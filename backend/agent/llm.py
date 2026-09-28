"""LLM provider 抽象。

保留这层是为了随时能换模型——DeepSeek 的 tool calling 稳定性是 Day 2 的已知风险，
换 provider 时 loop.py 不应该有任何改动。

所有候选 provider 都兼容 OpenAI SDK，所以这里薄薄一层即可。
Langfuse 用 `langfuse.openai` 的 drop-in 替换，在这里接入而不是散落在 loop 里。
"""
from typing import Any, AsyncIterator


class LLMClient:
    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self.model = model
        # TODO(Day 2): 初始化 AsyncOpenAI 客户端
        raise NotImplementedError

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        """非流式调用。Day 2 先用它把 loop 逻辑跑通。"""
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Any]:
        """流式调用。注意 tool_calls 在流式模式下是分片到达的，需要按 index 累积拼接。"""
        raise NotImplementedError
        yield  # pragma: no cover - 保持函数为异步生成器
