"""
my-rag 完整 API —— 带前端 UI
基于 step10，集成 web 前端页面 + 文档上传功能
接口：
  - POST /api/chat                  普通 RAG
  - POST /api/chat/memory           带记忆的非流式对话
  - POST /api/chat/memory/stream    带记忆的流式对话
  - POST /api/conversations/new     创建新对话
  - GET  /api/conversations         获取所有对话列表
  - GET  /api/conversations/{id}/history  查看对话历史
  - DELETE /api/conversations/{id}  删除对话
  - POST /api/documents/upload      上传文档
  - GET  /api/documents/list        查看已入库文档
  - /static/*                       前端页面
"""
import os, sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

sys.stdout.reconfigure(encoding="utf-8")

import configs
from configs import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
from core.indexer import build_index
from core.reranker import Reranker
from core.splitter import load_and_split_documents
from core.memory import init_pool, close_pool
from schemas.chat import ChatRequest, MemoryChatRequest, ChatResponse, NewConvResponse, UploadResponse
from services.chat_service import chat_once, chat_with_memory, stream_chat_with_memory
from services.conversation_service import (
    create_new_conversation,
    get_all_conversations,
    get_conversation_history,
    remove_conversation_by_id,
)
from services.document_service import list_knowledge_documents, upload_document_to_knowledge_base

# ==================== 1. 启动 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
DOCS_PATH = os.path.join(DATA_DIR, "documents.json")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Server] 加载 FAISS 索引...")
    app.state.index, app.state.documents = build_index(
        documents=load_and_split_documents(DOCS_DIR), data_dir=DATA_DIR)
    app.state.reranker = Reranker()
    await init_pool(MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
    print(f"[Server] 索引就绪（{app.state.index.ntotal} 个文档块）")
    yield
    await close_pool()
    print("[Server] 服务关闭")


app = FastAPI(title="my-rag", lifespan=lifespan)


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/documents")
async def documents_page():
    return FileResponse(os.path.join(WEB_DIR, "documents.html"))


# ==================== 2. 静态文件 ====================
if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    print(f"[Server] 前端已挂载: http://127.0.0.1:8000/static/index.html")

# ==================== 3. 普通 RAG ====================
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    return ChatResponse(**chat_once(app, request.query))

# ==================== 4. 对话管理 ====================
@app.post("/api/conversations/new", response_model=NewConvResponse)
async def new_conversation():
    return NewConvResponse(**await create_new_conversation())

@app.get("/api/conversations")
async def conversations():
    return await get_all_conversations()

@app.get("/api/conversations/{conversation_id}/history")
async def conversation_history(conversation_id: str):
    return await get_conversation_history(conversation_id)

@app.delete("/api/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    return await remove_conversation_by_id(conversation_id)

# ==================== 5. 带记忆的非流式 ====================
# @app.post("/api/chat/memory", response_model=ChatResponse)
# async def chat_memory(request: MemoryChatRequest):
#     result = await chat_with_memory(app, request.query, request.conversation_id, request.history_len)
#     return ChatResponse(**result)

# ==================== 6. 带记忆的流式（前端用这个） ====================
@app.post("/api/chat/memory/stream")
async def chat_memory_stream(request: MemoryChatRequest):
    return EventSourceResponse(
        stream_chat_with_memory(app, request.query, request.conversation_id, request.history_len)
    )

# ==================== 7. 文档上传 ====================
@app.post("/api/documents/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    result = await upload_document_to_knowledge_base(app, file, DOCS_DIR, INDEX_PATH, DOCS_PATH)
    return UploadResponse(**result)

# ==================== 8. 文档列表 ====================
@app.get("/api/documents/list")
def list_documents():
    return list_knowledge_documents(app)


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
