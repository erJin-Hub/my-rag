from fastapi import HTTPException

from repositories.memory_repository import create_memory, disable_memory, list_memories, update_memory


async def add_long_term_memory(
    content: str,
    category: str = "general",
    importance: int = 3,
    source_conversation_id: str = "",
) -> dict:
    try:
        return await create_memory(content, category, importance, source_conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def get_long_term_memories(
    include_disabled: bool = False,
    limit: int = 20,
    category: str = "",
) -> dict:
    return {"items": await list_memories(
        include_disabled=include_disabled,
        limit=limit,
        category=category,
    )}


async def update_long_term_memory(
    memory_id: int,
    content: str | None = None,
    category: str | None = None,
    importance: int | None = None,
    enabled: bool | None = None,
) -> dict:
    try:
        memory = await update_memory(memory_id, content, category, importance, enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="长期记忆不存在")
    return memory


async def remove_long_term_memory(memory_id: int) -> dict:
    disabled = await disable_memory(memory_id)
    if not disabled:
        raise HTTPException(status_code=404, detail="长期记忆不存在")
    return {"id": memory_id, "enabled": False}
