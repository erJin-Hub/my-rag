"""
第1步：最简单的 RAG — 内存文档 + FAISS 检索 + LLM 回答
Embedding 使用智谱 embedding-2 API（无需本地模型）
"""
try:
    from steps._bootstrap import DATA_DIR, DOCS_DIR
except ModuleNotFoundError:
    from _bootstrap import DATA_DIR, DOCS_DIR

import httpx
import jwt
import time
import numpy as np
from typing import List
from langchain_core.documents import Document

# ==================== 0. 智谱 API 公共配置 ====================
API_KEY = "f319167f721645fe91aa4918d321b521.bPLyCmwCzSOr1Ttb"
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


# 智谱要求 JWT 鉴权：把 API Key 的 ID 部分 + 时间戳加密成一个临时 token，有效期 60 秒。
def generate_token(apikey: str, exp_seconds: int = 60):
    api_id, secret = apikey.split(".")
    payload = {
        "api_key": api_id,
        "exp": int(round(time.time() * 1000)) + exp_seconds * 1000,
        "timestamp": int(round(time.time() * 1000)),
    }
    return jwt.encode(payload, secret, algorithm="HS256",
                      headers={"alg": "HS256", "sign_type": "SIGN"})


# ==================== 1. 在线 Embedding（替代本地模型） ====================
def embed_texts(texts: List[str]) -> List[List[float]]:
    """调用智谱 embedding-2 API，把文本列表转成向量列表"""
    token = generate_token(API_KEY)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    embeddings = []
    with httpx.Client(timeout=30) as client:
        for text in texts:
            resp = client.post(EMBED_URL, headers=headers,
                               json={"model": "embedding-2", "input": text})
            embeddings.append(resp.json()["data"][0]["embedding"])
    return embeddings


print("[OK] Embedding API 就绪（智谱 embedding-2）")

# ==================== 2. 准备文档 ====================
documents = [
    Document(page_content="RAG（检索增强生成）是一种结合信息检索与文本生成的技术。"),
    Document(page_content="RAG 的核心流程是：先检索相关文档，再将文档作为上下文输入 LLM 生成答案。"),
    Document(page_content="LangChain 是构建 RAG 应用最流行的框架，提供了完整的工具链。"),
    Document(page_content="FAISS 是 Meta 开源的高性能向量相似度搜索库，常用于 RAG 的检索环节。"),
    Document(page_content="Embedding 模型将文本转换为向量，BGE 系列是中文效果最好的开源 Embedding 模型之一。"),
]
print(f"[OK] 准备 {len(documents)} 篇文档")

# ==================== 3. 构建 FAISS 向量库 ====================
import faiss

# 对每篇文档生成 embedding
texts = [doc.page_content for doc in documents]
embeddings = embed_texts(texts)
dim = len(embeddings[0])  # 获取维度

# 创建 FAISS 索引（内积相似度）
index = faiss.IndexFlatIP(dim)
index.add(np.array(embeddings, dtype=np.float32))
print(f"[OK] FAISS 向量库构建完成，维度={dim}，文档数={index.ntotal}")

# ==================== 4. 检索 ====================
query = "什么是RAG？"
query_emb = embed_texts([query])[0]

# 搜索 top 3
scores, indices = index.search(np.array([query_emb], dtype=np.float32), k=3)

print("\n=== 检索结果 ===")
for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
    if idx >= 0:
        print(f"  [{i + 1}] 分数: {score:.4f} | 内容: {documents[idx].page_content[:50]}...")

# ==================== 5. 拼 Prompt ====================
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

# ==================== 6. 调用 LLM ====================
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
