"""圣地巡礼 MCP Server（自建）。

用 MCP SDK 2.x + stdio 传输，由后端作为子进程拉起。
开发时用 MCP Inspector 单独验证，不要一上来就接进 agent：

    mcp dev backend/mcp_servers/seichi/server.py

数据源见 repository.py。当前是 mock —— Anitabi 被 Cloudflare 拦截，
且其线上 API 已不再返回地标级 geo（实测 0/84），解封后需先解决坐标补全。
"""
from typing import Any

# 注意：MCP SDK 2.x 把 FastMCP 改名为 MCPServer，网上多数教程还是 1.x 的写法
from mcp.server.mcpserver import MCPServer

from .repository import get_repository

mcp = MCPServer("seichi")
repo = get_repository()


@mcp.tool()
def search_anime(title: str) -> list[dict[str, Any]]:
    """按作品名搜索动画，返回作品 id 与基本信息。

    拿到 anime_id 后用 list_spots 查该作品的圣地。
    支持中文名、日文原名、城市名模糊匹配。
    """
    return repo.search_anime(title)


@mcp.tool()
def list_spots(anime_id: int) -> list[dict[str, Any]]:
    """列出某作品的全部圣地：名称、经纬度、对应集数与时间点、所在城市。

    anime_id 来自 search_anime 的返回结果。
    """
    return repo.list_spots(anime_id)


@mcp.tool()
def get_spot(spot_id: str) -> dict[str, Any]:
    """查询单个圣地的详情。spot_id 来自 list_spots 的返回结果。"""
    spot = repo.get_spot(spot_id)
    if spot is None:
        # 返回而不是抛异常——让 LLM 自己决定是换个 id 重试还是告诉用户查不到
        return {"error": f"未找到圣地 {spot_id}"}
    return spot


if __name__ == "__main__":
    mcp.run(transport="stdio")
