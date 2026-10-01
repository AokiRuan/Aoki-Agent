"""LLM 抽象层。讲解见 docs/05-agent-loop.md。

loop 只认识本文件定义的 LLMResponse / ToolCall，不接触 openai SDK 的类型。
好处：测试时可以用一个按剧本回复的假 LLM 替换；将来换 SDK 或换服务商，loop 不用改。

所有候选 LLM（DeepSeek 等）都兼容 OpenAI 接口，所以真实实现只有一个 LLMClient，
换服务商只需改配置里的 model / base_url。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

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


class ChatModel(Protocol):
    """loop 对 LLM 的全部要求：给消息和工具，返回一个 LLMResponse。

    用 Protocol 而不是 ABC：测试里的假 LLM 不需要继承任何类，方法签名对上即可。
    """

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...


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
        # client 可注入：测试时传入一个走 httpx.MockTransport 的 AsyncOpenAI
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        calls = []
        for tc in msg.tool_calls or []:
            args, err = parse_tool_arguments(tc.function.arguments)
            calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                    raw_arguments=tc.function.arguments or "",
                    parse_error=err,
                )
            )

        return LLMResponse(
            content=msg.content,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            usage=resp.usage.model_dump(exclude_none=True) if resp.usage else None,
        )

    # TODO(第 5 步)：stream_chat —— 流式模式下 tool_calls 分片到达，需要按 index 累积拼接
