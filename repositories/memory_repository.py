import asyncio
from datetime import datetime

from sqlalchemy import select

from core.memory_vector_store import delete_memory_vector, sync_memory_vectors, upsert_memory_vector
from db.models import Memory
from db.session import get_session_factory

DEFAULT_MEMORY_LIMIT = 20


def normalize_memory_content(content: str) -> str:
    return " ".join((content or "").split())


def format_datetime(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d %H:%M:%S")


async def sync_memory_vector(memory: dict) -> None:
    try:
        if memory.get("enabled"):
            await asyncio.to_thread(upsert_memory_vector, memory)
        else:
            await asyncio.to_thread(delete_memory_vector, int(memory["id"]))
    except Exception as exc:
        print(f"[Milvus] 同步长期记忆向量失败 memory_id={memory.get('id')}: {exc}")


async def create_memory(
    content: str,
    category: str = "general",
    importance: int = 3,
    source_conversation_id: str = "",
) -> dict:
    content = normalize_memory_content(content)
    if not content:
        raise ValueError("长期记忆内容不能为空")

    importance = max(1, min(int(importance or 3), 5))
    session_factory = get_session_factory()
    async with session_factory() as session:
        memory = Memory(
            content=content,
            category=(category or "general").strip() or "general",
            importance=importance,
            source_conversation_id=(source_conversation_id or "").strip(),
            enabled=True,
        )
        session.add(memory)
        await session.commit()
        await session.refresh(memory)
        result = memory_to_dict(memory)
    await sync_memory_vector(result)
    return result


async def memory_content_exists(content: str) -> bool:
    content = normalize_memory_content(content)
    if not content:
        return False

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Memory.id).where(
            Memory.enabled.is_(True),
            Memory.content == content,
        ).limit(1)
        return await session.scalar(stmt) is not None


async def list_memories(
    include_disabled: bool = False,
    limit: int = DEFAULT_MEMORY_LIMIT,
    category: str = "",
) -> list[dict]:
    limit = max(1, min(int(limit or DEFAULT_MEMORY_LIMIT), 100))
    category = (category or "").strip()
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Memory)
        if not include_disabled:
            stmt = stmt.where(Memory.enabled.is_(True))
        if category:
            stmt = stmt.where(Memory.category == category)
        stmt = stmt.order_by(Memory.importance.desc(), Memory.updated_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return [memory_to_dict(memory) for memory in result.scalars()]


async def list_memories_by_ids(memory_ids: list[int]) -> list[dict]:
    if not memory_ids:
        return []

    order = {memory_id: index for index, memory_id in enumerate(memory_ids)}
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Memory).where(
            Memory.enabled.is_(True),
            Memory.id.in_(memory_ids),
        )
        result = await session.execute(stmt)
        memories = [memory_to_dict(memory) for memory in result.scalars()]
    return sorted(memories, key=lambda memory: order.get(memory["id"], len(order)))


async def sync_enabled_memory_vectors(limit: int = 100) -> tuple[int, int]:
    memories = await list_memories(include_disabled=False, limit=limit)
    return await asyncio.to_thread(sync_memory_vectors, memories)


async def update_memory(
    memory_id: int,
    content: str | None = None,
    category: str | None = None,
    importance: int | None = None,
    enabled: bool | None = None,
) -> dict | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        memory = await session.get(Memory, memory_id)
        if memory is None:
            return None

        if content is not None:
            content = normalize_memory_content(content)
            if not content:
                raise ValueError("长期记忆内容不能为空")
            memory.content = content
        if category is not None:
            memory.category = category.strip() or "general"
        if importance is not None:
            memory.importance = max(1, min(int(importance or 3), 5))
        if enabled is not None:
            memory.enabled = enabled

        memory.updated_at = datetime.now()
        await session.commit()
        await session.refresh(memory)
        result = memory_to_dict(memory)
    await sync_memory_vector(result)
    return result


async def get_enabled_memory_text(limit: int = DEFAULT_MEMORY_LIMIT) -> str:
    memories = await list_memories(include_disabled=False, limit=limit)
    if not memories:
        return ""
    lines = []
    for memory in memories:
        lines.append(f"- [{memory['category']}|重要度{memory['importance']}] {memory['content']}")
    return "\n".join(lines)


def format_memories_text(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = []
    for memory in memories:
        lines.append(f"- [{memory['category']}|重要度{memory['importance']}] {memory['content']}")
    return "\n".join(lines)


async def disable_memory(memory_id: int) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        memory = await session.get(Memory, memory_id)
        if memory is None:
            return False
        memory.enabled = False
        memory.updated_at = datetime.now()
        await session.commit()
    try:
        await asyncio.to_thread(delete_memory_vector, int(memory_id))
    except Exception as exc:
        print(f"[Milvus] 删除长期记忆向量失败 memory_id={memory_id}: {exc}")
    return True


def memory_to_dict(memory: Memory) -> dict:
    return {
        "id": memory.id,
        "content": memory.content,
        "category": memory.category,
        "importance": memory.importance,
        "source_conversation_id": memory.source_conversation_id,
        "enabled": memory.enabled,
        "created_at": format_datetime(memory.created_at),
        "updated_at": format_datetime(memory.updated_at),
    }
