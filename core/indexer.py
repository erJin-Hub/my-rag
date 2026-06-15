# FAISS 索引管理模块
# 负责：构建索引、持久化、加载、检索
import os, json
import numpy as np
import faiss
from typing import List, Tuple
from langchain_core.documents import Document
from core.embedding import embed_texts

INDEX_FILE = "faiss.index"
DOCS_FILE = "documents.json"


def build_index(documents: List[Document], data_dir: str, force: bool = False):
    """
    构建 FAISS 索引并持久化。
    如果索引已存在且 force=False，直接加载。
    返回 (index, documents)
    """
    index_path = os.path.join(data_dir, INDEX_FILE)
    docs_path = os.path.join(data_dir, DOCS_FILE)

    if not force and os.path.exists(index_path) and os.path.exists(docs_path):
        return load_index(data_dir)

    print(f"[INFO] 构建索引中...")
    texts = [doc.page_content for doc in documents]
    embeddings = embed_texts(texts)

    index = faiss.IndexFlatIP(len(embeddings[0]))
    index.add(np.array(embeddings, dtype=np.float32))

    faiss.write_index(index, index_path)
    doc_dicts = [{"content": doc.page_content, "metadata": doc.metadata} for doc in documents]
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump(doc_dicts, f, ensure_ascii=False, indent=2)

    print(f"[OK] 索引构建完成：{index.ntotal} 个文档块 → {index_path}")
    return index, documents


def load_index(data_dir: str) -> Tuple[faiss.Index, List[Document]]:
    """从磁盘加载已持久化的 FAISS 索引和文档"""
    index_path = os.path.join(data_dir, INDEX_FILE)
    docs_path = os.path.join(data_dir, DOCS_FILE)

    index = faiss.read_index(index_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        doc_dicts = json.load(f)
    documents = [Document(page_content=d["content"], metadata=d.get("metadata", {}))
                 for d in doc_dicts]
    print(f"[OK] 从磁盘加载索引：{index.ntotal} 个文档块")
    return index, documents


def search(index: faiss.Index, documents: List[Document],
           query: str, top_k: int) -> List[Document]:
    """
    检索：将 query 转 embedding，FAISS 搜索 top_k 个最相似文档块。
    返回排序后的 Document 列表。
    """
    query_emb = embed_texts([query])[0]
    return search_by_vector(index, documents, query_emb, top_k)


def search_by_vector(index: faiss.Index, documents: List[Document],
                     query_vector: List[float], top_k: int) -> List[Document]:
    """使用已生成的 query 向量检索 FAISS，避免重复调用 embedding。"""
    scores, indices = index.search(np.array([query_vector], dtype=np.float32), k=top_k)
    results = []
    for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
        if idx >= 0:
            doc = documents[idx]
            doc.metadata["faiss_score"] = float(score)
            results.append(doc)
    return results
