"""圣地巡礼 MCP Server（自建）。

用 FastMCP + stdio 传输，由后端作为子进程拉起。
开发时用 MCP Inspector 单独验证，不要一上来就接进 agent。

数据源（Day 1 上午限时 2 小时决定）：
- 首选：Anitabi 开放 API —— 需验证可用性、调用限制与使用条款
- 兜底：data/ 下手工整理 5~10 部作品的 JSON，demo 够用且完全可控
超时就直接切兜底，别让这里堵住后面四天。
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("seichi")


@mcp.tool()
def search_anime(title: str) -> list[dict]:
    """按作品名模糊搜索动画，返回作品 id 与基本信息。"""
    raise NotImplementedError


@mcp.tool()
def list_spots(anime_id: str) -> list[dict]:
    """返回某作品的全部圣地：名称、经纬度、对应剧集/场景、地址。"""
    raise NotImplementedError


@mcp.tool()
def get_spot(spot_id: str) -> dict:
    """单个圣地的详情。"""
    raise NotImplementedError


if __name__ == "__main__":
    mcp.run()
