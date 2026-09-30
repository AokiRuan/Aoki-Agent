"""路线 MCP Server。讲解见 docs/04-external-mcp-servers.md。

包装 OSRM（路线时间/距离）与 Nominatim（地名→坐标）。以模块方式启动：

    python -m backend.mcp_servers.route.server

stdio 模式下 stdout 是 JSON-RPC 通道，禁止 print。
"""
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from .client import TRANSIT_SUGGEST_MIN, Mode, RouteClient, best_order

mcp = MCPServer("route")

# 模块级变量，测试时用 monkeypatch 替换成注入了 MockTransport 的实例
client = RouteClient()


class Stop(BaseModel):
    """路线上的一个点。"""

    name: str = Field(description="地点名称，用于在结果中标识")
    lat: float = Field(ge=-90, le=90, description="纬度")
    lng: float = Field(ge=-180, le=180, description="经度")


@mcp.tool()
async def geocode(
    query: Annotated[str, Field(min_length=1, description="地名、车站名或地址，日文原名最准，如「京都駅」")],
) -> dict[str, Any]:
    """把地名、车站名或地址转换成坐标。

    用于用户提到的出发地/住宿地等不在圣地列表里的地点，
    例如「从京都站出发」→ 先 geocode("京都駅") 拿到坐标，再用 plan_route。
    可能返回多个候选，请根据上下文选择。
    """
    try:
        results = await client.geocode(query.strip())
    except httpx.HTTPError as e:
        return {"error": f"地理编码服务暂时不可用（{type(e).__name__}）"}
    if not results:
        return {"error": f"找不到「{query}」，可以换成日文原名或更具体的地址再试"}
    return {"query": query, "candidates": results}


@mcp.tool()
async def plan_route(
    stops: Annotated[
        list[Stop], Field(min_length=2, max_length=12, description="要经过的地点，2~12 个")
    ],
    mode: Annotated[Mode, Field(description="出行方式：walking 步行 / driving 驾车")] = "walking",
    optimize: Annotated[
        bool, Field(description="true：重新排序使总时间最短；false：按给定顺序")
    ] = True,
) -> dict[str, Any]:
    """规划经过多个地点的路线，给出顺序、每段的距离与时间、总时间。

    - optimize=true 时，第一个点固定为起点，其余点重新排序使总时间最短（不回到起点）
    - 只问「A 到 B 要多久」时，传两个点并设 optimize=false
    - 只支持步行和驾车，不含电车/巴士。某段标记 suggest_transit=true 时，
      说明步行太远，应建议用户改乘公共交通
    - estimated=true 表示路线服务不可用，时间为直线距离估算值，请提醒用户仅供参考
    """
    points = [(s.lat, s.lng) for s in stops]
    durations, distances, estimated = await client.matrix(points, mode)

    if optimize:
        order, method = best_order(durations, start=0)
    else:
        order, method = list(range(len(stops))), "given"

    legs = []
    for a, b in zip(order, order[1:]):
        minutes = durations[a][b] / 60
        legs.append(
            {
                "from": stops[a].name,
                "to": stops[b].name,
                "distance_km": round(distances[a][b] / 1000, 2),
                "duration_min": round(minutes),
                "suggest_transit": mode == "walking" and minutes > TRANSIT_SUGGEST_MIN,
            }
        )

    return {
        "mode": mode,
        "method": method,
        "estimated": estimated,
        # 带上坐标，前端可以直接按顺序在地图上连线
        "stops": [
            {"order": i + 1, "name": stops[idx].name, "lat": stops[idx].lat, "lng": stops[idx].lng}
            for i, idx in enumerate(order)
        ],
        "legs": legs,
        "total_distance_km": round(sum(leg["distance_km"] for leg in legs), 2),
        "total_duration_min": sum(leg["duration_min"] for leg in legs),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
