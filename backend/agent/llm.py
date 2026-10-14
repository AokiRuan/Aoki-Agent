"""LLM 抽象层。讲解见 docs/05-agent-loop.md。

loop 只认识本文件定义的 TextDelta / LLMResponse / ToolCall，不接触 openai SDK 的类型。
好处：测试时可以用一个按剧本回复的假 LLM 替换；将来换 SDK 或换服务商，loop 不用改。

所有候选 LLM（DeepSeek 等）都兼容 OpenAI 接口，所以真实实现只有一个 LLMClient，
换服务商只需改配置里的 model / base_url。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, Union

from openai import AsyncOpenAI


@dataclass
class ToolCall:
    id: str
    name: str
    # 解析后的参数。LLM 生成的 JSON 不合法时为空 dict，并在 parse_error 里记录原因
    arguments: dict[str, Any]
    # LLM 原样给出的参数字符串。写回对话历史时必须用原文
    raw_arguments: str
    parse_error: str | None = None


@dataclass
class LLMResponse:
    # 注意：DeepSeek 返回 tool_calls 时 content 往往也不为空（会附带一句「我来查一下」）
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    def to_message(self) -> dict[str, Any]:
        """转成可以追加到对话历史里的 assistant 消息（OpenAI 格式）。"""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.raw_arguments},
                }
                for tc in self.tool_calls
            ]
        return msg


@dataclass
class TextDelta:
    """流式输出中的一小段文字。"""

    text: str


# 流式接口产出的东西：若干个 TextDelta，最后**恰好一个** LLMResponse（拼好的完整回复）
StreamItem = Union[TextDelta, LLMResponse]


class ChatModel(Protocol):
    """loop 对 LLM 的全部要求：给消息和工具，流式返回文字片段，最后给出完整回复。

    用 Protocol 而不是 ABC：测试里的假 LLM 不需要继承任何类，方法签名对上即可。
    注意这里是 def 不是 async def：async generator 函数被调用时直接返回一个
    异步迭代器，本身不需要 await。
    """

    def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamItem]: ...


def parse_tool_arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
    """解析 LLM 给出的参数字符串。返回 (参数, 错误信息)。"""
    if not raw:
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"参数不是合法的 JSON：{e.msg}"
    if not isinstance(value, dict):
        return {}, "参数必须是 JSON 对象"
    return value, None


def _make_tool_call(id: str, name: str, raw: str) -> ToolCall:
    args, err = parse_tool_arguments(raw)
    return ToolCall(id=id, name=name, arguments=args, raw_arguments=raw, parse_error=err)


def _usage_dict(usage: Any) -> dict[str, Any] | None:
    return usage.model_dump(exclude_none=True) if usage else None


class StreamAssembler:
    """把流式分片拼回一个完整的 LLMResponse。

    实测 DeepSeek 的分片方式：
    - 文字：每片几个字，在 delta.content 里
    - 工具调用：每个调用的第一片带 index、id、name，之后的分片只带 index 和一小段参数
      （小到 "l"、"ng" 这种程度），必须按 index 把参数片段拼起来
    - usage：DeepSeek 放在最后一片（和 finish_reason 一起）；OpenAI 官方则是
      额外再发一片 choices 为空的。两种都要支持
    """

    def __init__(self) -> None:
        self._text: list[str] = []
        self._calls: dict[int, dict[str, str]] = {}
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] | None = None

    def feed(self, chunk: Any) -> str | None:
        """喂入一个分片，返回其中的文字增量（没有则为 None）。"""
        if chunk.usage:
            self.usage = _usage_dict(chunk.usage)
        if not chunk.choices:
            return None

        choice = chunk.choices[0]
        if choice.finish_reason:
            self.finish_reason = choice.finish_reason
        delta = choice.delta

        for tc in delta.tool_calls or []:
            buf = self._calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                buf["id"] = tc.id
            if tc.function and tc.function.name:
                buf["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                buf["arguments"] += tc.function.arguments

        if delta.content:
            self._text.append(delta.content)
            return delta.content
        return None

    def result(self) -> LLMResponse:
        calls = [
            _make_tool_call(b["id"], b["name"], b["arguments"])
            for _, b in sorted(self._calls.items())
        ]
        return LLMResponse(
            content="".join(self._text) or None,
            tool_calls=calls,
            finish_reason=self.finish_reason,
            usage=self.usage,
        )


class LLMClient:
    """OpenAI 兼容接口的实现。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        # client 可注入：测试时传入一个走 httpx.MockTransport 的 AsyncOpenAI；
        # 开启 Langfuse 时传入 langfuse.openai.AsyncOpenAI（见 tracing.py）
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)

    def _kwargs(self, messages, tools) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamItem]:
        """流式调用：边收边产出 TextDelta，结束时产出拼好的 LLMResponse。"""
        resp = await self._client.chat.completions.create(
            **self._kwargs(messages, tools),
            stream=True,
            # 不加这个参数，流式模式下不返回 token 用量
            stream_options={"include_usage": True},
        )
        assembler = StreamAssembler()
        async for chunk in resp:
            text = assembler.feed(chunk)
            if text:
                yield TextDelta(text)
        yield assembler.result()

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """非流式调用。loop 已改用 stream()；保留它给评测脚本等不需要逐字输出的场景。"""
        resp = await self._client.chat.completions.create(**self._kwargs(messages, tools))
        choice = resp.choices[0]
        msg = choice.message
        calls = [
            _make_tool_call(tc.id, tc.function.name, tc.function.arguments or "")
            for tc in msg.tool_calls or []
        ]
        return LLMResponse(
            content=msg.content,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            usage=_usage_dict(resp.usage),
        )
