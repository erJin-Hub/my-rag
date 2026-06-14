from fastapi import APIRouter, Query

from schemas.chat import MemoryCreateRequest, MemoryResponse, MemoryUpdateRequest
from services.memory_service import (
    add_long_term_memory,
    get_long_term_memories,
    rebuild_long_term_memory_vectors,
    remove_long_term_memory,
    update_long_term_memory,
)

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.post("", response_model=MemoryResponse)
async def create_memory(request: MemoryCreateRequest):
    return MemoryResponse(**await add_long_term_memory(
        content=request.content,
        category=request.category,
        importance=request.importance,
        source_conversation_id=request.source_conversation_id,
    ))


@router.get("")
async def memories(
    include_disabled: bool = Query(
        False,
        description="是否包含已禁用的长期记忆。默认 False，只返回聊天时会使用的记忆。",
    ),
    category: str = Query(
        "",
        description="按长期记忆类型筛选。为空表示不过滤，例如 preference、profile、project、goal、fact、general。",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="最多返回多少条长期记忆。默认 20，最大 100。",
    ),
):
    return await get_long_term_memories(
        include_disabled=include_disabled,
        limit=limit,
        category=category,
    )


@router.post("/vector-sync")
async def sync_memory_vectors():
    return await rebuild_long_term_memory_vectors()


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(memory_id: int, request: MemoryUpdateRequest):
    return MemoryResponse(**await update_long_term_memory(
        memory_id=memory_id,
        content=request.content,
        category=request.category,
        importance=request.importance,
        enabled=request.enabled,
    ))


@router.delete("/{memory_id}")
async def delete_memory(memory_id: int):
    return await remove_long_term_memory(memory_id)
