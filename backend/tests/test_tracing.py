"""tracing 装饰器测试：用一个记录调用的假 Langfuse 客户端，不连网络。讲解见 docs/09-langfuse.md。"""
from contextlib import contextmanager

from backend.agent.harness import Harness
from backend.agent.loop import AgentLoop
from backend.agent.mcp_client import ToolOutcome
from backend.agent.tracing import Tracing
from backend.tests.fakes import FakeLLM, FakeTools, answer, call, with_tools


class FakeSpan:
    def __init__(self, kwargs):
        self.start = kwargs
        self.updates = {}

    def update(self, **kwargs):
        self.updates.update(kwargs)


class FakeLangfuse:
    """只实现 tracing.py 用到的那一个方法，按创建顺序记录所有节点。"""

    def __init__(self):
        self.spans = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        span = FakeSpan(kwargs)
        self.spans.append(span)
        yield span


def by_type(lf, as_type):
    return [s for s in lf.spans if s.start["as_type"] == as_type]


async def test_disabled_tracing_returns_components_unchanged():
    tracing = Tracing(None)
    llm, tools = FakeLLM(), FakeTools()
    assert tracing.wrap_llm(llm, "m") is llm
    assert tracing.wrap_tools(tools) is tools
    with tracing.turn(session_id="s", user_input="hi") as turn:
        turn.finish("ok", iterations=1, usage={})  # 空壳，不报错


async def test_full_turn_records_agent_generations_and_tools():
    lf = FakeLangfuse()
    tracing = Tracing(lf)
    llm = FakeLLM(with_tools(call("c1", title="莉可丽丝"), content="我来查"), answer("找到了"))
    llm.script[0].usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
    loop = AgentLoop(tracing.wrap_llm(llm, "deepseek-chat"), tracing.wrap_tools(FakeTools()), Harness())

    with tracing.turn(session_id="s1", user_input="莉可丽丝的圣地") as turn:
        events = [e async for e in loop.run([{"role": "user", "content": "莉可丽丝的圣地"}])]
        done = events[-1].payload
        turn.finish("找到了", iterations=done["iterations"], usage=done["usage"])

    agent = by_type(lf, "agent")[0]
    assert agent.start["input"] == "莉可丽丝的圣地"
    assert agent.updates["output"] == "找到了"

    gens = by_type(lf, "generation")
    assert len(gens) == 2  # 两轮 LLM 调用
    assert gens[0].start["model"] == "deepseek-chat"
    assert gens[0].start["metadata"] == {"tools": ["search_anime"]}
    assert gens[0].updates["usage_details"] == {"input": 100, "output": 10, "total": 110}
    assert "completion_start_time" in gens[0].updates  # 记录了首字时间
    assert gens[1].updates["output"]["content"] == "找到了"

    tool = by_type(lf, "tool")[0]
    assert tool.start["name"] == "search_anime" and tool.start["input"] == {"title": "莉可丽丝"}
    assert tool.updates["output"] == {"ok": "search_anime"}


async def test_tool_error_marked_as_error_level():
    lf = FakeLangfuse()
    failing = FakeTools(lambda name, args: ToolOutcome(data=None, is_error=True, text="服务不可用"))
    tools = Tracing(lf).wrap_tools(failing)

    await tools.call_tool("get_weather_forecast", {"lat": 35, "lng": 135})

    span = by_type(lf, "tool")[0]
    assert span.updates["level"] == "ERROR"
    assert span.updates["status_message"] == "服务不可用"


async def test_traced_tools_still_exposes_schemas():
    tools = FakeTools()
    assert Tracing(FakeLangfuse()).wrap_tools(tools).tool_schemas() == tools.tool_schemas()
