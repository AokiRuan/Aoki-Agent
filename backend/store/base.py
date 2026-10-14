"""SessionStore 接口。讲解见 docs/08-fastapi-sse.md。

Day 2 用 memory.py 的实现让服务先跑起来，Day 4 换成 postgres.py。
接口不变，routes 与 loop 都不用动。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StoredMessage(BaseModel):
    """存储的一条消息。字段是 OpenAI 消息格式的超集：

    - 发给 LLM 时用 to_llm_message()，只取 LLM 认识的字段
    - 前端恢复会话时拿全部字段，其中 data / tool_name / is_error 用来复现
      工具调用过程和地图打点（这些信息 LLM 不需要，也不能发给它）
    """

    role: Literal["user", "assistant", "tool"]
    content: Optional[str] = None
    # assistant 消息：本轮发起的工具调用（OpenAI 格式，原样保存以便再发给 LLM）
    tool_calls: Optional[list[dict[str, Any]]] = None
    # tool 消息：对应哪一个调用
    tool_call_id: Optional[str] = None
    # tool 消息：工具名、是否失败、结构化结果 —— 只给前端用
    tool_name: Optional[str] = None
    is_error: Optional[bool] = None
    data: Any = None
    created_at: datetime = Field(default_factory=utcnow)

    def to_llm_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class StoredSession(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class SessionNotFound(KeyError):
    pass


class SessionStore(ABC):
    @abstractmethod
    async def create_session(self, title: str) -> StoredSession: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[StoredSession]: ...

    @abstractmethod
    async def list_sessions(self) -> list[StoredSession]:
        """按最近更新时间倒序。"""

    @abstractmethod
    async def append_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        """追加一轮对话的全部消息。一轮是一个整体：Postgres 实现里放在同一个事务中，
        不会出现「存了工具调用、没存工具结果」的半截状态（那样的历史再发给 LLM 会被拒绝）。
        会话不存在时抛 SessionNotFound。"""

    @abstractmethod
    async def get_messages(self, session_id: str) -> list[StoredMessage]: ...
