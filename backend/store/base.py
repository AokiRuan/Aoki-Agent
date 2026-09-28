"""SessionStore 接口。

Day 2 用 memory.py 的实现让 loop 先跑起来，Day 4 换成 postgres.py。
接口不变，routes 与 loop 都不用动——这也是一个小的 harness 设计点。
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class StoredMessage(BaseModel):
    role: str
    content: str | None = None
    # 存 JSON，这样刷新页面后前端能复现工具调用过程与地图打点，
    # 而不只是最终回答
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    created_at: datetime


class StoredSession(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class SessionStore(ABC):
    @abstractmethod
    async def create_session(self, title: str) -> StoredSession: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[StoredSession]: ...

    @abstractmethod
    async def list_sessions(self) -> list[StoredSession]: ...

    @abstractmethod
    async def append_message(self, session_id: str, message: StoredMessage) -> None: ...

    @abstractmethod
    async def get_messages(self, session_id: str) -> list[StoredMessage]: ...
