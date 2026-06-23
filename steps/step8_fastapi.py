"""
第8步：FastAPI 服务化
基于 step7.5 的模块化代码，把 RAG 流水线封装成 HTTP API：
  - POST /api/chat  → 输入 query，返回 LLM 回答 + 检索到的文档
  - 启动时自动加载 FAISS 索引，整个服务生命周期复用
"""
try:
    from steps._bootstrap import DATA_DIR, DOCS_DIR
except ModuleNotFoundError:
    from _bootstrap import DATA_DIR, DOCS_DIR

import sys, os, httpx
from fastapi import FastAPI
from pydantic import BaseModel
from contextlib import asynccontextmanager

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

# ==================== 2. 创建 FastAPI 应用 ====================
app = FastAPI(title="my-rag API", lifespan=lifespan)

# ==================== 3. 请求/响应模型 ====================
class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

# ==================== 4. 核心接口 ====================
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    query = request.query

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

    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "stream": False}

    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]

    sources = [doc.metadata.get("source", "") for doc in reranked]
    return ChatResponse(answer=answer, sources=sources)


# ==================== 5. 启动 ====================
if __name__ == "__main__":
    import asyncio, uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
