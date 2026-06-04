from db.session import close_database, init_database
from repositories.conversation_repository import (
    create_conversation,
    delete_conversation,
    ensure_conversation,
    get_conversation_title,
    get_history,
    list_conversations,
    new_conversation_id,
    save_message,
    set_conversation_title,
    short_title_from_text,
)


async def init_pool(host, port, user, password, database):
    """兼容旧调用名：初始化 SQLAlchemy 异步数据库连接并建表。"""
    await init_database(host, port, user, password, database)


async def close_pool():
    """兼容旧调用名：关闭 SQLAlchemy 异步数据库连接。"""
    await close_database()
