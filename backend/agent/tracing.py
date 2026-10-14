"""Langfuse 可观测性接入。讲解见 docs/09-langfuse.md。

设计：**装饰器模式**。loop 只认识 ChatModel 与 ToolExecutor 两个接口，
所以给它们各套一层"带记录功能的外壳"，loop、LLMClient、MCPClientPool 都不用改：

    TracedLLM(LLMClient)          → 每次 LLM 调用记录成一个 generation（输入、输出、token、首字延迟）
    TracedTools(MCPClientPool)    → 每次工具调用记录成一个 tool（参数、结果、是否失败）
    Tracing.turn(...)             → 一次完整回答记录成一个 agent，上面两类挂在它下面

trace 结构：
    agent-turn (agent)            session_id = 会话 id
    ├── llm (generation)
    ├── search_anime (tool)
    ├── llm (generation)
    └── ...

没配 key 时 Tracing 处于关闭状态：wrap_* 原样返回，turn() 什么都不做。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator

from .llm import ChatModel, LLMResponse, StreamItem, TextDelta
from .mcp_client import ToolExecutor, ToolOutcome


class Turn:
    """一次完整回答对应的 trace 节点。关闭状态下是个空壳。"""

    def __init__(self, span: Any = None) -> None:
        self._span = span

    def finish(self, output: str, *, iterations: int, usage: dict[str, int]) -> None:
        if self._span:
            self._span.update(output=output, metadata={"iterations": iterations, "usage": usage})

    def fail(self, message: str) -> None:
        if self._span:
            self._span.update(level="ERROR", status_message=message)


class Tracing:
    def __init__(self, client: Any = None) -> None:
        self._lf = client

    @property
    def enabled(self) -> bool:
        return self._lf is not None

    @classmethod
    def from_settings(cls, public_key: str, secret_key: str, host: str) -> Tracing:
        """未配置 key 时返回关闭状态的 Tracing，不阻塞本地开发与测试。"""
        if not (public_key and secret_key):
            return cls(None)
        from langfuse import Langfuse  # 延迟导入：关闭时不加载 OpenTelemetry 那一整套

        # 显式传 key，而不是依赖 LANGFUSE_* 环境变量：我们的配置来自 .env + pydantic-settings，
        # 并不在 os.environ 里。注意 Langfuse Cloud 分区（EU / US / JP），host 必须与项目所在区一致
        return cls(Langfuse(public_key=public_key, secret_key=secret_key, base_url=host))

    def wrap_llm(self, llm: ChatModel, model: str) -> ChatModel:
        return TracedLLM(llm, self._lf, model) if self.enabled else llm

    def wrap_tools(self, tools: ToolExecutor) -> ToolExecutor:
        return TracedTools(tools, self._lf) if self.enabled else tools

    @contextmanager
    def turn(self, *, session_id: str | None, user_input: str) -> Iterator[Turn]:
        """把一次完整回答包成一个 agent 节点，期间所有 LLM / 工具调用自动挂到它下面。"""
        if not self.enabled:
            yield Turn()
            return
        from langfuse import propagate_attributes

        # propagate_attributes 把 session_id 打到这个 trace 上：
        # Langfuse 的 Sessions 页面会把同一会话的多次回答归到一起
        with propagate_attributes(session_id=session_id, trace_name="chat-turn"):
            with self._lf.start_as_current_observation(
                name="agent-turn", as_type="agent", input=user_input
            ) as span:
                yield Turn(span)

    def shutdown(self) -> None:
        """进程退出前调用：把缓冲中的数据发完再关闭。不调用的话，最后几条 trace 会丢。

        注意 Langfuse 不可达时这里会阻塞约 5 秒（实测），所以只在退出时调一次，
        不要在每次请求后调 flush。平时数据由后台线程批量发送，不阻塞请求。
        """
        if self.enabled:
            self._lf.shutdown()


class TracedLLM:
    """给 ChatModel 套上 generation 记录。"""

    def __init__(self, inner: ChatModel, lf: Any, model: str) -> None:
        self._inner = inner
        self._lf = lf
        self._model = model

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamItem]:
        tool_names = [t["function"]["name"] for t in tools or []]
        with self._lf.start_as_current_observation(
            name="llm",
            as_type="generation",
            model=self._model,
            input=messages,
            metadata={"tools": tool_names},
        ) as gen:
            first_token_seen = False
            async for item in self._inner.stream(messages, tools):
                if isinstance(item, TextDelta) and not first_token_seen:
                    # 首字时间：Langfuse 据此算出「首字延迟」，流式体验好不好主要看它
                    gen.update(completion_start_time=datetime.now(timezone.utc))
                    first_token_seen = True
                elif isinstance(item, LLMResponse):
                    gen.update(output=item.to_message(), usage_details=_usage_details(item.usage))
                yield item


class TracedTools:
    """给 ToolExecutor 套上 tool 记录。"""

    def __init__(self, inner: ToolExecutor, lf: Any) -> None:
        self._inner = inner
        self._lf = lf

    def tool_schemas(self) -> list[dict[str, Any]]:
        return self._inner.tool_schemas()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        with self._lf.start_as_current_observation(name=name, as_type="tool", input=arguments) as span:
            outcome = await self._inner.call_tool(name, arguments)
            if outcome.is_error:
                span.update(output=outcome.text, level="ERROR", status_message=outcome.text[:200])
            else:
                span.update(output=outcome.data)
            return outcome


def _usage_details(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """OpenAI 的字段名 → Langfuse 的字段名。"""
    if not usage:
        return None
    mapping = {"prompt_tokens": "input", "completion_tokens": "output", "total_tokens": "total"}
    return {lf_key: usage[k] for k, lf_key in mapping.items() if isinstance(usage.get(k), int)}
