"""Agent loop 对外产出的结构化事件。

loop 内部不直接写 SSE，而是 yield 这些事件，由 app/routes/chat.py 转成 SSE 帧。
这样 loop 既能被 HTTP 层消费，也能被评测脚本直接消费。
"""
from typing import Any, Literal, Optional
from pydantic import BaseModel

EventType = Literal["token", "tool_call", "tool_result", "done", "error"]


class AgentEvent(BaseModel):
    """所有事件的统一载体。"""

    type: EventType
    # token: 增量文本片段
    content: Optional[str] = None
    # tool_call / tool_result: 工具名与调用 id（同一次调用的两个事件 id 相同）
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    # tool_call: LLM 给出的参数；tool_result: MCP 返回的结果
    payload: Optional[dict[str, Any]] = None
    # error: 错误信息
    message: Optional[str] = None


# TODO(Day 2): 按需补充构造辅助函数，例如 token_event() / tool_call_event()
