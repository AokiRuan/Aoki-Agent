"""POST /chat —— SSE 流式端点。

流程：
1. session_id 不存在则新建会话（标题取首条用户消息截断）
2. 从 store 载入历史，追加本轮用户消息
3. 跑 AgentLoop，把 AgentEvent 转成 SSE 帧下发
4. 循环结束后把 assistant 消息（含 tool_calls / tool_results）写回 store

事件类型：token / tool_call / tool_result / done / error
"""
from fastapi import APIRouter

router = APIRouter()


# TODO(Day 2): @router.post("/chat") -> StreamingResponse(media_type="text/event-stream")
