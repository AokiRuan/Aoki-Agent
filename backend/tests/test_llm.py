"""LLM 客户端测试：用 MockTransport 模拟 OpenAI 兼容接口的响应。讲解见 docs/05-agent-loop.md。"""
import json
from datetime import datetime, timezone

import httpx
from openai import AsyncOpenAI

from backend.agent.llm import LLMClient, LLMResponse, TextDelta, parse_tool_arguments
from backend.agent.prompts import build_system_prompt


def sse_body(chunks):
    """把一组 chunk 编码成 OpenAI 流式接口的 SSE 响应体。"""
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def chunk(delta=None, finish=None, usage=None, choices=True):
    c = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "deepseek-chat"}
    c["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if choices else []
    if usage:
        c["usage"] = usage
    return c


def tc_piece(index, args, id=None, name=None):
    piece = {"index": index, "function": {"arguments": args}}
    if id:
        piece.update(id=id, type="function")
        piece["function"]["name"] = name
    return {"tool_calls": [piece]}


def streaming_client(chunks, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body(chunks))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sdk = AsyncOpenAI(api_key="test", base_url="https://llm.test/v1", http_client=http)
    return LLMClient("deepseek-chat", "test", client=sdk)


USAGE = {"prompt_tokens": 323, "completion_tokens": 157, "total_tokens": 480}


async def test_stream_assembles_fragmented_tool_calls_like_deepseek():
    # 按 DeepSeek 实测的分片方式：先文字，再两个工具调用；参数被切成很碎的片段；
    # usage 和 finish_reason 在同一片
    chunks = [
        chunk({"role": "assistant", "content": ""}),
        chunk({"content": "我先"}),
        chunk({"content": "查一下"}),
        chunk(tc_piece(0, "", id="call_00", name="get_weather_forecast")),
        *[chunk(tc_piece(0, p)) for p in ['{"', "lat", '": 34', ".99", ', "l', "ng", '": 135.76}']],
        chunk(tc_piece(1, "", id="call_01", name="get_weather_forecast")),
        *[chunk(tc_piece(1, p)) for p in ['{"lat": 35.68', ', "lng": 139.77}']],
        chunk({}, finish="tool_calls", usage=USAGE),
    ]
    seen = []
    items = [i async for i in streaming_client(chunks, seen).stream([{"role": "user", "content": "hi"}], tools=[{}])]

    assert [i.text for i in items if isinstance(i, TextDelta)] == ["我先", "查一下"]
    final = items[-1]
    assert isinstance(final, LLMResponse) and len(items) == 3
    assert final.content == "我先查一下"
    assert [(tc.id, tc.arguments) for tc in final.tool_calls] == [
        ("call_00", {"lat": 34.99, "lng": 135.76}),
        ("call_01", {"lat": 35.68, "lng": 139.77}),
    ]
    assert final.finish_reason == "tool_calls"
    assert final.usage["total_tokens"] == 480
    # 请求里必须带上 stream 与 include_usage
    assert seen[0]["stream"] is True and seen[0]["stream_options"] == {"include_usage": True}


async def test_stream_usage_in_separate_empty_chunk_like_openai():
    chunks = [
        chunk({"content": "宇治"}),
        chunk({}, finish="stop"),
        chunk(choices=False, usage=USAGE),  # OpenAI 官方：usage 单独一片，choices 为空
    ]
    items = [i async for i in streaming_client(chunks).stream([])]
    final = items[-1]
    assert final.content == "宇治" and final.tool_calls == []
    assert final.usage["prompt_tokens"] == 323


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
