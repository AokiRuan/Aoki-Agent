"""Agent loop 测试：用按剧本回复的假 LLM 和假工具，不花 token、结果确定。
讲解见 docs/05-agent-loop.md。
"""
import asyncio
import copy

from backend.agent.harness import FORCE_FINAL_INSTRUCTION, Harness
from backend.agent.llm import LLMResponse, ToolCall
from backend.agent.loop import AgentLoop
from backend.agent.mcp_client import ToolOutcome

SCHEMAS = [{"type": "function", "function": {"name": "search_anime", "parameters": {}}}]


class FakeLLM:
    """按顺序返回预先写好的回复；记录每次收到的请求。"""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    async def chat(self, messages, tools=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": tools})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeTools:
    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or (lambda name, args: ToolOutcome(data={"ok": name}, is_error=False, text=f"{name} ok"))

    def tool_schemas(self):
        return SCHEMAS

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        result = self.handler(name, arguments)
        return await result if asyncio.iscoroutine(result) else result


def call(id, name="search_anime", **args):
    import json
    return ToolCall(id=id, name=name, arguments=args, raw_arguments=json.dumps(args))


def answer(text):
    return LLMResponse(content=text, finish_reason="stop")


def with_tools(*calls, content=None):
    return LLMResponse(content=content, tool_calls=list(calls), finish_reason="tool_calls")


async def run(loop, messages):
    return [e async for e in loop.run(messages)]


USER = [{"role": "system", "content": "sys"}, {"role": "user", "content": "莉可丽丝的圣地"}]


async def test_plain_answer_without_tools():
    llm = FakeLLM(answer("你好"))
    events = await run(AgentLoop(llm, FakeTools(), Harness()), USER)

    assert [e.type for e in events] == ["token", "done"]
    assert events[-1].payload["new_messages"] == [{"role": "assistant", "content": "你好"}]
    assert llm.requests[0]["tools"] == SCHEMAS


async def test_one_tool_round_then_answer():
    llm = FakeLLM(with_tools(call("c1", title="莉可丽丝"), content="我来查一下"), answer("找到了"))
    tools = FakeTools()
    events = await run(AgentLoop(llm, tools, Harness()), USER)

    assert [e.type for e in events] == ["token", "tool_call", "tool_result", "token", "done"]
    assert tools.calls == [("search_anime", {"title": "莉可丽丝"})]
    # tool_call 与 tool_result 靠同一个 id 对应
    assert events[1].tool_call_id == events[2].tool_call_id == "c1"

    # 第二次问 LLM 时，历史里有：带 tool_calls 的 assistant 消息 + 对应 id 的 tool 消息
    second = llm.requests[1]["messages"]
    assert second[-2]["tool_calls"][0]["id"] == "c1"
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "search_anime ok"}

    new = events[-1].payload["new_messages"]
    assert [m["role"] for m in new] == ["assistant", "tool", "assistant"]
    assert events[-1].payload["iterations"] == 2


async def test_parallel_tool_calls_run_concurrently():
    both_started = asyncio.Event()
    started = []

    async def handler(name, args):
        started.append(args["title"])
        if len(started) == 2:
            both_started.set()
        # 如果是串行执行，第一个调用会一直等不到第二个开始 → 超时失败
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return ToolOutcome(data=None, is_error=False, text=args["title"])

    llm = FakeLLM(with_tools(call("a", title="京都"), call("b", title="东京")), answer("done"))
    events = await run(AgentLoop(llm, FakeTools(handler), Harness()), USER)

    results = [e for e in events if e.type == "tool_result"]
    assert [e.tool_call_id for e in results] == ["a", "b"]  # 结果按调用顺序回填
    assert sorted(started) == ["东京", "京都"]


async def test_tool_error_is_handed_back_to_llm():
    def handler(name, args):
        return ToolOutcome(data=None, is_error=True, text="服务不可用")

    llm = FakeLLM(with_tools(call("c1")), answer("抱歉，服务暂时不可用"))
    events = await run(AgentLoop(llm, FakeTools(handler), Harness()), USER)

    assert events[1].type == "tool_result" and events[1].payload["is_error"] is True
    assert llm.requests[1]["messages"][-1]["content"] == "服务不可用"
    assert events[-1].type == "done"


async def test_invalid_json_arguments_are_not_executed():
    bad = ToolCall(id="c1", name="search_anime", arguments={}, raw_arguments="{oops", parse_error="参数不是合法的 JSON")
    llm = FakeLLM(with_tools(bad), answer("ok"))
    tools = FakeTools()
    await run(AgentLoop(llm, tools, Harness()), USER)

    assert tools.calls == []
    fed_back = llm.requests[1]["messages"][-1]["content"]
    assert "参数不是合法的 JSON" in fed_back and "请修正参数" in fed_back
    # 写回历史的是 LLM 的原文参数，而不是解析后的空 dict
    assert llm.requests[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"] == "{oops"


async def test_repeated_identical_calls_are_short_circuited():
    same = lambda i: with_tools(call(f"c{i}", title="同一个"))  # noqa: E731
    llm = FakeLLM(same(1), same(2), same(3), answer("好吧"))
    tools = FakeTools()
    await run(AgentLoop(llm, tools, Harness(max_repeat_calls=2)), USER)

    assert len(tools.calls) == 2  # 第三次没有真正执行
    assert "已经用相同的参数调用过" in llm.requests[3]["messages"][-1]["content"]


async def test_iteration_limit_forces_final_answer_without_tools():
    llm = FakeLLM(
        with_tools(call("c1", title="1")),
        with_tools(call("c2", title="2")),
        answer("根据已有信息回答"),
    )
    events = await run(AgentLoop(llm, FakeTools(), Harness(max_iterations=2)), USER)

    final_request = llm.requests[2]
    assert final_request["tools"] is None
    assert final_request["messages"][-1]["content"] == FORCE_FINAL_INSTRUCTION

    done = events[-1]
    assert done.type == "done" and done.payload["iterations"] == 3
    # 收尾指令不是用户说的话，不能被存进会话
    assert all(m.get("content") != FORCE_FINAL_INSTRUCTION for m in done.payload["new_messages"])


async def test_llm_failure_yields_error_event():
    llm = FakeLLM(RuntimeError("401 Unauthorized"))
    events = await run(AgentLoop(llm, FakeTools(), Harness()), USER)

    assert [e.type for e in events] == ["error"]
    assert "401" in events[0].message


async def test_input_messages_not_mutated_and_usage_summed():
    first = with_tools(call("c1"))
    first.usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110, "prompt_tokens_details": {}}
    second = answer("ok")
    second.usage = {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140}
    original = copy.deepcopy(USER)

    events = await run(AgentLoop(FakeLLM(first, second), FakeTools(), Harness()), USER)

    assert USER == original
    assert events[-1].payload["usage"] == {"prompt_tokens": 220, "completion_tokens": 30, "total_tokens": 250}
