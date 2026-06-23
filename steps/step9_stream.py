"""
第9步：流式输出（SSE）
基于 step8，新增流式接口：
  - POST /api/chat         → 一次性返回（保留）
  - POST /api/chat/stream  → SSE 流式，一个字一个字推送

原理：LLM API 设 stream=True，服务端边收边推，客户端边收边显示。
"""
try:
    from steps._bootstrap import DATA_DIR, DOCS_DIR
except ModuleNotFoundError:
    from _bootstrap import DATA_DIR, DOCS_DIR

import sys, os, httpx, json, asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from sse_starlette.sse import EventSourceResponse

sys.stdout.reconfigure(encoding="utf-8")

from configs import SEARCH_TOP_K, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE
from core.embedding import generate_token
from core.splitter import load_and_split_documents
from core.indexer import build_index, search
from core.reranker import Reranker

# ==================== 1. 启动时加载索引 ====================
os.makedirs(DATA_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Server] 加载 FAISS 索引...")
    app.state.index, app.state.documents = build_index(
        documents=load_and_split_documents(DOCS_DIR),
        data_dir=DATA_DIR,
    )
    app.state.reranker = Reranker()
    print("[Server] 索引就绪，服务启动")
    yield
    print("[Server] 服务关闭")

app = FastAPI(title="my-rag API（流式）", lifespan=lifespan)

# ==================== 2. 模型定义 ====================
class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

# ==================== 3. 辅-检索+拼 prompt ====================
def retrieve_and_build_prompt(query: str, app) -> tuple[str, list]:
    """执行两阶段检索，返回 (prompt, sources)"""
    candidates = search(app.state.index, app.state.documents, query, top_k=SEARCH_TOP_K)
    reranked = app.state.reranker.rerank(query, candidates)
    context = "\n".join([doc.page_content for doc in reranked])
    prompt = f"""根据以下已知信息，简洁和专业的来回答问题。
如果无法从中得到答案，请说"根据已知信息无法回答该问题"。

<已知信息>
{context}
</已知信息>

<问题>
{query}
</问题>"""
    sources = [doc.metadata.get("source", "") for doc in reranked]
    return prompt, sources

# ==================== 4. 非流式接口（保留） ====================
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """一次性返回完整答案"""
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

# ==================== ★ 5. 流式接口（step9 新增） ★ ====================
@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    SSE 流式接口。
    客户端收到的数据格式（每个事件一行）：
      data: {"token": "R"}
      data: {"token": "AG"}
      data: {"token": "是"}
      ...
      data: {"sources": ["rag-intro.md", ...]}    ← 最后一条
    """
    prompt, sources = retrieve_and_build_prompt(request.query, app)
    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "stream": True}

    async def event_generator():
        """异步生成器：逐 token 从智谱拿到，转成 SSE 事件发出去"""
        with httpx.Client(timeout=60) as client:
            with client.stream("POST", ZHIPU_CHAT_URL, headers=headers, json=data) as resp:
                resp.raise_for_status()
                full_text = ""
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
                # 最后一条：附上来源和完整文本
                yield {"event": "done", "data": json.dumps({"sources": sources, "full_text": full_text})}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
