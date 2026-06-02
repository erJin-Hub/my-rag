"""
第6步：Reranker 重排序（阿里云百炼 gte-rerank 在线 API）
基于 step5，在 FAISS 粗排之后加入在线 Rerank API 精排：
  - FAISS 先捞 top-10 候选（粗排，速度快）
  - 百炼 gte-rerank API 对候选逐一精排打分（细排，准确度高）
  - 最终取 top-3 喂给 LLM

零额外依赖：百炼 API 只需 httpx，已安装。
"""
import httpx, jwt, time, json, os, re, sys
import numpy as np
import faiss
from typing import List, Optional, Any
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ==================== 0. API 配置 ====================
# 智谱（Embedding + LLM）
API_KEY = "f319167f721645fe91aa4918d321b521.bPLyCmwCzSOr1Ttb"
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

# 阿里云百炼（Rerank）
RERANK_URL = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
RERANK_API_KEY = "sk-2c906e393780490cac2a76b843e6aa4d"    # ← 替换成你的

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

# ==================== 2. 切分器（同 step5） ====================
def _split_text_with_regex_from_end(text: str, separator: str, keep_separator: bool) -> List[str]:
    if separator:
        if keep_separator:
            _splits = re.split(f"({separator})", text)
            splits = ["".join(i) for i in zip(_splits[0::2], _splits[1::2])]
            if len(_splits) % 2 == 1:
                splits += _splits[-1:]
        else:
            splits = re.split(separator, text)
    else:
        splits = list(text)
    return [s for s in splits if s != ""]

class ChineseRecursiveTextSplitter(RecursiveCharacterTextSplitter):
    def __init__(self, separators=None, keep_separator=True, is_separator_regex=True, **kwargs):
        super().__init__(keep_separator=keep_separator, **kwargs)
        self._separators = separators or [
            r"\n\n", r"\n", r"。|！|？", r"\.\s|\!\s|\?\s", r"；|;\s", r"，|,\s"
        ]
        self._is_separator_regex = is_separator_regex

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks = []
        separator = separators[-1]
        new_separators = []
        for i, _s in enumerate(separators):
            _separator = _s if self._is_separator_regex else re.escape(_s)
            if _s == "":
                separator = _s
                break
            if re.search(_separator, text):
                separator = _s
                new_separators = separators[i + 1:]
                break
        _separator = separator if self._is_separator_regex else re.escape(separator)
        splits = _split_text_with_regex_from_end(text, _separator, self._keep_separator)
        _good_splits = []
        _separator = "" if self._keep_separator else separator
        for s in splits:
            if self._length_function(s) < self._chunk_size:
                _good_splits.append(s)
            else:
                if _good_splits:
                    merged_text = self._merge_splits(_good_splits, _separator)
                    final_chunks.extend(merged_text)
                    _good_splits = []
                if not new_separators:
                    final_chunks.append(s)
                else:
                    other_info = self._split_text(s, new_separators)
                    final_chunks.extend(other_info)
        if _good_splits:
            merged_text = self._merge_splits(_good_splits, _separator)
            final_chunks.extend(merged_text)
        return [re.sub(r"\n{2,}", "\n", chunk.strip()) for chunk in final_chunks if chunk.strip()!=""]

# ==================== 3. 标题增强（同 step5） ====================
def under_non_alpha_ratio(text: str, threshold: float = 0.5) -> bool:
    if len(text) == 0:
        return False
    alpha_count = len([char for char in text if char.strip() and char.isalpha()])
    total_count = len([char for char in text if char.strip()])
    try:
        return (alpha_count / total_count) < threshold
    except:
        return False

def is_possible_title(text: str, title_max_word_length: int = 20, non_alpha_threshold: float = 0.5) -> bool:
    if len(text) == 0:
        return False
    if re.search(r"[^\w\s]\Z", text):
        return False
    if len(text) > title_max_word_length:
        return False
    if under_non_alpha_ratio(text, threshold=non_alpha_threshold):
        return False
    if text.endswith((",", ".", "\uff0c", "\u3002")):
        return False
    if text.isnumeric():
        return False
    text_5 = text[:5] if len(text) >= 5 else text
    if not any(c.isnumeric() for c in text_5):
        return False
    return True

def zh_title_enhance(docs: List[Document]) -> List[Document]:
    title = None
    if len(docs) > 0:
        for doc in docs:
            if is_possible_title(doc.page_content):
                doc.metadata['category'] = 'cn_Title'
                title = doc.page_content
            elif title:
                doc.page_content = f"下文与({title})有关。{doc.page_content}"
        return docs
    else:
        print("文档为空")
        return docs

CHUNK_SIZE = 250
CHUNK_OVERLAP = 50
ZH_TITLE_ENHANCE = True

def load_and_split_documents(folder: str) -> List[Document]:
    text_splitter = ChineseRecursiveTextSplitter(
        keep_separator=True, is_separator_regex=True,
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
    )
    all_chunks = []
    for file_path in Path(folder).iterdir():
        if file_path.is_file() and file_path.suffix in {".txt", ".md"}:
            content = file_path.read_text(encoding="utf-8-sig")
            doc = Document(page_content=content, metadata={"source": file_path.name})
            chunks = text_splitter.split_documents([doc])
            if ZH_TITLE_ENHANCE:
                chunks = zh_title_enhance(chunks)
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk"] = i
                chunk.metadata["source"] = file_path.name
            all_chunks.extend(chunks)
            print(f"  [LOAD] {file_path.name} ({len(content)} 字) → 切成 {len(chunks)} 块")
    return all_chunks

# ==================== 4. 加载或构建索引 ====================
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

# ==================== ★ 5. Reranker 重排序（step6 核心，百炼在线 API） ★ ====================
# 两阶段检索：
#   [粗排] FAISS 向量相似度 → 捞 top-10 候选（快，但只看 embedding 距离）
#   [精排] 百炼 gte-rerank → 对候选重新打分排序（准，模型同时看到 query 和文档全文）
#
# gte-rerank 流程：
#   发一个 POST，body 里带上 query + documents 数组
#   返回按相关性排好序的结果，每个带有 relevance_score

SEARCH_TOP_K = 10   # FAISS 粗排捞多少
RERANK_TOP_N = 3    # 精排保留多少

class Reranker:
    """
    基于阿里云百炼 gte-rerank 的在线重排序器。
    只需 API Key，无需安装任何模型文件。
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.top_n = RERANK_TOP_N

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if len(documents) == 0:
            return []

        # ① 提取文档正文
        doc_texts = [doc.page_content for doc in documents]

        # ② 调用百炼 Rerank API
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "qwen3-rerank",
            "query": query,
            "documents": doc_texts,
            "top_n": self.top_n,
        }

        with httpx.Client(timeout=30) as client:
            resp = client.post(RERANK_URL, headers=headers, json=body)
            resp.raise_for_status()
            result = resp.json()

        # ③ 解析结果，按新顺序返回
        # 百炼返回格式：{"results": [{"index": 2, "relevance_score": 0.98}, ...]}
        reranked = []
        for item in result["results"]:
            doc = documents[item["index"]]
            doc.metadata["relevance_score"] = item["relevance_score"]
            reranked.append(doc)
        return reranked

# ==================== 6. 两阶段检索 + LLM ====================
query = "RAG如何解决幻觉问题？"
query_emb = embed_texts([query])[0]

# --- 阶段1：FAISS 粗排 ---
print(f"\n=== 阶段1：FAISS 粗排（捞 top-{SEARCH_TOP_K}） ===")
scores, indices = index.search(np.array([query_emb], dtype=np.float32), k=SEARCH_TOP_K)

candidates = []
for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
    if idx >= 0:
        candidates.append(documents[idx])
        print(f"  [{i+1}] FAISS: {score:.4f} | {documents[idx].metadata['source']}[块{documents[idx].metadata['chunk']}] | {documents[idx].page_content[:50]}...")

# --- 阶段2：百炼 Rerank 精排 ---
print(f"\n=== 阶段2：百炼 gte-rerank 精排（{len(candidates)} 个候选 → top-{RERANK_TOP_N}） ===")
reranker = Reranker(api_key=RERANK_API_KEY)
reranked_docs = reranker.rerank(query, candidates)

print("\n=== 精排后结果 ===")
for i, doc in enumerate(reranked_docs):
    score = doc.metadata.get("relevance_score", "N/A")
    print(f"  [{i+1}] Rerank: {score:.4f} | {doc.metadata['source']}[块{doc.metadata['chunk']}] | {doc.page_content[:60]}...")

# --- 阶段3：LLM 回答 ---
context = "\n".join([doc.page_content for doc in reranked_docs])

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
