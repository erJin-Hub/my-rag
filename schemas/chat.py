from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str


class MemoryChatRequest(BaseModel):
    query: str
    conversation_id: str = ""
    history_len: int = 10


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    conversation_id: str = ""
    title: str = ""


class NewConvResponse(BaseModel):
    conversation_id: str
    title: str = ""


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    total_chunks: int


class MemoryCreateRequest(BaseModel):
    content: str
    category: str = "general"
    importance: int = 3
    source_conversation_id: str = ""


class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    importance: int
    source_conversation_id: str = ""
    enabled: bool
    created_at: str
    updated_at: str
