"""
第7步：配置系统重构
基于 step6，把散落的配置提取到 configs/ 包中：
  - api_config.py : 所有 API Key 和 URL
  - model_config.py : 切分/检索/LLM 参数
  - __init__.py : 统一导出，一行 from configs import * 搞定

改动：不删功能、不改逻辑，只把配置变量移到独立文件。
好处：改参数不用翻主逻辑、Key 和代码分离更安全。
"""
try:
    from steps._bootstrap import DATA_DIR, DOCS_DIR
except ModuleNotFoundError:
    from _bootstrap import DATA_DIR, DOCS_DIR

import httpx, jwt, time, json, os, re, sys
import numpy as np
import faiss
from typing import List, Optional, Any
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

# ★ 配置统一导入（替代原来散落的常量定义）
from configs import (
    ZHIPU_API_KEY, ZHIPU_EMBED_URL, ZHIPU_CHAT_URL,
    BAILIAN_API_KEY, BAILIAN_RERANK_URL,
    CHUNK_SIZE, CHUNK_OVERLAP, ZH_TITLE_ENHANCE,
    EMBEDDING_MODEL, LLM_MODEL, TEMPERATURE,
    SEARCH_TOP_K, RERANK_TOP_N,
)

sys.stdout.reconfigure(encoding="utf-8")

# ==================== 0. 公共工具 ====================
def generate_token(apikey, exp_seconds=60):
    api_id, secret = apikey.split(".")
    payload = {"api_key": api_id, "exp": int(round(time.time()*1000)) + exp_seconds*1000,
               "timestamp": int(round(time.time()*1000))}
    return jwt.encode(payload, secret, algorithm="HS256",
                      headers={"alg": "HS256", "sign_type": "SIGN"})

def embed_texts(texts: List[str]) -> List[List[float]]:
    token = generate_token(ZHIPU_API_KEY)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    embeddings = []
    with httpx.Client(timeout=30) as client:
        for text in texts:
            resp = client.post(ZHIPU_EMBED_URL, headers=headers,
                               json={"model": EMBEDDING_MODEL, "input": text})
            embeddings.append(resp.json()["data"][0]["embedding"])
    return embeddings

# ==================== 1. 路径 ====================
INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
DOCS_PATH = os.path.join(DATA_DIR, "documents.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ==================== 2. 中文切分器（不变） ====================
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

# ==================== 3. 标题增强（不变） ====================
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

# ==================== 5. Reranker（不变） ====================
class Reranker:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.top_n = RERANK_TOP_N

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if len(documents) == 0:
            return []
        doc_texts = [doc.page_content for doc in documents]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gte-rerank",
            "query": query,
            "documents": doc_texts,
            "top_n": self.top_n,
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(BAILIAN_RERANK_URL, headers=headers, json=body)
            resp.raise_for_status()
            result = resp.json()
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
reranker = Reranker(api_key=BAILIAN_API_KEY)
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

token = generate_token(ZHIPU_API_KEY)
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
data = {"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE, "stream": False}

print("\n=== 调用 LLM 中... ===")
with httpx.Client(timeout=60) as client:
    response = client.post(ZHIPU_CHAT_URL, headers=headers, json=data)
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]

print(f"\n=== LLM 回答 ===\n{answer}")
