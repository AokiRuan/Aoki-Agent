"""圣地巡礼 MCP server 测试。讲解见 docs/03-mcp-server.md。"""
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.mcp_servers.seichi import server
from backend.mcp_servers.seichi.repository import MockRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def test_stdio_roundtrip_as_subprocess():
    """走真实协议：把 server 拉成子进程，经 stdin/stdout 的 JSON-RPC 调用工具。
    这正是 Day 2 的 mcp_client.py 要做的事。"""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.mcp_servers.seichi.server"],
        cwd=str(PROJECT_ROOT),
        env={"PYTHONIOENCODING": "utf-8"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_anime", {"title": "莉可丽丝"})

    assert result.is_error is False
    # 返回 list 的工具，结构化结果会被包成 {"result": [...]}
    assert result.structured_content["result"][0]["anime_id"] == 364450


async def test_three_tools_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert names == {"search_anime", "list_spots", "get_spot"}


async def test_tool_schema_generated_from_type_hints():
    # MCP SDK 从函数签名自动生成 JSON Schema —— 这就是 learn/tools/registry.py 手工拼的那部分
    tools = {t.name: t for t in await server.mcp.list_tools()}
    schema = tools["list_spots"].input_schema
    assert schema["properties"]["anime_id"]["type"] == "integer"
    assert schema["required"] == ["anime_id"]


def test_search_by_chinese_japanese_and_city():
    assert server.search_anime("莉可丽丝")[0]["anime_id"] == 364450
    assert server.search_anime("ユーフォニアム")[0]["anime_id"] == 115908
    assert server.search_anime("宇治")[0]["anime_id"] == 115908


def test_search_miss_and_blank_return_empty():
    assert server.search_anime("不存在的作品") == []
    assert server.search_anime("   ") == []


def test_search_result_excludes_points():
    # 摘要不带地标列表，避免一次把 LLM 上下文塞满
    hit = server.search_anime("莉可丽丝")[0]
    assert "points" not in hit
    assert hit["spots_count"] == 5


def test_list_spots_shape():
    spots = server.list_spots(364450)
    assert len(spots) == 5
    first = spots[0]
    for key in ("spot_id", "name_ja", "lat", "lng", "episode", "origin", "origin_url"):
        assert key in first


def test_unknown_spot_returns_error_instead_of_raising():
    # 返回 error 而不是抛异常：让 LLM 自己决定重试还是告诉用户
    assert "error" in server.get_spot("bad-id")


def test_every_mock_spot_has_coordinates():
    repo = MockRepository()
    for anime in repo._anime:
        for spot in repo.list_spots(anime["id"]):
            assert spot["lat"] is not None and spot["lng"] is not None, spot["spot_id"]
