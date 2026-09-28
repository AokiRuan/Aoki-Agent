"""SessionStore 的内存实现（Day 2）。

进程重启即丢，仅用于把 loop 跑通。Day 4 换 postgres.py。
"""
from .base import SessionStore, StoredMessage, StoredSession


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, StoredSession] = {}
        self._messages: dict[str, list[StoredMessage]] = {}

    async def create_session(self, title: str) -> StoredSession:
        raise NotImplementedError

    async def get_session(self, session_id: str) -> StoredSession | None:
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list[StoredSession]:
        raise NotImplementedError

    async def append_message(self, session_id: str, message: StoredMessage) -> None:
        raise NotImplementedError

    async def get_messages(self, session_id: str) -> list[StoredMessage]:
        return self._messages.get(session_id, [])
