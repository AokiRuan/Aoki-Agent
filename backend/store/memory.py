"""SessionStore 的内存实现。讲解见 docs/08-fastapi-sse.md。

进程重启即丢，用于本地开发与测试。Day 4 换 postgres.py。

所有方法里都没有 await，所以在 asyncio 的单线程模型下天然是原子的，不需要加锁。
"""
from __future__ import annotations

import uuid

from .base import SessionNotFound, SessionStore, StoredMessage, StoredSession, utcnow


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, StoredSession] = {}
        self._messages: dict[str, list[StoredMessage]] = {}

    async def create_session(self, title: str) -> StoredSession:
        now = utcnow()
        session = StoredSession(id=str(uuid.uuid4()), title=title, created_at=now, updated_at=now)
        self._sessions[session.id] = session
        self._messages[session.id] = []
        return session

    async def get_session(self, session_id: str) -> StoredSession | None:
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list[StoredSession]:
        return sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)

    async def append_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        self._messages[session_id].extend(messages)
        self._sessions[session_id] = self._sessions[session_id].model_copy(update={"updated_at": utcnow()})

    async def get_messages(self, session_id: str) -> list[StoredMessage]:
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        # 返回副本：调用方修改列表不会影响存储
        return list(self._messages[session_id])
