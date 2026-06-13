"""
my-rag 完整 API —— 带前端 UI

主入口只负责：
  - 初始化 FAISS 索引、Reranker、数据库连接
  - 挂载静态前端文件
  - 注册按功能拆分的 API Router
"""
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

sys.stdout.reconfigure(encoding="utf-8")

from configs import MYSQL_DATABASE, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER
from configs.app_paths import DATA_DIR, DOCS_DIR, WEB_DIR
from core.indexer import build_index
from core.memory import close_pool, init_pool
from core.reranker import Reranker
from core.splitter import load_and_split_documents
from routers import chat_router, conversation_router, document_router, memory_router, page_router

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Server] 加载 FAISS 索引...")
    app.state.index, app.state.documents = build_index(
        documents=load_and_split_documents(DOCS_DIR),
        data_dir=DATA_DIR,
    )
    app.state.reranker = Reranker()
    await init_pool(MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
    print(f"[Server] 索引就绪（{app.state.index.ntotal} 个文档块）")
    yield
    await close_pool()
    print("[Server] 服务关闭")


app = FastAPI(title="my-rag", lifespan=lifespan)

app.include_router(page_router.router)
app.include_router(chat_router.router)
app.include_router(conversation_router.router)
app.include_router(memory_router.router)
app.include_router(document_router.router)

if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    print("[Server] 前端已挂载: http://127.0.0.1:8000/static/index.html")


if __name__ == "__main__":
    import asyncio
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()
