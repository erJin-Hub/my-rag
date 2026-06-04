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
import json, os, re, sys
from contextlib import asynccontextmanager
from pathlib import Path
from collections import Counter

import httpx, numpy as np, faiss
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

sys.stdout.reconfigure(encoding="utf-8")

import configs
from configs import (SEARCH_TOP_K, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE,
                     MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
from core.embedding import generate_token, embed_texts
from core.indexer import build_index, search
from core.reranker import Reranker
from core.splitter import load_and_split_documents
from core.memory import (
    init_pool, close_pool, save_message, get_history,
    new_conversation_id, list_conversations, delete_conversation,
    create_conversation, get_conversation_title, set_conversation_title,
    ensure_conversation,
)
from langchain_core.documents import Document

# ==================== 1. 启动 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
DOCS_PATH = os.path.join(DATA_DIR, "documents.json")
TITLE_MAX_CHARS = 18
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
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


# ==================== 2. 静态文件 ====================
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    print(f"[Server] 前端已挂载: http://127.0.0.1:8000/static/index.html")

# ==================== 3. 模型 ====================
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

class UploadResponse(BaseModel):
    filename: str
    chunks: int
    total_chunks: int

# ==================== 4. 辅-检索 ====================
def retrieve(query: str, app) -> tuple:
    candidates = search(app.state.index, app.state.documents, query, top_k=SEARCH_TOP_K)
    reranked = app.state.reranker.rerank(query, candidates)
    context = "\n".join([doc.page_content for doc in reranked])
    sources = [doc.metadata.get("source", "") for doc in reranked]
    return context, sources

# ==================== 5. 标题生成 ====================
def trim_title(title: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    title = title.strip(' \t\r\n"\'`''""，。！？；：、…—·')
    return title if len(title) <= max_chars else title[:max_chars].rstrip(' \t\r\n"\'`''""，。！？；：、…—·')

def fallback_title(query: str) -> str:
    title = re.sub(r"\s+", " ", query or "").strip()
    title = re.sub(r"^(请|帮我|给我|麻烦|你能不能|能不能|可以帮我|请你)\s*", "", title)
    return trim_title(title) or "新对话"

async def generate_conversation_title(query: str, answer: str) -> str:
    prompt = f"""根据首轮对话内容生成一个简短的会话标签名，风格参考 DeepSeek 的左侧会话标题。
要求：
1. 抽象概括用户真正想做的事，不要直接截断原问题。
2. 中文优先，最多 {TITLE_MAX_CHARS} 个字。
3. 不要输出引号、句号、冒号、编号、表情。
4. 不要使用"会话""问题""关于"等空泛词。
5. 只输出标签名本身。

用户首问：
{query}

助手首答：
{answer[:1200]}"""
    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
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

# ==================== 6. 普通 RAG ====================
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    context, sources = retrieve(request.query, app)
    prompt = f"""根据以下已知信息，简洁和专业的来回答问题。
如果无法从中得到答案，请说"根据已知信息无法回答该问题"。

<已知信息>
{context}
</已知信息>

<问题>
{request.query}
</问题>"""
    token = generate_token()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "stream": False}
    with httpx.Client(timeout=60) as client:
        resp = client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
    return ChatResponse(answer=answer, sources=sources)

# ==================== 7. 对话管理 ====================
@app.post("/api/conversations/new", response_model=NewConvResponse)
async def new_conversation():
    cid = await create_conversation()
    title = await get_conversation_title(cid)
    return NewConvResponse(conversation_id=cid, title=title)

@app.get("/api/conversations")
async def conversations():
    return {"items": await list_conversations()}

@app.get("/api/conversations/{conversation_id}/history")
async def conversation_history(conversation_id: str):
    history = await get_history(conversation_id)
    title = await get_conversation_title(conversation_id)
    return {"conversation_id": conversation_id, "title": title, "messages": history}

@app.delete("/api/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    deleted = await delete_conversation(conversation_id)
    return {"conversation_id": conversation_id, "deleted_messages": deleted}

# ==================== 8. 带记忆的非流式 ====================
@app.post("/api/chat/memory", response_model=ChatResponse)
async def chat_memory(request: MemoryChatRequest):
    cid = request.conversation_id or await create_conversation()
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

# ==================== 9. 带记忆的流式（前端用这个） ====================
@app.post("/api/chat/memory/stream")
async def chat_memory_stream(request: MemoryChatRequest):
    cid = request.conversation_id or await create_conversation()
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
        done = {"sources": sources, "conversation_id": cid, "title": title}
        yield {"event": "done", "data": json.dumps(done, ensure_ascii=False)}

    return EventSourceResponse(event_generator())

# ==================== 10. 文档上传 ====================
ALLOWED_SUFFIXES = {".txt", ".md"}

@app.post("/api/documents/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，只支持 {ALLOWED_SUFFIXES}")

    content = (await file.read()).decode("utf-8")
    file_path = os.path.join(DOCS_DIR, file.filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 切分单个文件
    from core.splitter import ChineseRecursiveTextSplitter, zh_title_enhance
    splitter = ChineseRecursiveTextSplitter(
        keep_separator=True, is_separator_regex=True,
        chunk_size=configs.CHUNK_SIZE, chunk_overlap=configs.CHUNK_OVERLAP,
    )
    doc = Document(page_content=content, metadata={"source": file.filename})
    new_chunks = splitter.split_documents([doc])
    if configs.ZH_TITLE_ENHANCE:
        new_chunks = zh_title_enhance(new_chunks)
    for i, chunk in enumerate(new_chunks):
        chunk.metadata["chunk"] = i
        chunk.metadata["source"] = file.filename

    if not new_chunks:
        os.remove(file_path)
        raise HTTPException(400, "文件内容为空或无法切分")

    # embedding + 追加
    texts = [c.page_content for c in new_chunks]
    embeddings = embed_texts(texts)
    app.state.index.add(np.array(embeddings, dtype=np.float32))
    app.state.documents.extend(new_chunks)

    # 持久化
    faiss.write_index(app.state.index, INDEX_PATH)
    doc_dicts = [{"content": d.page_content, "metadata": d.metadata} for d in app.state.documents]
    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc_dicts, f, ensure_ascii=False, indent=2)

    print(f"[Upload] {file.filename} -> {len(new_chunks)} 块，总计 {app.state.index.ntotal} 块")
    return UploadResponse(filename=file.filename, chunks=len(new_chunks), total_chunks=app.state.index.ntotal)

# ==================== 11. 文档列表 ====================
@app.get("/api/documents/list")
def list_documents():
    counter = Counter(d.metadata.get("source", "?") for d in app.state.documents)
    return {
        "total_chunks": app.state.index.ntotal,
        "files": [{"filename": k, "chunks": v} for k, v in counter.items()],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
