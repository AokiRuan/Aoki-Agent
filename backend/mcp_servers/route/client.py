"""路线与地理编码客户端。讲解见 docs/04-external-mcp-servers.md。

- OSRM（FOSSGIS 公共实例）：算点与点之间的步行/驾车时间与距离
- Nominatim：地名/车站名 → 坐标

两个都是公益服务，使用政策要求：带可识别的 User-Agent、低频率（Nominatim 明确要求 ≤1 次/秒）。

OSRM 不可用时降级为「直线距离 × 绕路系数 ÷ 平均速度」的估算，并在结果里标注 estimated。
"""
from __future__ import annotations

import asyncio
import math
import time
from itertools import permutations
from typing import Any, Literal

import httpx

USER_AGENT = "Aoki-Agent/0.1 (learning project; seichi-junrei demo)"

Mode = Literal["walking", "driving"]

# FOSSGIS 按 profile 分开部署；URL 里的 /driving/ 段在这种部署下会被忽略，真正决定 profile 的是前缀
OSRM_BASES: dict[str, str] = {
    "walking": "https://routing.openstreetmap.de/routed-foot",
    "driving": "https://routing.openstreetmap.de/routed-car",
}
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# 降级估算用的参数
FALLBACK_SPEED_KMH: dict[str, float] = {"walking": 4.5, "driving": 30.0}
DETOUR_FACTOR = 1.3  # 直线距离 → 实际道路距离的经验系数

# 步行超过这个时间，提示 LLM 建议改乘公共交通
TRANSIT_SUGGEST_MIN = 45

# 穷举最优顺序的上限：(n-1)! 条路线，8 个点是 5040 条，再多就改用启发式
EXACT_ORDER_MAX_STOPS = 8


# ---------------------------------------------------------------- 纯函数

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """球面上两点的直线距离（公里）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_leg(lat1: float, lng1: float, lat2: float, lng2: float, mode: Mode) -> tuple[float, float]:
    """降级估算：返回 (秒, 米)。"""
    km = haversine_km(lat1, lng1, lat2, lng2) * DETOUR_FACTOR
    seconds = km / FALLBACK_SPEED_KMH[mode] * 3600
    return seconds, km * 1000


def path_cost(order: list[int], durations: list[list[float]]) -> float:
    return sum(durations[a][b] for a, b in zip(order, order[1:]))


def best_order(durations: list[list[float]], start: int = 0) -> tuple[list[int], str]:
    """求从 start 出发、经过所有点一次的最短路径（不回到起点）。

    返回 (访问顺序, 方法)。点少时穷举保证最优；点多时用最近邻启发式，快但不保证最优。
    """
    n = len(durations)
    others = [i for i in range(n) if i != start]

    if n <= EXACT_ORDER_MAX_STOPS:
        best = min(permutations(others), key=lambda p: path_cost([start, *p], durations))
        return [start, *best], "exact"

    order, remaining = [start], set(others)
    while remaining:
        here = order[-1]
        nxt = min(remaining, key=lambda j: durations[here][j])
        order.append(nxt)
        remaining.remove(nxt)
    return order, "nearest_neighbor"


# ---------------------------------------------------------------- 网络层

class _Throttle:
    """保证两次请求之间至少间隔 interval 秒。Nominatim 使用政策要求 ≤1 次/秒。"""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delay = self._last + self._interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class RouteClient:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        geocode_interval: float = 1.1,
    ) -> None:
        # transport 为 None 时走真实网络；测试时注入 httpx.MockTransport
        self._transport = transport
        self._timeout = timeout
        self._geocode_throttle = _Throttle(geocode_interval)
        self._geocode_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
        )

    async def matrix(
        self, points: list[tuple[float, float]], mode: Mode
    ) -> tuple[list[list[float]], list[list[float]], bool]:
        """两两之间的 (时间秒矩阵, 距离米矩阵, 是否为估算)。

        一次 OSRM table 请求拿到 n×n 全部结果，比逐对调 route 少 n² 次请求。
        """
        # OSRM 的坐标顺序是「经度,纬度」，和常见的「纬度,经度」相反
        coords = ";".join(f"{lng},{lat}" for lat, lng in points)
        url = f"{OSRM_BASES[mode]}/table/v1/driving/{coords}"
        try:
            async with self._http() as http:
                resp = await http.get(url, params={"annotations": "duration,distance"})
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != "Ok":
                raise ValueError(data.get("message") or data.get("code"))
        except (httpx.HTTPError, ValueError):
            return (*self._estimate_matrix(points, mode), True)

        durations, distances = data["durations"], data["distances"]
        estimated = False
        # 个别点对路网不可达时 OSRM 返回 null，用估算值补上
        for i, (la, lo) in enumerate(points):
            for j, (lb, lob) in enumerate(points):
                if durations[i][j] is None or distances[i][j] is None:
                    durations[i][j], distances[i][j] = estimate_leg(la, lo, lb, lob, mode)
                    estimated = True
        return durations, distances, estimated

    @staticmethod
    def _estimate_matrix(points, mode):
        n = len(points)
        dur = [[0.0] * n for _ in range(n)]
        dist = [[0.0] * n for _ in range(n)]
        for i, (la, lo) in enumerate(points):
            for j, (lb, lob) in enumerate(points):
                if i != j:
                    dur[i][j], dist[i][j] = estimate_leg(la, lo, lb, lob, mode)
        return dur, dist

    async def geocode(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        key = (query, limit)
        if key in self._geocode_cache:
            return self._geocode_cache[key]

        await self._geocode_throttle.wait()
        async with self._http() as http:
            resp = await http.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": limit,
                    "accept-language": "ja,zh",
                },
            )
            resp.raise_for_status()
            raw = resp.json()

        results = [
            {
                "name": r.get("name") or r.get("display_name", "").split(",")[0],
                "address": r.get("display_name"),
                # Nominatim 返回的坐标是字符串，字段名是 lon 而不是 lng
                "lat": float(r["lat"]),
                "lng": float(r["lon"]),
                "type": r.get("type"),
            }
            for r in raw
        ]
        self._geocode_cache[key] = results
        return results
