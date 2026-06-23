"""
第10步：对话记忆（MySQL 版）
基于 step9，新增多轮对话能力：
  - POST /api/conversations/new         -> 创建新对话
  - POST /api/chat/memory               -> 带记忆的非流式对话
  - POST /api/chat/memory/stream        -> 带记忆的流式对话
  - GET  /api/conversations/{id}/history -> 查看历史
  - DELETE /api/conversations/{id}       -> 删除对话
  - POST /api/chat                      -> 普通 RAG（兼容保留）
"""
try:
    from steps._bootstrap import DATA_DIR, DOCS_DIR
except ModuleNotFoundError:
    from _bootstrap import DATA_DIR, DOCS_DIR

import json
import os
import re
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

sys.stdout.reconfigure(encoding="utf-8")

from configs import (SEARCH_TOP_K, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE,
                     MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
from core.embedding import generate_token
from core.indexer import build_index, search
from core.memory import (
    close_pool,
    create_conversation as create_memory_conversation,
    delete_conversation,
    get_conversation_title,
    get_history,
    init_pool,
    list_conversations,
    new_conversation_id,
    save_message,
    set_conversation_title,
)
from core.reranker import Reranker
from core.splitter import load_and_split_documents

# ==================== 1. 启动 ====================
TITLE_MAX_CHARS = 18
os.makedirs(DATA_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Server] 加载 FAISS 索引...")
    app.state.index, app.state.documents = build_index(
        documents=load_and_split_documents(DOCS_DIR), data_dir=DATA_DIR)
    app.state.reranker = Reranker()
    await init_pool(MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
    print("[Server] 索引就绪")
    yield
    await close_pool()
    print("[Server] 服务关闭")


app = FastAPI(title="my-rag API (MySQL)", lifespan=lifespan)

# ==================== 2. 模型 ====================
class ChatRequest(BaseModel):
    query: str


class MemoryChatRequest(BaseModel):
    query: str
    conversation_id: str = ""
    history_len: int = 10


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    conversation_id: str = ""
    title: str = ""


class NewConvResponse(BaseModel):
    conversation_id: str
    title: str = ""


# ==================== 2.1 会话标题 ====================
def trim_title(title: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    title = title.strip(" \t\r\n\"'`“”‘’《》<>，,。.!！?？:：;；、-—_")
    if len(title) <= max_chars:
        return title
    return title[:max_chars].rstrip(" \t\r\n\"'`“”‘’《》<>，,。.!！?？:：;；、-—_")


def fallback_title(query: str) -> str:
    title = re.sub(r"\s+", " ", query or "").strip()
    title = re.sub(r"^(请|帮我|给我|麻烦|你能不能|能不能|可以帮我|请你)\s*", "", title)
    return trim_title(title) or "新对话"


def normalize_generated_title(raw_title: str, query: str) -> str:
    title = (raw_title or "").splitlines()[0]
    title = re.sub(r"^\s*(标题|会话标题|标签名)\s*[:：]\s*", "", title)
    title = re.sub(r"\s+", " ", title)
    return trim_title(title) or fallback_title(query)


async def generate_conversation_title(query: str, answer: str) -> str:
    prompt = f"""请根据首轮对话内容生成一个简短的会话标签名，风格参考 DeepSeek 的左侧会话标题。
要求：
1. 抽象概括用户真正想做的事，不要直接截断原问题。
2. 中文优先，最多 {TITLE_MAX_CHARS} 个字。
3. 不要输出引号、句号、冒号、编号、表情。
4. 不要使用“会话”“问题”“关于”等空泛词。
5. 只输出标签名本身。

用户首问：
{query}

助手首答：
{answer[:1200]}"""

    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
            resp.raise_for_status()
            raw_title = resp.json()["choices"][0]["message"]["content"]
        return normalize_generated_title(raw_title, query)
    except Exception as exc:
        print(f"[Title] 生成失败，使用回退标题: {exc}")
        return fallback_title(query)


async def maybe_set_first_turn_title(
    conversation_id: str,
    previous_history: list[dict],
    query: str,
    answer: str,
) -> str:
    existing_title = await get_conversation_title(conversation_id)
    if existing_title:
        return existing_title
    if previous_history:
        return ""

    title = await generate_conversation_title(query, answer)
    await set_conversation_title(conversation_id, title)
    return title


# ==================== 3. 辅-检索 ====================
def retrieve(query: str, app) -> tuple:
    candidates = search(app.state.index, app.state.documents, query, top_k=SEARCH_TOP_K)
    reranked = app.state.reranker.rerank(query, candidates)
    context = "\n".join([doc.page_content for doc in reranked])
    sources = [doc.metadata.get("source", "") for doc in reranked]
    return context, sources


def retrieve_and_build_prompt(query: str, app) -> tuple:
    context, sources = retrieve(query, app)
    prompt = f"""根据以下已知信息，简洁和专业的来回答问题。
如果无法从中得到答案，请说"根据已知信息无法回答该问题"。

<已知信息>
{context}
</已知信息>

<问题>
{query}
</问题>"""
    return prompt, sources


# ==================== 4. 普通接口（无记忆） ====================
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    prompt, sources = retrieve_and_build_prompt(request.query, app)
    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "stream": False}
    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
    return ChatResponse(answer=answer, sources=sources)


# ==================== 5. 创建新对话 ====================
@app.post("/api/conversations/new", response_model=NewConvResponse)
async def create_conversation():
    conversation_id = await create_memory_conversation()
    return NewConvResponse(conversation_id=conversation_id)


# ==================== 6. 查看历史 ====================
@app.get("/api/conversations")
async def conversations():
    return {"items": await list_conversations()}


@app.get("/api/conversations/{conversation_id}/history")
async def conversation_history(conversation_id: str):
    history = await get_history(conversation_id)
    title = await get_conversation_title(conversation_id)
    return {"conversation_id": conversation_id, "title": title, "messages": history}


# ==================== 6.1 删除对话 ====================
@app.delete("/api/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    deleted = await delete_conversation(conversation_id)
    return {"conversation_id": conversation_id, "deleted_messages": deleted}


# ==================== 7. 带记忆的非流式接口 ====================
@app.post("/api/chat/memory", response_model=ChatResponse)
async def chat_memory(request: MemoryChatRequest):
    cid = request.conversation_id or new_conversation_id()

    history = await get_history(cid, request.history_len)
    history_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    context, sources = retrieve(request.query, app)

    system_prompt = f"""你是AI技术顾问。根据已知信息回答问题，无法回答时请说"根据已知信息无法回答该问题"。
<已知信息>
{context}
</已知信息>"""

    messages = [{"role": "system", "content": system_prompt}]
    messages += history_messages
    messages.append({"role": "user", "content": request.query})

    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": messages, "temperature": TEMPERATURE, "stream": False}

    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]

    await save_message(cid, "user", request.query)
    await save_message(cid, "assistant", answer)
    title = await maybe_set_first_turn_title(cid, history, request.query, answer)

    return ChatResponse(answer=answer, sources=sources, conversation_id=cid, title=title)


# ==================== 8. 带记忆的流式接口 ====================
@app.post("/api/chat/memory/stream")
async def chat_memory_stream(request: MemoryChatRequest):
    cid = request.conversation_id or new_conversation_id()
    history = await get_history(cid, request.history_len)
    history_messages = [{"role": m["role"], "content": m["content"]} for m in history]
    context, sources = retrieve(request.query, app)

    system_prompt = f"""你是AI技术顾问。根据已知信息回答问题，无法回答时请说"根据已知信息无法回答该问题"。
<已知信息>
{context}
</已知信息>"""

    messages = [{"role": "system", "content": system_prompt}]
    messages += history_messages
    messages.append({"role": "user", "content": request.query})

    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": messages, "temperature": TEMPERATURE, "stream": True}

    async def event_generator():
        full_text = ""
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", ZHIPU_CHAT_URL, headers=headers, json=data) as resp:
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
        await save_message(cid, "user", request.query)
        await save_message(cid, "assistant", full_text)
        title = await maybe_set_first_turn_title(cid, history, request.query, full_text)
        done_data = {"sources": sources, "conversation_id": cid, "title": title}
        yield {"event": "done", "data": json.dumps(done_data, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
