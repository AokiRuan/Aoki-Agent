"""天气 MCP server 测试（不碰网络）。讲解见 docs/04-external-mcp-servers.md。"""
import httpx
import pytest

from backend.mcp_servers.weather import server
from backend.mcp_servers.weather.client import WeatherClient, parse_daily
from backend.tests.stdio_helper import stdio_session

# Open-Meteo 响应的形态：daily 下每个字段是一列
# 2024-01-06 是周六、2024-01-07 是周日
FAKE_RESPONSE = {
    "latitude": 34.875,
    "longitude": 135.8125,
    "timezone": "Asia/Tokyo",
    "daily": {
        "time": ["2024-01-06", "2024-01-07"],
        "weather_code": [3, 61],
        "temperature_2m_max": [9.1, 7.4],
        "temperature_2m_min": [1.5, 2.2],
        "precipitation_probability_max": [10, 80],
        "precipitation_sum": [0.0, 12.4],
        "wind_speed_10m_max": [9.8, 15.1],
    },
}


def use_transport(monkeypatch, handler):
    """把 server 里的 client 换成走 MockTransport 的实例。"""
    monkeypatch.setattr(server, "client", WeatherClient(transport=httpx.MockTransport(handler)))


def test_parse_daily_turns_columns_into_rows():
    out = parse_daily(FAKE_RESPONSE)
    assert out["today"] == "2024-01-06"
    assert out["timezone"] == "Asia/Tokyo"
    sat, sun = out["days"]
    assert sat["weekday"] == "周六" and sun["weekday"] == "周日"
    assert sat["weather"] == "阴" and sun["weather"] == "小雨"
    assert sun["precipitation_probability_pct"] == 80


def test_parse_daily_tolerates_missing_columns_and_unknown_codes():
    data = {"daily": {"time": ["2024-01-06"], "weather_code": [1234]}}
    day = parse_daily(data)["days"][0]
    assert day["weather"] == "未知天气代码 1234"
    assert day["temp_max_c"] is None


async def test_tool_sends_expected_query(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json=FAKE_RESPONSE)

    use_transport(monkeypatch, handler)
    out = await server.get_weather_forecast(lat=34.89, lng=135.81, days=2)

    assert out["days"][1]["weather"] == "小雨"
    assert seen["latitude"] == "34.89" and seen["longitude"] == "135.81"
    assert seen["forecast_days"] == "2"
    assert seen["timezone"] == "auto"
    assert seen["ua"].startswith("Aoki-Agent")


async def test_network_failure_returns_error_not_raise(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    use_transport(monkeypatch, handler)
    out = await server.get_weather_forecast(lat=34.89, lng=135.81)
    assert "error" in out and "ConnectError" in out["error"]


async def test_http_error_status_returns_error(monkeypatch):
    use_transport(monkeypatch, lambda request: httpx.Response(503))
    out = await server.get_weather_forecast(lat=34.89, lng=135.81)
    assert "503" in out["error"]


async def test_schema_exposes_constraints_to_llm():
    tool = {t.name: t for t in await server.mcp.list_tools()}["get_weather_forecast"]
    props = tool.input_schema["properties"]
    assert props["days"]["maximum"] == 16 and props["days"]["minimum"] == 1
    assert props["lat"]["minimum"] == -90
    assert tool.input_schema["required"] == ["lat", "lng"]


async def test_out_of_range_args_rejected_before_network():
    with pytest.raises(Exception, match="less than or equal to 16"):
        await server.mcp.call_tool("get_weather_forecast", {"lat": 35, "lng": 135, "days": 30})


async def test_stdio_server_starts():
    async with stdio_session("backend.mcp_servers.weather.server") as session:
        tools = await session.list_tools()
    assert [t.name for t in tools.tools] == ["get_weather_forecast"]
