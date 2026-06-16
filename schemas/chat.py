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
    used_memories: list[dict] = []


class NewConvResponse(BaseModel):
    conversation_id: str
    title: str = ""


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    total_chunks: int


class MemoryCreateRequest(BaseModel):
    # 记住什么
    content: str
    # 这是什么类型的记忆
    category: str = "general"
    # 有多重要
    importance: int = 3
    # 这条记忆从哪个会话来的
    source_conversation_id: str = ""


class MemoryUpdateRequest(BaseModel):
    # 新的记忆内容；不传表示不修改
    content: str | None = None
    # 新的记忆类型；不传表示不修改
    category: str | None = None
    # 新的重要程度；不传表示不修改
    importance: int | None = None
    # 是否启用这条记忆；不传表示不修改
    enabled: bool | None = None


class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    importance: int
    source_conversation_id: str = ""
    enabled: bool
    created_at: str
    updated_at: str
