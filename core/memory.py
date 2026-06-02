# 对话记忆模块（MySQL 持久化）
import aiomysql, uuid
from datetime import datetime

_pool = None  # 模块级连接池，由外部初始化


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
    print("[MySQL] 连接池就绪")


async def close_pool():
    """关闭连接池（服务关闭时调用）"""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()


async def save_message(conversation_id: str, role: str, content: str):
    """保存一条消息"""
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


def new_conversation_id() -> str:
    """生成新的对话 ID"""
    return uuid.uuid4().hex[:12]
