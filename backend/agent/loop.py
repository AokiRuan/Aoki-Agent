"""自建 Agent Loop —— 本项目的核心。

核心循环：

    messages → LLM(tools=mcp_schemas) → 有 tool_calls?
       ├─ 是 → 经 MCP client 执行 → 结果追加到 messages → 回到开头
       └─ 否 → 输出最终回答

实现顺序（Day 2）：先做非流式版本把逻辑跑通，再加流式。
流式 + tool_calls 的增量拼接是这里最容易低估的部分。
"""
from typing import AsyncIterator

from .events import AgentEvent


class AgentLoop:
    def __init__(self, llm, mcp_pool, harness) -> None:
        self.llm = llm
        self.mcp_pool = mcp_pool
        self.harness = harness

    async def run(self, messages: list[dict]) -> AsyncIterator[AgentEvent]:
        """执行一轮完整对话，产出事件流。

        messages 是已经载入的会话历史 + 本轮用户输入。
        调用方负责把产生的消息写回 SessionStore。
        """
        raise NotImplementedError
        yield  # pragma: no cover - 保持函数为异步生成器
