"""路线 MCP server 测试（不碰网络）。讲解见 docs/04-external-mcp-servers.md。"""
import httpx
import pytest

from backend.mcp_servers.route import server
from backend.mcp_servers.route.client import (
    RouteClient,
    best_order,
    haversine_km,
)
from backend.mcp_servers.route.server import Stop
from backend.tests.stdio_helper import stdio_session


def use_transport(monkeypatch, handler):
    client = RouteClient(transport=httpx.MockTransport(handler), geocode_interval=0)
    monkeypatch.setattr(server, "client", client)
    return client


def line_matrix(positions):
    """点排在一条直线上，时间 = 位置差。方便手算最优顺序。"""
    return [[abs(a - b) * 60.0 for b in positions] for a in positions]


# ---------------------------------------------------------------- 纯函数

def test_haversine_one_degree_latitude_is_about_111km():
    assert haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.01)


def test_best_order_exact_finds_optimal_path():
    # 点 0..3 分别位于 0, 3, 1, 2。从 0 出发的最优顺序：0 → 2(1) → 3(2) → 1(3)
    order, method = best_order(line_matrix([0, 3, 1, 2]), start=0)
    assert order == [0, 2, 3, 1]
    assert method == "exact"


def test_best_order_falls_back_to_heuristic_for_many_stops():
    positions = [0, 9, 1, 8, 2, 7, 3, 6, 4, 5]  # 10 个点，超过穷举上限
    order, method = best_order(line_matrix(positions), start=0)
    assert method == "nearest_neighbor"
    assert [positions[i] for i in order] == list(range(10))


# ---------------------------------------------------------------- plan_route

STOPS = [
    Stop(name="A", lat=35.0, lng=135.0),
    Stop(name="B", lat=35.0, lng=135.3),  # 远
    Stop(name="C", lat=35.0, lng=135.1),  # 近
]


def fake_table(positions):
    dur = line_matrix(positions)
    return {"code": "Ok", "durations": dur, "distances": [[d * 10 for d in row] for row in dur]}


async def test_plan_route_optimizes_and_sends_lng_lat(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=fake_table([0, 3, 1]))

    use_transport(monkeypatch, handler)
    out = await server.plan_route(stops=STOPS, mode="walking")

    # OSRM 要「经度,纬度」——顺序写反是最常见的 bug
    assert seen["path"].endswith("/table/v1/driving/135.0,35.0;135.3,35.0;135.1,35.0")
    assert seen["path"].startswith("/routed-foot/")
    assert seen["params"]["annotations"] == "duration,distance"

    assert [s["name"] for s in out["stops"]] == ["A", "C", "B"]
    assert out["method"] == "exact" and out["estimated"] is False
    assert [leg["duration_min"] for leg in out["legs"]] == [1, 2]
    assert out["total_duration_min"] == 3


async def test_plan_route_keeps_given_order(monkeypatch):
    use_transport(monkeypatch, lambda r: httpx.Response(200, json=fake_table([0, 3, 1])))
    out = await server.plan_route(stops=STOPS, optimize=False)
    assert [s["name"] for s in out["stops"]] == ["A", "B", "C"]
    assert out["method"] == "given"


async def test_driving_uses_car_profile(monkeypatch):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json=fake_table([0, 3, 1]))

    use_transport(monkeypatch, handler)
    await server.plan_route(stops=STOPS, mode="driving")
    assert seen["path"].startswith("/routed-car/")


async def test_osrm_down_degrades_to_estimate(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("unreachable", request=request)

    use_transport(monkeypatch, handler)
    out = await server.plan_route(stops=STOPS)

    assert out["estimated"] is True
    # 估算依然给出合理的顺序：A → C（近）→ B（远）
    assert [s["name"] for s in out["stops"]] == ["A", "C", "B"]
    assert all(leg["duration_min"] > 0 for leg in out["legs"])


async def test_unreachable_pair_is_patched_with_estimate(monkeypatch):
    table = fake_table([0, 3, 1])
    table["durations"][0][2] = None
    use_transport(monkeypatch, lambda r: httpx.Response(200, json=table))
    out = await server.plan_route(stops=STOPS)
    assert out["estimated"] is True


async def test_long_walk_suggests_transit(monkeypatch):
    far = [Stop(name="东京", lat=35.68, lng=139.77), Stop(name="镰仓", lat=35.31, lng=139.49)]
    table = {"code": "Ok", "durations": [[0, 36000], [36000, 0]], "distances": [[0, 50000], [50000, 0]]}
    use_transport(monkeypatch, lambda r: httpx.Response(200, json=table))
    out = await server.plan_route(stops=far, mode="walking", optimize=False)
    assert out["legs"][0]["suggest_transit"] is True


async def test_plan_route_schema_and_validation():
    tool = {t.name: t for t in await server.mcp.list_tools()}["plan_route"]
    schema = tool.input_schema
    assert schema["properties"]["stops"]["minItems"] == 2
    assert schema["properties"]["mode"]["enum"] == ["walking", "driving"]

    with pytest.raises(Exception, match="at least 2"):
        await server.mcp.call_tool("plan_route", {"stops": [{"name": "A", "lat": 35, "lng": 135}]})


# ---------------------------------------------------------------- geocode

NOMINATIM_RESPONSE = [
    {
        "name": "京都駅",
        "display_name": "京都駅, 烏丸通, 下京区, 京都市, 日本",
        "lat": "34.9858",
        "lon": "135.7588",
        "type": "station",
    }
]


async def test_geocode_converts_string_coords_and_caches(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.params["q"])
        return httpx.Response(200, json=NOMINATIM_RESPONSE)

    use_transport(monkeypatch, handler)
    first = await server.geocode("京都駅")
    second = await server.geocode("京都駅")

    cand = first["candidates"][0]
    assert cand == {
        "name": "京都駅",
        "address": "京都駅, 烏丸通, 下京区, 京都市, 日本",
        "lat": 34.9858,
        "lng": 135.7588,
        "type": "station",
    }
    assert second == first
    assert calls == ["京都駅"]  # 第二次命中缓存，没有发请求


async def test_geocode_no_result(monkeypatch):
    use_transport(monkeypatch, lambda r: httpx.Response(200, json=[]))
    out = await server.geocode("不存在的地方")
    assert "找不到" in out["error"]


async def test_geocode_service_down(monkeypatch):
    use_transport(monkeypatch, lambda r: httpx.Response(429))
    out = await server.geocode("京都駅")
    assert "error" in out


async def test_stdio_server_starts():
    async with stdio_session("backend.mcp_servers.route.server") as session:
        tools = await session.list_tools()
    assert sorted(t.name for t in tools.tools) == ["geocode", "plan_route"]
