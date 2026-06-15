import asyncio
import json
import re

import httpx

from configs import MEMORY_VECTOR_TOP_K, SEARCH_TOP_K, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE
from core.embedding import embed_texts, generate_token
from core.indexer import search, search_by_vector
from core.memory_vector_store import search_memory_ids, search_memory_ids_by_vector
from core.memory import (
    count_user_messages,
    create_conversation,
    get_conversation_title,
    get_history,
    save_message,
    set_conversation_title,
)
from prompts.conversation_prompts import build_conversation_title_prompt
from prompts.memory_prompts import (
    build_memory_dedupe_prompt,
    build_memory_extract_prompt,
    build_memory_summary_extract_prompt,
)
from prompts.rag_prompts import build_memory_system_prompt, build_rag_user_prompt
from repositories.memory_repository import create_memory as save_long_term_memory
from repositories.memory_repository import format_memories_text, get_enabled_memory_text, list_memories
from repositories.memory_repository import list_memories_by_ids, memory_content_exists
from repositories.memory_repository import update_memory as update_long_term_memory

TITLE_MAX_CHARS = 18
ALLOWED_MEMORY_CATEGORIES = {"profile", "preference", "project", "goal", "fact", "general"}
MEMORY_SUMMARY_INTERVAL = 6
MEMORY_SUMMARY_WINDOW = 8
MEMORY_TRIGGER_KEYWORDS = [
    "记住",
    "帮我记",
    "你要记得",
    "以后",
    "下次",
    "我叫",
    "我是",
    "我现在是",
    "我正在",
    "我喜欢",
    "我不喜欢",
    "我希望",
    "我的项目",
    "我的目标",
    "我的偏好",
]


def retrieve(query: str, app) -> tuple[str, list[str]]:
    candidates = search(app.state.index, app.state.documents, query, top_k=SEARCH_TOP_K)
    reranked = app.state.reranker.rerank(query, candidates)
    context = "\n".join([doc.page_content for doc in reranked])
    sources = [doc.metadata.get("source", "") for doc in reranked]
    return context, sources


def retrieve_with_vector(query: str, query_vector: list[float], app) -> tuple[str, list[str]]:
    candidates = search_by_vector(app.state.index, app.state.documents, query_vector, top_k=SEARCH_TOP_K)
    reranked = app.state.reranker.rerank(query, candidates)
    context = "\n".join([doc.page_content for doc in reranked])
    sources = [doc.metadata.get("source", "") for doc in reranked]
    return context, sources


async def get_relevant_memory_text(query: str) -> str:
    try:
        memory_ids = await asyncio.to_thread(search_memory_ids, query, MEMORY_VECTOR_TOP_K)
        memories = await list_memories_by_ids(memory_ids)
        if memories:
            return format_memories_text(memories)
        return ""
    except Exception as exc:
        print(f"[Milvus] 长期记忆向量检索失败，回退到默认记忆读取: {exc}")
        return await get_enabled_memory_text()


async def get_relevant_memory_text_with_vector(query_vector: list[float]) -> str:
    try:
        memory_ids = await asyncio.to_thread(search_memory_ids_by_vector, query_vector, MEMORY_VECTOR_TOP_K)
        memories = await list_memories_by_ids(memory_ids)
        if memories:
            return format_memories_text(memories)
        return ""
    except Exception as exc:
        print(f"[Milvus] 长期记忆向量检索失败，回退到默认记忆读取: {exc}")
        return await get_enabled_memory_text()


async def embed_query(query: str) -> list[float]:
    vectors = await asyncio.to_thread(embed_texts, [query])
    return vectors[0]


def trim_title(title: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    title = title.strip(' \t\r\n"\'`''""，。！？；：、…—·')
    return title if len(title) <= max_chars else title[:max_chars].rstrip(' \t\r\n"\'`''""，。！？；：、…—·')


def fallback_title(query: str) -> str:
    title = re.sub(r"\s+", " ", query or "").strip()
    title = re.sub(r"^(请|帮我|给我|麻烦|你能不能|能不能|可以帮我|请你)\s*", "", title)
    return trim_title(title) or "新对话"


async def generate_conversation_title(query: str, answer: str) -> str:
    prompt = build_conversation_title_prompt(query, answer, TITLE_MAX_CHARS)
    data = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].splitlines()[0]
    except Exception:
        return ""


async def maybe_set_first_turn_title(cid: str, history: list, query: str, answer: str) -> str:
    if history:
        return ""
    existing = await get_conversation_title(cid)
    if existing:
        return existing
    generated = await generate_conversation_title(query, answer)
    title = trim_title(generated) or fallback_title(query)
    await set_conversation_title(cid, title)
    return title


def parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def normalize_memory_item(item: dict) -> dict | None:
    content = " ".join(str(item.get("content", "")).split())
    if not content or len(content) < 6:
        return None

    category = str(item.get("category", "general")).strip().lower() or "general"
    # 如果模型没给分类或者乱写，就默认 general
    if category not in ALLOWED_MEMORY_CATEGORIES:
        category = "general"

    try:
        importance = int(item.get("importance", 3))
    except (TypeError, ValueError):
        importance = 3
    importance = max(1, min(importance, 5))

    return {"content": content, "category": category, "importance": importance}


def should_extract_memory_by_rule(query: str) -> bool:
    query = query or ""
    return any(keyword in query for keyword in MEMORY_TRIGGER_KEYWORDS)


def should_extract_memory_by_interval(user_message_count: int) -> bool:
    return user_message_count > 0 and user_message_count % MEMORY_SUMMARY_INTERVAL == 0


def normalize_memory_decision(payload: dict, fallback_item: dict, existing_ids: set[int]) -> dict:
    action = str(payload.get("action", "create")).strip().lower()
    if action not in {"create", "ignore", "update"}:
        action = "create"

    normalized_item = normalize_memory_item({
        "content": payload.get("content") or fallback_item["content"],
        "category": payload.get("category") or fallback_item["category"],
        "importance": payload.get("importance", fallback_item["importance"]),
    })
    if normalized_item is None:
        normalized_item = fallback_item

    memory_id = payload.get("memory_id")
    try:
        memory_id = int(memory_id) if memory_id is not None else None
    except (TypeError, ValueError):
        memory_id = None

    if action == "update" and memory_id not in existing_ids:
        action = "create"
        memory_id = None
    if action != "update":
        memory_id = None

    return {"action": action, "memory_id": memory_id, **normalized_item}


async def decide_memory_save_action(item: dict) -> dict:
    # 只和同类型记忆比较，避免“用户偏好”和“项目背景”互相误判重复。
    existing_memories = await list_memories(
        include_disabled=False,
        limit=20,
        category=item["category"],
    )
    if not existing_memories:
        return {"action": "create", "memory_id": None, **item}

    prompt = build_memory_dedupe_prompt(item, existing_memories)
    data = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "stream": False,
    }
    existing_ids = {memory["id"] for memory in existing_memories}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[Memory] 语义去重失败，按新记忆保存: {exc}")
        return {"action": "create", "memory_id": None, **item}

    payload = parse_json_object(raw)
    return normalize_memory_decision(payload, item, existing_ids)


def format_history_for_memory_summary(history: list[dict]) -> str:
    lines = []
    role_names = {"user": "用户", "assistant": "助手"}
    for item in history:
        role = role_names.get(item["role"], item["role"])
        content = " ".join((item.get("content") or "").split())
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def extract_and_save_by_prompt(prompt: str, conversation_id: str) -> list[dict]:
    data = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[Memory] 自动提取失败: {exc}")
        return []

    # 把大模型返回的原始文本 raw，清洗一下，截取 JSON，解析成 Python dict，如果失败就返回 {}
    payload = parse_json_object(raw)

    raw_items = payload.get("memories", [])

    # 如果memories不是列表，说明模型返回格式不符合要求，这次就不保存任何长期记忆，直接返回空列表
    # 即使模型输出格式错了，也不会影响主聊天流程。
    if not isinstance(raw_items, list):
        return []

    saved = []
    for raw_item in raw_items[:3]:
        if not isinstance(raw_item, dict):
            continue
        item = normalize_memory_item(raw_item)
        if item is None:
            continue
        # 如果 mysql 的 memories 表里已经有完全相同的启用记忆，就跳过，不重复保存。
        if await memory_content_exists(item["content"]):
            continue
        decision = await decide_memory_save_action(item)
        if decision["action"] == "ignore":
            continue
        try:
            if decision["action"] == "update":
                updated = await update_long_term_memory(
                    memory_id=decision["memory_id"],
                    content=decision["content"],
                    category=decision["category"],
                    importance=decision["importance"],
                    enabled=True,
                )
                if updated:
                    saved.append(updated)
            else:
                saved.append(await save_long_term_memory(
                    content=decision["content"],
                    category=decision["category"],
                    importance=decision["importance"],
                    source_conversation_id=conversation_id,
                ))
        except ValueError:
            continue

    if saved:
        print(f"[Memory] 自动写入/更新 {len(saved)} 条长期记忆")
    return saved


async def extract_and_save_long_term_memories(query: str, answer: str, conversation_id: str) -> list[dict]:
    prompt = build_memory_extract_prompt(query, answer)
    return await extract_and_save_by_prompt(prompt, conversation_id)


async def summarize_and_save_recent_memories(conversation_id: str) -> list[dict]:
    # 因为一轮对话通常包含：用户消息 1 条，助手消息 1 条，所以 MEMORY_SUMMARY_WINDOW * 2
    history = await get_history(conversation_id, MEMORY_SUMMARY_WINDOW * 2)
    conversation_text = format_history_for_memory_summary(history)
    if not conversation_text:
        return []
    prompt = build_memory_summary_extract_prompt(conversation_text)
    return await extract_and_save_by_prompt(prompt, conversation_id)


async def maybe_extract_and_save_long_term_memories(
    query: str,
    answer: str,
    conversation_id: str,
) -> list[dict]:
    user_message_count = await count_user_messages(conversation_id)
    # 规则触发（根据特定的关键词）
    by_rule = should_extract_memory_by_rule(query)
    # 定期总结
    by_interval = should_extract_memory_by_interval(user_message_count)
    if not by_rule and not by_interval:
        return []

    saved = []
    if by_rule:
        print("[Memory] 触发长期记忆提取：规则触发")
        saved.extend(await extract_and_save_long_term_memories(query, answer, conversation_id))
    if by_interval:
        print(f"[Memory] 触发长期记忆总结：第 {user_message_count} 轮，读取最近 {MEMORY_SUMMARY_WINDOW} 轮")
        saved.extend(await summarize_and_save_recent_memories(conversation_id))
    return saved


def build_auth_headers() -> dict:
    token = generate_token()
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def chat_once(app, query: str) -> dict:
    context, sources = retrieve(query, app)
    data = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": build_rag_user_prompt(context, query)}],
        "temperature": TEMPERATURE,
        "stream": False,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
    return {"answer": answer, "sources": sources}


async def chat_with_memory(app, query: str, conversation_id: str = "", history_len: int = 10) -> dict:
    cid = conversation_id or await create_conversation()
    history = await get_history(cid, history_len)
    context, sources = retrieve(query, app)
    long_term_memory = await get_relevant_memory_text(query)
    messages = build_memory_messages(query, history, context, long_term_memory)
    data = {"model": LLM_MODEL, "messages": messages, "temperature": TEMPERATURE, "stream": False}

    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]

    await save_message(cid, "user", query)
    await save_message(cid, "assistant", answer)
    title = await maybe_set_first_turn_title(cid, history, query, answer)
    await maybe_extract_and_save_long_term_memories(query, answer, cid)
    return {"answer": answer, "sources": sources, "conversation_id": cid, "title": title}


def build_memory_messages(query: str, history: list, context: str, long_term_memory: str = "") -> list[dict]:
    messages = [{"role": "system", "content": build_memory_system_prompt(context, long_term_memory)}]
    messages += [{"role": item["role"], "content": item["content"]} for item in history]
    messages.append({"role": "user", "content": query})
    return messages


async def stream_chat_with_memory(app, query: str, conversation_id: str = "", history_len: int = 10):
    cid = conversation_id or await create_conversation()
    # 查短期记忆
    history = await get_history(cid, history_len)
    context, sources = retrieve(query, app)
    # 查长期记忆
    long_term_memory = await get_relevant_memory_text(query)
    messages = build_memory_messages(query, history, context, long_term_memory)
    data = {"model": LLM_MODEL, "messages": messages, "temperature": TEMPERATURE, "stream": True}

    full_text = ""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip() or "[DONE]" in line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if choices := chunk.get("choices"):
                    if content := choices[0].get("delta", {}).get("content"):
                        full_text += content
                        yield {"event": "token", "data": json.dumps({"token": content}, ensure_ascii=False)}

    await save_message(cid, "user", query)
    await save_message(cid, "assistant", full_text)
    title = await maybe_set_first_turn_title(cid, history, query, full_text)
    # 自动提取长期记忆：规则触发提取当前轮，定期触发总结最近几轮。
    await maybe_extract_and_save_long_term_memories(query, full_text, cid)
    done = {"sources": sources, "conversation_id": cid, "title": title}
    yield {"event": "done", "data": json.dumps(done, ensure_ascii=False)}
