# 对话记忆模块（MySQL 持久化）
import aiomysql, re, uuid

_pool = None
TITLE_MAX_CHARS = 18


def short_title_from_text(text: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    title = re.sub(r"\s+", " ", text or "").strip()
    title = re.sub(r"^(请|帮我|给我|麻烦|你能不能|能不能|可以帮我|请你)\s*", "", title)
    title = title.strip(' \t\r\n"\'`""，。！？；：、…—·')
    if len(title) <= max_chars:
        return title
    return title[:max_chars].rstrip(' \t\r\n"\'`""，。！？；：、…—·')


async def init_pool(host, port, user, password, database):
    """初始化 MySQL 连接池并建表（服务启动时调用一次）"""
    global _pool
    _pool = await aiomysql.create_pool(
        host=host, port=port, user=user, password=password,
        db=database, charset="utf8mb4", autocommit=True,
        minsize=1, maxsize=5,
    )
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(32) NOT NULL,
                    role            VARCHAR(16) NOT NULL,
                    content         TEXT NOT NULL,
                    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_conv_id (conversation_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id VARCHAR(32) PRIMARY KEY,
                    title           VARCHAR(64) NOT NULL DEFAULT '',
                    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
    print("[MySQL] 连接池就绪")


async def close_pool():
    """关闭连接池（服务关闭时调用）"""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()


async def create_conversation(title: str = "") -> str:
    """创建新对话：优先复用空白对话，否则生成新 ID"""
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT c.conversation_id
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.conversation_id
                WHERE COALESCE(c.title, '') = ''
                GROUP BY c.conversation_id
                HAVING COUNT(m.id) = 0
                ORDER BY MAX(c.updated_at) DESC LIMIT 1
            """)
            row = await cur.fetchone()
            if row:
                return row["conversation_id"]

    conversation_id = new_conversation_id()
    await ensure_conversation(conversation_id, title)
    return conversation_id


async def ensure_conversation(conversation_id: str, title: str = ""):
    """写入或更新时间戳"""
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO conversations (conversation_id, title)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP""",
                (conversation_id, title or "")
            )


async def get_conversation_title(conversation_id: str) -> str:
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT title FROM conversations WHERE conversation_id = %s",
                (conversation_id,)
            )
            row = await cur.fetchone()
            return row["title"] if row and row["title"] else ""


async def set_conversation_title(conversation_id: str, title: str):
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO conversations (conversation_id, title)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE title = VALUES(title), updated_at = CURRENT_TIMESTAMP""",
                (conversation_id, title or "")
            )


async def save_message(conversation_id: str, role: str, content: str):
    """保存一条消息"""
    await ensure_conversation(conversation_id)
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, role, content)
            )


async def get_history(conversation_id: str, limit: int = 10) -> list[dict]:
    """获取指定对话的历史消息"""
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id ASC LIMIT %s",
                (conversation_id, limit)
            )
            rows = await cur.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]


async def list_conversations() -> list[dict]:
    """获取所有对话列表"""
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT
                    c.conversation_id, c.title, c.created_at, c.updated_at,
                    COUNT(m.id) AS message_count,
                    SUBSTRING_INDEX(
                        GROUP_CONCAT(
                            CASE WHEN m.role = 'user' THEN m.content END
                            ORDER BY m.id ASC SEPARATOR '\n'
                        ), '\n', 1
                    ) AS first_user_content
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.conversation_id
                GROUP BY c.conversation_id, c.title, c.created_at, c.updated_at
                ORDER BY c.updated_at DESC
            """)
            rows = await cur.fetchall()
            conversations = []
            has_empty = False
            for r in rows:
                msg_count = r["message_count"]
                if msg_count == 0:
                    if has_empty:
                        continue
                    has_empty = True
                conversations.append({
                    "conversation_id": r["conversation_id"],
                    "title": r["title"] or short_title_from_text(r["first_user_content"]) or "新对话",
                    "message_count": msg_count,
                    "created_at": str(r["created_at"]),
                    "updated_at": str(r["updated_at"]),
                })
            return conversations


async def delete_conversation(conversation_id: str) -> int:
    """删除对话（消息+记录），返回删除的消息数"""
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM messages WHERE conversation_id = %s",
                (conversation_id,)
            )
            deleted = cur.rowcount
            await cur.execute(
                "DELETE FROM conversations WHERE conversation_id = %s",
                (conversation_id,)
            )
            return deleted


def new_conversation_id() -> str:
    """生成新的对话 ID"""
    return uuid.uuid4().hex[:12]
