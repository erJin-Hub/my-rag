from functools import lru_cache
from typing import Iterable

from pymilvus import MilvusClient

from configs import EMBEDDING_DIM, MILVUS_MEMORY_COLLECTION, MILVUS_URI, MEMORY_VECTOR_TOP_K
from core.embedding import embed_texts

VECTOR_FIELD = "vector"


@lru_cache(maxsize=1)
def get_milvus_client() -> MilvusClient:
    return MilvusClient(uri=MILVUS_URI)


def ensure_memory_collection() -> None:
    client = get_milvus_client()
    if client.has_collection(MILVUS_MEMORY_COLLECTION):
        return
    client.create_collection(
        collection_name=MILVUS_MEMORY_COLLECTION,
        dimension=EMBEDDING_DIM,
        primary_field_name="memory_id",
        id_type="int",
        vector_field_name=VECTOR_FIELD,
        metric_type="COSINE",
        auto_id=False,
    )
    client.load_collection(MILVUS_MEMORY_COLLECTION)
    print(f"[Milvus] 创建长期记忆 collection: {MILVUS_MEMORY_COLLECTION}")


def embed_one(text: str) -> list[float]:
    vectors = embed_texts([text])
    if not vectors:
        raise ValueError("embedding 结果为空")
    vector = vectors[0]
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"embedding 维度不匹配：期望 {EMBEDDING_DIM}，实际 {len(vector)}")
    return vector


def upsert_memory_vector(memory: dict) -> None:
    ensure_memory_collection()
    content = memory.get("content") or ""
    if not content:
        return
    vector = embed_one(content)
    get_milvus_client().upsert(
        collection_name=MILVUS_MEMORY_COLLECTION,
        data=[{
            "memory_id": int(memory["id"]),
            VECTOR_FIELD: vector,
        }],
    )
    get_milvus_client().flush(MILVUS_MEMORY_COLLECTION)
    get_milvus_client().load_collection(MILVUS_MEMORY_COLLECTION)


def delete_memory_vector(memory_id: int) -> None:
    if not get_milvus_client().has_collection(MILVUS_MEMORY_COLLECTION):
        return
    get_milvus_client().delete(
        collection_name=MILVUS_MEMORY_COLLECTION,
        ids=[int(memory_id)],
    )


def search_memory_ids(query: str, limit: int = MEMORY_VECTOR_TOP_K) -> list[int]:
    query = (query or "").strip()
    if not query:
        return []
    query_vector = embed_one(query)
    return search_memory_ids_by_vector(query_vector, limit)


def search_memory_ids_by_vector(query_vector: list[float], limit: int = MEMORY_VECTOR_TOP_K) -> list[int]:
    return [item["memory_id"] for item in search_memory_hits_by_vector(query_vector, limit)]


def search_memory_hits_by_vector(query_vector: list[float], limit: int = MEMORY_VECTOR_TOP_K) -> list[dict]:
    ensure_memory_collection()
    results = get_milvus_client().search(
        collection_name=MILVUS_MEMORY_COLLECTION,
        data=[query_vector],
        limit=max(1, int(limit or MEMORY_VECTOR_TOP_K)),
        output_fields=["memory_id"],
    )
    if not results:
        return []
    hits = []
    for hit in results[0]:
        memory_id = hit.get("id") or hit.get("memory_id")
        entity = hit.get("entity") or {}
        memory_id = entity.get("memory_id", memory_id)
        if memory_id is not None:
            hits.append({
                "memory_id": int(memory_id),
                "score": float(hit.get("distance", 0)),
            })
    return hits


def sync_memory_vectors(memories: Iterable[dict]) -> tuple[int, int]:
    synced = 0
    failed = 0
    for memory in memories:
        try:
            upsert_memory_vector(memory)
            synced += 1
        except Exception as exc:
            failed += 1
            print(f"[Milvus] 同步长期记忆向量失败 memory_id={memory.get('id')}: {exc}")
    return synced, failed
