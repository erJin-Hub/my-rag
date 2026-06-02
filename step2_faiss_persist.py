"""
第2步：FAISS 持久化 — 索引和文档存磁盘，重启不丢失
"""
import httpx, jwt, time, json, os
import numpy as np
import faiss
from typing import List
from langchain_core.documents import Document

# ==================== 0. API 配置 ====================
API_KEY = "f319167f721645fe91aa4918d321b521.bPLyCmwCzSOr1Ttb"
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"

def generate_token(apikey: str, exp_seconds: int = 60):
    api_id, secret = apikey.split(".")
    payload = {
        "api_key": api_id, "exp": int(round(time.time()*1000)) + exp_seconds*1000,
        "timestamp": int(round(time.time()*1000)),
    }
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

# ==================== 1. 持久化路径 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
DOCS_PATH = os.path.join(DATA_DIR, "documents.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 2. 加载或构建 ====================
if os.path.exists(INDEX_PATH) and os.path.exists(DOCS_PATH):
    # ---- 磁盘上有，直接加载 ----
    print("[OK] 检测到已有索引，从磁盘加载...")
    index = faiss.read_index(INDEX_PATH)
    with open(DOCS_PATH, "r", encoding="utf-8") as f:
        doc_dicts = json.load(f)
    documents = [Document(page_content=d["content"], metadata=d.get("metadata", {}))
                 for d in doc_dicts]
    print(f"[OK] 加载完成：{index.ntotal} 个文档")
else:
    # ---- 磁盘上没有，新建 ----
    print("[INFO] 未找到索引，从头构建...")
    documents = [
        Document(page_content="RAG（检索增强生成）是一种结合信息检索与文本生成的技术。"),
        Document(page_content="RAG 的核心流程是：先检索相关文档，再将文档作为上下文输入 LLM 生成答案。"),
        Document(page_content="LangChain 是构建 RAG 应用最流行的框架，提供了完整的工具链。"),
        Document(page_content="FAISS 是 Meta 开源的高性能向量相似度搜索库，常用于 RAG 的检索环节。"),
        Document(page_content="Embedding 模型将文本转换为向量，BGE 系列是中文效果最好的开源 Embedding 模型之一。"),
    ]

    texts = [doc.page_content for doc in documents]
    embeddings = embed_texts(texts)

    index = faiss.IndexFlatIP(len(embeddings[0]))
    index.add(np.array(embeddings, dtype=np.float32))

    # 存 FAISS 索引
    faiss.write_index(index, INDEX_PATH)
    # 存文档正文
    doc_dicts = [{"content": doc.page_content, "metadata": doc.metadata} for doc in documents]
    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc_dicts, f, ensure_ascii=False, indent=2)

    print(f"[OK] 构建完成并已保存：{index.ntotal} 个文档 → {INDEX_PATH}")

# ==================== 3-6. 检索 + 回答（和 step1 一样） ====================
CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

query = "什么是RAG？"
query_emb = embed_texts([query])[0]
scores, indices = index.search(np.array([query_emb], dtype=np.float32), k=3)

print("\n=== 检索结果 ===")
for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
    if idx >= 0:
        print(f"  [{i+1}] 分数: {score:.4f} | 内容: {documents[idx].page_content[:50]}...")

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
