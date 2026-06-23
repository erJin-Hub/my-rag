from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from schemas.chat import ChatRequest, ChatResponse, MemoryChatRequest
from services.chat_service import chat_once, chat_with_memory, stream_chat_with_memory

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(request: Request, body: ChatRequest):
    return ChatResponse(**chat_once(request.app, body.query))


@router.post("/memory", response_model=ChatResponse)
async def chat_memory(request: Request, body: MemoryChatRequest):
    result = await chat_with_memory(
        request.app,
        body.query,
        body.conversation_id,
        body.history_len,
        body.enable_web_search,
    )
    return ChatResponse(**result)


@router.post("/memory/stream")
async def chat_memory_stream(request: Request, body: MemoryChatRequest):
    return EventSourceResponse(
        stream_chat_with_memory(
            request.app,
            body.query,
            body.conversation_id,
            body.history_len,
            body.enable_web_search,
        )
    )
