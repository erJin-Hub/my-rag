import json
import re

import httpx

from configs import SEARCH_TOP_K, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE
from core.embedding import generate_token
from core.indexer import search
from core.memory import (
    create_conversation,
    get_conversation_title,
    get_history,
    save_message,
    set_conversation_title,
)
from prompts.conversation_prompts import build_conversation_title_prompt
from prompts.memory_prompts import build_memory_extract_prompt
from prompts.rag_prompts import build_memory_system_prompt, build_rag_user_prompt
from repositories.memory_repository import create_memory as save_long_term_memory
from repositories.memory_repository import get_enabled_memory_text, memory_content_exists

TITLE_MAX_CHARS = 18
ALLOWED_MEMORY_CATEGORIES = {"profile", "preference", "project", "goal", "fact", "general"}


def retrieve(query: str, app) -> tuple[str, list[str]]:
    candidates = search(app.state.index, app.state.documents, query, top_k=SEARCH_TOP_K)
    reranked = app.state.reranker.rerank(query, candidates)
    context = "\n".join([doc.page_content for doc in reranked])
    sources = [doc.metadata.get("source", "") for doc in reranked]
    return context, sources


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


async def extract_and_save_long_term_memories(query: str, answer: str, conversation_id: str) -> list[dict]:
    prompt = build_memory_extract_prompt(query, answer)
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
        # 如果 memories 表里已经有完全相同的启用记忆，就跳过，不重复保存。
        if await memory_content_exists(item["content"]):
            continue
        try:
            saved.append(await save_long_term_memory(
                content=item["content"],
                category=item["category"],
                importance=item["importance"],
                source_conversation_id=conversation_id,
            ))
        except ValueError:
            continue

    if saved:
        print(f"[Memory] 自动保存 {len(saved)} 条长期记忆")
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
    long_term_memory = await get_enabled_memory_text()
    messages = build_memory_messages(query, history, context, long_term_memory)
    data = {"model": LLM_MODEL, "messages": messages, "temperature": TEMPERATURE, "stream": False}

    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=build_auth_headers(), json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]

    await save_message(cid, "user", query)
    await save_message(cid, "assistant", answer)
    title = await maybe_set_first_turn_title(cid, history, query, answer)
    await extract_and_save_long_term_memories(query, answer, cid)
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
    long_term_memory = await get_enabled_memory_text()
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
    # 自动提取长期记忆
    await extract_and_save_long_term_memories(query, full_text, cid)
    done = {"sources": sources, "conversation_id": cid, "title": title}
    yield {"event": "done", "data": json.dumps(done, ensure_ascii=False)}
