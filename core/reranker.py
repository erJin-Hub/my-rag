# Reranker 重排序模块（阿里云百炼 gte-rerank 在线 API）
import httpx
from typing import List
from langchain_core.documents import Document
from configs import BAILIAN_API_KEY, BAILIAN_RERANK_URL, RERANK_TOP_N


class Reranker:
    """基于百炼 gte-rerank 的在线重排序器，只需 API Key，零本地依赖"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or BAILIAN_API_KEY
        self.top_n = RERANK_TOP_N

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        if len(documents) == 0:
            return []
        clean_documents = [
            doc for doc in documents
            if (doc.page_content or "").strip()
        ]
        if len(clean_documents) == 0:
            return []

        doc_texts = [doc.page_content.strip() for doc in clean_documents]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "qwen3-rerank",
            "query": query,
            "documents": doc_texts,
            "top_n": min(self.top_n, len(clean_documents)),
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(BAILIAN_RERANK_URL, headers=headers, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                print("[Reranker] 百炼返回错误状态：", resp.status_code)
                print("[Reranker] 百炼返回错误内容：", resp.text)
                print("[Reranker] query长度：", len(query or ""))
                print("[Reranker] documents数量：", len(doc_texts))
                print("[Reranker] documents长度：", [len(text) for text in doc_texts])
                raise
            result = resp.json()
        reranked = []
        for item in result["results"]:
            doc = clean_documents[item["index"]]
            doc.metadata["relevance_score"] = item["relevance_score"]
            reranked.append(doc)
        return reranked
