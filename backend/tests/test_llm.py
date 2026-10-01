"""LLM 客户端测试：用 MockTransport 模拟 OpenAI 兼容接口的响应。讲解见 docs/05-agent-loop.md。"""
import json
from datetime import datetime, timezone

import httpx
from openai import AsyncOpenAI

from backend.agent.llm import LLMClient, parse_tool_arguments
from backend.agent.prompts import build_system_prompt


def completion(message, finish_reason="stop"):
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-chat",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def client_returning(body, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sdk = AsyncOpenAI(api_key="test", base_url="https://llm.test/v1", http_client=http)
    return LLMClient("deepseek-chat", "test", client=sdk)


async def test_parses_tool_calls_and_content_together():
    # DeepSeek 实测：返回 tool_calls 时 content 往往也有一句说明
    body = completion(
        {
            "role": "assistant",
            "content": "我来查一下",
            "tool_calls": [
                {"id": "c0", "type": "function", "function": {"name": "search_anime", "arguments": '{"title": "莉可丽丝"}'}},
                {"id": "c1", "type": "function", "function": {"name": "get_spot", "arguments": '{"spot_id": "x"}'}},
            ],
        },
        finish_reason="tool_calls",
    )
    seen = []
    resp = await client_returning(body, seen).chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

    assert resp.content == "我来查一下"
    assert [tc.name for tc in resp.tool_calls] == ["search_anime", "get_spot"]
    assert resp.tool_calls[0].arguments == {"title": "莉可丽丝"}
    assert resp.usage["total_tokens"] == 15
    assert seen[0]["tools"] == [{"type": "function"}]

    msg = resp.to_message()
    assert msg["content"] == "我来查一下"
    assert msg["tool_calls"][0]["function"]["arguments"] == '{"title": "莉可丽丝"}'


async def test_no_tools_param_when_tools_empty():
    seen = []
    await client_returning(completion({"role": "assistant", "content": "ok"}), seen).chat([], tools=None)
    assert "tools" not in seen[0]


def test_parse_tool_arguments_errors():
    assert parse_tool_arguments('{"a": 1}') == ({"a": 1}, None)
    assert parse_tool_arguments("") == ({}, None)
    args, err = parse_tool_arguments("{oops")
    assert args == {} and "不是合法的 JSON" in err
    assert parse_tool_arguments("[1, 2]")[1] == "参数必须是 JSON 对象"


def test_system_prompt_uses_japan_date():
    # UTC 10/02 20:00 = 日本时间 10/03 05:00（周六）
    prompt = build_system_prompt(datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc))
    assert "今天是 2026-10-03（周六），日本时间 05:00" in prompt
