"""
第10步：对话记忆（MySQL 版）
基于 step9，新增多轮对话能力：
  - POST /api/conversations/new         -> 创建新对话
  - POST /api/chat/memory               -> 带记忆的非流式对话
  - POST /api/chat/memory/stream        -> 带记忆的流式对话
  - GET  /api/conversations/{id}/history -> 查看历史
  - POST /api/chat                      -> 普通 RAG（兼容保留）
"""
import sys, os, httpx, json
from fastapi import FastAPI
from pydantic import BaseModel
from contextlib import asynccontextmanager
from sse_starlette.sse import EventSourceResponse

sys.stdout.reconfigure(encoding="utf-8")

from configs import (SEARCH_TOP_K, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE,
                     MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
from core.embedding import generate_token
from core.splitter import load_and_split_documents
from core.indexer import build_index, search
from core.reranker import Reranker
from core.memory import init_pool, close_pool, save_message, get_history, new_conversation_id

# ==================== 1. 启动 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
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

class NewConvResponse(BaseModel):
    conversation_id: str

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
    return NewConvResponse(conversation_id=new_conversation_id())

# ==================== 6. 查看历史 ====================
@app.get("/api/conversations/{conversation_id}/history")
async def conversation_history(conversation_id: str):
    history = await get_history(conversation_id)
    return {"conversation_id": conversation_id, "messages": history}

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

    return ChatResponse(answer=answer, sources=sources)

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
        with httpx.Client(timeout=60) as client:
            with client.stream("POST", ZHIPU_CHAT_URL, headers=headers, json=data) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.strip() or "[DONE]" in line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        chunk = json.loads(line)
                        if choices := chunk.get("choices"):
                            if content := choices[0].get("delta", {}).get("content"):
                                full_text += content
                                yield {"event": "token", "data": json.dumps({"token": content})}
                    except json.JSONDecodeError:
                        continue
        await save_message(cid, "user", request.query)
        await save_message(cid, "assistant", full_text)
        yield {"event": "done", "data": json.dumps({"sources": sources, "conversation_id": cid})}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
