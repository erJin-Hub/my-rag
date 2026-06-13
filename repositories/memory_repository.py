from datetime import datetime

from sqlalchemy import select

from db.models import Memory
from db.session import get_session_factory

DEFAULT_MEMORY_LIMIT = 20


def normalize_memory_content(content: str) -> str:
    return " ".join((content or "").split())


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
        return memory_to_dict(memory)


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
        return memory_to_dict(memory)


async def get_enabled_memory_text(limit: int = DEFAULT_MEMORY_LIMIT) -> str:
    memories = await list_memories(include_disabled=False, limit=limit)
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
        return True


def memory_to_dict(memory: Memory) -> dict:
    return {
        "id": memory.id,
        "content": memory.content,
        "category": memory.category,
        "importance": memory.importance,
        "source_conversation_id": memory.source_conversation_id,
        "enabled": memory.enabled,
        "created_at": str(memory.created_at),
        "updated_at": str(memory.updated_at),
    }
