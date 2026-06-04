import re
import uuid
from datetime import datetime

from sqlalchemy import delete, func, select

from db.models import Conversation, Message
from db.session import get_session_factory

TITLE_MAX_CHARS = 18


def short_title_from_text(text: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    title = re.sub(r"\s+", " ", text or "").strip()
    title = re.sub(r"^(请|帮我|给我|麻烦|你能不能|能不能|可以帮我|请你)\s*", "", title)
    title = title.strip(' \t\r\n"\'`""，。！？；：、…—·')
    if len(title) <= max_chars:
        return title
    return title[:max_chars].rstrip(' \t\r\n"\'`""，。！？；：、…—·')


def new_conversation_id() -> str:
    return uuid.uuid4().hex[:12]


async def create_conversation(title: str = "") -> str:
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(Conversation.conversation_id)
            .outerjoin(Message, Message.conversation_id == Conversation.conversation_id)
            .where(func.coalesce(Conversation.title, "") == "")
            .group_by(Conversation.conversation_id)
            .having(func.count(Message.id) == 0)
            .order_by(func.max(Conversation.updated_at).desc())
            .limit(1)
        )
        row = await session.scalar(stmt)
        if row:
            return row

    conversation_id = new_conversation_id()
    await ensure_conversation(conversation_id, title)
    return conversation_id


async def ensure_conversation(conversation_id: str, title: str = "") -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            session.add(Conversation(conversation_id=conversation_id, title=title or ""))
        else:
            conversation.updated_at = datetime.now()
        await session.commit()


async def get_conversation_title(conversation_id: str) -> str:
    session_factory = get_session_factory()
    async with session_factory() as session:
        title = await session.scalar(
            select(Conversation.title).where(Conversation.conversation_id == conversation_id)
        )
        return title or ""


async def set_conversation_title(conversation_id: str, title: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            conversation = Conversation(conversation_id=conversation_id, title=title or "")
            session.add(conversation)
        else:
            conversation.title = title or ""
            conversation.updated_at = datetime.now()
        await session.commit()


async def save_message(conversation_id: str, role: str, content: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            session.add(Conversation(conversation_id=conversation_id, title=""))
        else:
            conversation.updated_at = datetime.now()
        session.add(Message(conversation_id=conversation_id, role=role, content=content))
        await session.commit()


async def get_history(conversation_id: str, limit: int = 10) -> list[dict]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        rows = list(reversed(result.all()))
        return [{"role": role, "content": content} for role, content in rows]


async def list_conversations() -> list[dict]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc())
        )
        conversations = []
        has_empty = False
        for conversation in result.scalars():
            message_count = await session.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == conversation.conversation_id)
            )
            if message_count == 0:
                if has_empty:
                    continue
                has_empty = True
            first_user_content = await session.scalar(
                select(Message.content)
                .where(Message.conversation_id == conversation.conversation_id, Message.role == "user")
                .order_by(Message.id.asc())
                .limit(1)
            )
            conversations.append({
                "conversation_id": conversation.conversation_id,
                "title": conversation.title or short_title_from_text(first_user_content) or "新对话",
                "message_count": message_count,
                "created_at": str(conversation.created_at),
                "updated_at": str(conversation.updated_at),
            })
        return conversations


async def delete_conversation(conversation_id: str) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        deleted = result.rowcount or 0
        await session.execute(delete(Conversation).where(Conversation.conversation_id == conversation_id))
        await session.commit()
        return deleted
