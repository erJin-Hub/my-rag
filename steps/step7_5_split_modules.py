"""
第7.5步：业务逻辑拆分
基于 step7，把主文件中的业务逻辑拆成独立模块：
  core/
    embedding.py   ← JWT 鉴权 + 智谱 Embedding API
    splitter.py    ← 中文切分器 + 标题增强
    reranker.py    ← 百炼 gte-rerank 重排序
    indexer.py     ← FAISS 构建/加载/检索

效果：主文件从 270 行瘦身到 80 行，只负责"组装流程"。
"""
try:
    from steps._bootstrap import DATA_DIR, DOCS_DIR
except ModuleNotFoundError:
    from _bootstrap import DATA_DIR, DOCS_DIR

import httpx, sys, os

sys.stdout.reconfigure(encoding="utf-8")

# ★ 每个模块各司其职
from configs import ZHIPU_API_KEY, ZHIPU_CHAT_URL, LLM_MODEL, TEMPERATURE, SEARCH_TOP_K
from core.embedding import generate_token
from core.splitter import load_and_split_documents
from core.indexer import build_index, load_index, search
from core.reranker import Reranker

# ==================== 1. 构建/加载索引 ====================
os.makedirs(DATA_DIR, exist_ok=True)

index, documents = build_index(
    documents=load_and_split_documents(DOCS_DIR),
    data_dir=DATA_DIR,
)

# ==================== 2. 两阶段检索（粗排 → 精排） ====================
query = "RAG如何解决幻觉问题？"

# FAISS 粗排
print(f"\n=== FAISS 粗排（捞 top-{SEARCH_TOP_K}） ===")
candidates = search(index, documents, query, top_k=SEARCH_TOP_K)
for i, doc in enumerate(candidates):
    score = doc.metadata.get("faiss_score", "N/A")
    print(
        f"  [{i + 1}] FAISS: {score:.4f} | {doc.metadata['source']}[块{doc.metadata['chunk']}] | {doc.page_content[:50]}...")

# Rerank 精排
from configs import RERANK_TOP_N

print(f"\n=== 百炼 gte-rerank 精排（{len(candidates)} 候选 → top-{RERANK_TOP_N}） ===")
reranker = Reranker()
reranked_docs = reranker.rerank(query, candidates)

print("\n=== 精排后 ===")
for i, doc in enumerate(reranked_docs):
    print(
        f"  [{i + 1}] Rerank: {doc.metadata.get('relevance_score', '?'):.4f} | {doc.metadata['source']}[块{doc.metadata['chunk']}] | {doc.page_content[:60]}...")

# ==================== 3. LLM 回答 ====================
context = "\n".join([doc.page_content for doc in reranked_docs])
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

print("\n=== 调用 LLM 中... ===")
with httpx.Client(timeout=60) as client:
    response = client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]

print(f"\n=== LLM 回答 ===\n{answer}")
