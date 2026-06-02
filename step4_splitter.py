"""
第4步：文本切分 — 长文档切成小块，检索更精准
"""
import httpx, jwt, time, json, os
import numpy as np
import faiss
from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

# ==================== 0. API 配置 ====================
API_KEY = "f319167f721645fe91aa4918d321b521.bPLyCmwCzSOr1Ttb"
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

def generate_token(apikey, exp_seconds=60):
    api_id, secret = apikey.split(".")
    payload = {"api_key": api_id, "exp": int(round(time.time()*1000)) + exp_seconds*1000,
               "timestamp": int(round(time.time()*1000))}
    return jwt.encode(payload, secret, algorithm="HS256",
                      headers={"alg": "HS256", "sign_type": "SIGN"})

def embed_texts(texts: List[str]) -> List[List[float]]:
    token = generate_token(API_KEY)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    embeddings = []
    with httpx.Client(timeout=30) as client:
        for text in texts:
            resp = client.post(EMBED_URL, headers=headers,
                               json={"model": "embedding-2", "input": text})
            embeddings.append(resp.json()["data"][0]["embedding"])
    return embeddings

# ==================== 1. 路径 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
DOCS_PATH = os.path.join(DATA_DIR, "documents.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 2. 加载 + 切分 ====================
CHUNK_SIZE = 200     # 每块最多 200 字符
CHUNK_OVERLAP = 50   # 相邻块重叠 50 字符

def load_and_split_documents(folder: str) -> List[Document]:
    """
    从文件夹加载文档，切分成小块
    切分器只创建一次，对所有文件复用。chunk_size=200，overlap=50。
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )

    all_chunks = []
    for file_path in Path(folder).iterdir():
        if file_path.is_file() and file_path.suffix in {".txt", ".md"}:
            content = file_path.read_text(encoding="utf-8")

            # 先包成一个 Document
            doc = Document(page_content=content, metadata={"source": file_path.name})

            # 切分
            chunks = text_splitter.split_documents([doc])

            # 每个小块继承来源信息
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk"] = i
                chunk.metadata["source"] = file_path.name

            all_chunks.extend(chunks)
            print(f"  [LOAD] {file_path.name} ({len(content)} 字) → 切成 {len(chunks)} 块")

    return all_chunks

# ==================== 3. 加载或构建索引 ====================
if os.path.exists(INDEX_PATH) and os.path.exists(DOCS_PATH):
    print("[OK] 从磁盘加载已有索引...")
    index = faiss.read_index(INDEX_PATH)
    with open(DOCS_PATH, "r", encoding="utf-8") as f:
        doc_dicts = json.load(f)
    documents = [Document(page_content=d["content"], metadata=d.get("metadata", {}))
                 for d in doc_dicts]
    print(f"[OK] 加载完成：{index.ntotal} 个文档块")
else:
    print(f"[INFO] 未找到索引，从 {DOCS_DIR} 加载并切分文档...")
    documents = load_and_split_documents(DOCS_DIR)

    texts = [doc.page_content for doc in documents]
    embeddings = embed_texts(texts)

    index = faiss.IndexFlatIP(len(embeddings[0]))
    index.add(np.array(embeddings, dtype=np.float32))

    faiss.write_index(index, INDEX_PATH)
    doc_dicts = [{"content": doc.page_content, "metadata": doc.metadata} for doc in documents]
    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc_dicts, f, ensure_ascii=False, indent=2)
    print(f"[OK] 构建完成：{index.ntotal} 个文档块 → {INDEX_PATH}")

# ==================== 4-6. 检索 + LLM ====================
query = "RAG如何解决幻觉问题？"
query_emb = embed_texts([query])[0]
scores, indices = index.search(np.array([query_emb], dtype=np.float32), k=3)

print("\n=== 检索结果 ===")
for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
    if idx >= 0:
        print(f"  [{i+1}] 分数: {score:.4f} | {documents[idx].metadata['source']}[块{documents[idx].metadata['chunk']}] | {documents[idx].page_content[:40]}...")

retrieved_docs = [documents[idx] for idx in indices[0] if idx >= 0]
context = "\n".join([doc.page_content for doc in retrieved_docs])

prompt = f"""根据以下已知信息，简洁和专业的来回答问题。
如果无法从中得到答案，请说"根据已知信息无法回答该问题"。

<已知信息>
{context}
</已知信息>

<问题>
{query}
</问题>"""

token = generate_token(API_KEY)
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
data = {"model": "glm-4", "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7, "stream": False}

print("\n=== 调用 LLM 中... ===")
with httpx.Client(timeout=60) as client:
    response = client.post(CHAT_URL, headers=headers, json=data)
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]

print(f"\n=== LLM 回答 ===\n{answer}")
