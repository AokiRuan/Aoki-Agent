"""打真实外部 API 的集成测试。默认不跑，需要显式：

    python -m pytest -m network

用来确认第三方服务的真实行为和我们的假设一致。讲解见 docs/04-external-mcp-servers.md。
"""
import pytest

from backend.mcp_servers.route import server as route_server
from backend.mcp_servers.route.server import Stop
from backend.mcp_servers.weather import server as weather_server

pytestmark = pytest.mark.network


async def test_real_weather_forecast_for_uji():
    out = await weather_server.get_weather_forecast(lat=34.8918, lng=135.8077, days=3)
    assert "error" not in out, out
    assert out["timezone"] == "Asia/Tokyo"
    assert len(out["days"]) == 3
    assert out["days"][0]["weather"] is not None


async def test_real_walking_route_between_uji_spots():
    stops = [
        Stop(name="京阪宇治駅", lat=34.8932, lng=135.8092),
        Stop(name="宇治橋", lat=34.8918, lng=135.8077),
        Stop(name="大吉山展望台", lat=34.8933, lng=135.8110),
    ]
    out = await route_server.plan_route(stops=stops, mode="walking")
    assert out["estimated"] is False, "OSRM 不可用，走了降级估算"
    assert 0 < out["total_duration_min"] < 120


async def test_real_geocode_kyoto_station():
    out = await route_server.geocode("京都駅")
    assert "error" not in out, out
    cand = out["candidates"][0]
    assert cand["lat"] == pytest.approx(34.985, abs=0.02)
    assert cand["lng"] == pytest.approx(135.758, abs=0.02)
