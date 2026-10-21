"""会话读取接口。讲解见 docs/08-fastapi-sse.md。

GET /api/sessions        —— 列表（按最近更新倒序），供前端侧栏渲染
GET /api/sessions/{id}   —— 完整消息，供刷新页面后恢复，包含工具调用记录与地图打点数据
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.store.base import SessionNotFound

from ..chat_service import ChatService
from ..deps import get_service
from ..schemas import SessionDetail, SessionOut

router = APIRouter(prefix="/sessions")


@router.get("", response_model=list[SessionOut])
async def list_sessions(service: ChatService = Depends(get_service)):
    return await service.store.list_sessions()


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, service: ChatService = Depends(get_service)):
    session = await service.store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    try:
        messages = await service.store.get_messages(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return SessionDetail(**session.model_dump(), messages=messages)
