from fastapi import APIRouter

from schemas.chat import NewConvResponse
from services.conversation_service import (
    create_new_conversation,
    get_all_conversations,
    get_conversation_history,
    remove_conversation_by_id,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("/new", response_model=NewConvResponse)
async def new_conversation():
    return NewConvResponse(**await create_new_conversation())


@router.get("")
async def conversations():
    return await get_all_conversations()


@router.get("/{conversation_id}/history")
async def conversation_history(conversation_id: str):
    return await get_conversation_history(conversation_id)


@router.delete("/{conversation_id}")
async def remove_conversation(conversation_id: str):
    return await remove_conversation_by_id(conversation_id)
