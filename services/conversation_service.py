from core.memory import (
    create_conversation,
    delete_conversation,
    get_conversation_title,
    get_history,
    list_conversations,
)


async def create_new_conversation() -> dict:
    conversation_id = await create_conversation()
    title = await get_conversation_title(conversation_id)
    return {"conversation_id": conversation_id, "title": title}


async def get_all_conversations() -> dict:
    return {"items": await list_conversations()}


async def get_conversation_history(conversation_id: str) -> dict:
    history = await get_history(conversation_id)
    title = await get_conversation_title(conversation_id)
    return {"conversation_id": conversation_id, "title": title, "messages": history}


async def remove_conversation_by_id(conversation_id: str) -> dict:
    deleted = await delete_conversation(conversation_id)
    return {"conversation_id": conversation_id, "deleted_messages": deleted}
