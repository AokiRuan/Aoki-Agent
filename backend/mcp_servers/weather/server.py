"""天气 MCP Server。讲解见 docs/04-external-mcp-servers.md。

包装 Open-Meteo 的逐日预报。以模块方式启动：

    python -m backend.mcp_servers.weather.server

stdio 模式下 stdout 是 JSON-RPC 通道，禁止 print。
"""
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .client import MAX_FORECAST_DAYS, WeatherClient

mcp = MCPServer("weather")

# 模块级变量，测试时用 monkeypatch 替换成注入了 MockTransport 的实例
client = WeatherClient()


@mcp.tool()
async def get_weather_forecast(
    lat: Annotated[float, Field(ge=-90, le=90, description="纬度")],
    lng: Annotated[float, Field(ge=-180, le=180, description="经度")],
    days: Annotated[
        int, Field(ge=1, le=MAX_FORECAST_DAYS, description="预报天数，从今天算起")
    ] = 7,
) -> dict[str, Any]:
    """查询某地未来几天的逐日天气预报（最多 16 天）。

    返回每天的日期、星期、天气描述、最高/最低气温、降水概率、降水量、最大风速。
    结果中的 today 是当地的「今天」，可据此判断「明天」「这周末」对应哪几天。
    lat/lng 可以直接用 list_spots 返回的圣地坐标，或 geocode 查到的坐标。
    """
    try:
        return await client.get_daily_forecast(lat, lng, days)
    except httpx.HTTPStatusError as e:
        return {"error": f"天气服务返回错误状态码 {e.response.status_code}"}
    except httpx.HTTPError as e:
        # 超时、连不上等网络问题：告诉 LLM 服务不可用，让它如实转告用户
        return {"error": f"天气服务暂时不可用（{type(e).__name__}），请稍后再试"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
