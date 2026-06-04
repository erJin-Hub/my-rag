from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base

_engine = None
_session_factory = None


def build_mysql_url(host, port, user, password, database) -> str:
    return f"mysql+aiomysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


async def init_database(host, port, user, password, database) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(
        build_mysql_url(host, port, user, password, database),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[MySQL] SQLAlchemy AsyncSession 就绪")


async def close_database() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory():
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_database()")
    return _session_factory
