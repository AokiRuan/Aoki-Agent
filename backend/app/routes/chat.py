"""POST /api/chat —— SSE 流式端点。讲解见 docs/08-fastapi-sse.md。
路由本身不带 /api 前缀，由 main.py 在 include_router 时统一加上。

线上格式（每个事件之间空一行）：

    event: session
    data: {"session_id": "...", "title": "..."}

    event: token
    data: {"content": "我来"}

    event: tool_call
    data: {"tool_name": "search_anime", "tool_call_id": "call_00", "payload": {"title": "莉可丽丝"}}

    event: tool_result
    data: {"tool_name": "search_anime", "tool_call_id": "call_00", "payload": {"is_error": false, "data": [...]}}

    event: done
    data: {"payload": {"iterations": 3, "usage": {...}}}

出错时最后一个事件是 error（data 里有 message），之后不会再有 done。
"""
import json
from collections.abc import AsyncIterable
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from backend.agent.events import AgentEvent
from backend.store.base import StoredSession

from ..chat_service import ChatService
from ..deps import get_service, resolve_chat_session
from ..schemas import ChatRequest

router = APIRouter()


@router.post("/chat", response_class=EventSourceResponse)
async def chat(
    body: ChatRequest,
    session: StoredSession = Depends(resolve_chat_session),
    service: ChatService = Depends(get_service),
) -> AsyncIterable[ServerSentEvent]:
    # 第一个事件告诉前端会话 id：新建会话时前端靠它在下一轮带上 session_id
    yield _sse("session", {"session_id": session.id, "title": session.title})
    async for event in service.run_turn(session, body.message):
        yield _sse(event.type, _public(event))


def _sse(event: str, data: dict[str, Any]) -> ServerSentEvent:
    # 用 raw_data + 自己序列化，而不是 data=：后者会把中文转义成 宇 这样的序列，
    # curl 里没法读，体积也翻倍。json.dumps 不加 indent 时一定是单行，不会破坏 SSE 的行格式
    return ServerSentEvent(event=event, raw_data=json.dumps(data, ensure_ascii=False))


def _public(event: AgentEvent) -> dict[str, Any]:
    """发给前端的字段。done 里的 new_messages 是内部用来入库的，可能很大，不发。"""
    data = event.model_dump(exclude={"type"}, exclude_none=True)
    if event.type == "done":
        data["payload"] = {k: v for k, v in event.payload.items() if k != "new_messages"}
    return data
