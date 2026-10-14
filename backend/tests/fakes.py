"""测试用的假 LLM、假工具与辅助函数。loop 测试与 API 测试共用。讲解见 docs/05-agent-loop.md。

（文件名不以 test_ 开头，pytest 不会把它当测试收集。）
"""
import asyncio
import copy
import json

from backend.agent.llm import LLMResponse, TextDelta, ToolCall
from backend.agent.mcp_client import ToolOutcome

SCHEMAS = [{"type": "function", "function": {"name": "search_anime", "parameters": {}}}]


class FakeLLM:
    """按顺序返回预先写好的回复；记录每次收到的请求。

    模拟流式：把回复的文字按 2 个字一片切开逐片产出，最后产出完整的 LLMResponse。
    """

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    async def stream(self, messages, tools=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": tools})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        text = step.content or ""
        for i in range(0, len(text), 2):
            yield TextDelta(text[i : i + 2])
        yield step


class FakeTools:
    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or (
            lambda name, args: ToolOutcome(data={"ok": name}, is_error=False, text=f"{name} ok")
        )

    def tool_schemas(self):
        return SCHEMAS

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        result = self.handler(name, arguments)
        return await result if asyncio.iscoroutine(result) else result


def call(id, name="search_anime", **args):
    return ToolCall(id=id, name=name, arguments=args, raw_arguments=json.dumps(args))


def answer(text):
    return LLMResponse(content=text, finish_reason="stop")


def with_tools(*calls, content=None):
    return LLMResponse(content=content, tool_calls=list(calls), finish_reason="tool_calls")


def tokens(events):
    """把所有 token 事件拼回完整文字。"""
    return "".join(e.content for e in events if e.type == "token")


def types(events):
    """事件类型序列，连续的 token 合并成一个，便于断言。"""
    out = []
    for e in events:
        if not (e.type == "token" and out and out[-1] == "token"):
            out.append(e.type)
    return out
