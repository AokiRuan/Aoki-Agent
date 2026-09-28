"""SessionStore 的 Postgres 实现（Day 4）。

注意：App Runner 的文件系统是临时的，容器内 SQLite 会在重部署时丢数据，
所以生产环境数据库必须在容器外，只通过 DATABASE_URL 连接。

本地开发由 docker-compose 起一个 postgres 服务。
"""
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .base import SessionStore, StoredMessage, StoredSession
from .models import Base


class PostgresSessionStore(SessionStore):
    def __init__(self, database_url: str) -> None:
        # 需要 asyncpg 驱动：postgresql+asyncpg://...
        self._engine: AsyncEngine = create_async_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_tables(self) -> None:
        """启动时调用。demo 阶段用 create_all 代替迁移工具。"""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def create_session(self, title: str) -> StoredSession:
        raise NotImplementedError

    async def get_session(self, session_id: str) -> StoredSession | None:
        raise NotImplementedError

    async def list_sessions(self) -> list[StoredSession]:
        raise NotImplementedError

    async def append_message(self, session_id: str, message: StoredMessage) -> None:
        raise NotImplementedError

    async def get_messages(self, session_id: str) -> list[StoredMessage]:
        raise NotImplementedError
