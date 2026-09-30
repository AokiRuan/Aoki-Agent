"""Open-Meteo 天气预报客户端。讲解见 docs/04-external-mcp-servers.md。

Open-Meteo 免费、无需 API key，覆盖日本。本文件分两层：
- WeatherClient：负责发 HTTP 请求（网络层，可注入 transport 以便测试）
- parse_daily：把原始响应转成对 LLM 友好的格式（纯函数，不碰网络）
"""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16
USER_AGENT = "Aoki-Agent/0.1 (learning project; seichi-junrei demo)"

DAILY_FIELDS = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "precipitation_sum",
    "wind_speed_10m_max",
]

# WMO 天气代码 → 中文描述。LLM 看不懂数字代码，直接给描述
WMO_CODES: dict[int, str] = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}

WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class WeatherClient:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        # transport 为 None 时走真实网络；测试时注入 httpx.MockTransport
        self._transport = transport
        self._timeout = timeout

    async def get_daily_forecast(self, lat: float, lng: float, days: int) -> dict[str, Any]:
        params = {
            "latitude": lat,
            "longitude": lng,
            "daily": ",".join(DAILY_FIELDS),
            # auto：按坐标所在地的时区返回日期，日本就是 Asia/Tokyo
            "timezone": "auto",
            "forecast_days": days,
        }
        # 每次调用新建客户端：避免 AsyncClient 绑死在某个事件循环上（见文档「设计取舍」）
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
        ) as http:
            resp = await http.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            return parse_daily(resp.json())


def parse_daily(data: dict[str, Any]) -> dict[str, Any]:
    """把 Open-Meteo 的「按字段分列」格式转成「按天分行」格式。

    原始格式是列式的：{"time": [d1, d2], "temperature_2m_max": [t1, t2], ...}
    LLM 更容易理解行式的：[{"date": d1, "temp_max_c": t1}, ...]
    """
    daily = data["daily"]

    def col(name: str, i: int) -> Any:
        values = daily.get(name) or []
        return values[i] if i < len(values) else None

    days = []
    for i, date_str in enumerate(daily["time"]):
        code = col("weather_code", i)
        days.append(
            {
                "date": date_str,
                # 星期几：让 LLM 能直接判断「这周末」是哪两天
                "weekday": WEEKDAYS_CN[date.fromisoformat(date_str).weekday()],
                "weather": WMO_CODES.get(code, f"未知天气代码 {code}") if code is not None else None,
                "temp_max_c": col("temperature_2m_max", i),
                "temp_min_c": col("temperature_2m_min", i),
                "precipitation_probability_pct": col("precipitation_probability_max", i),
                "precipitation_mm": col("precipitation_sum", i),
                "wind_max_kmh": col("wind_speed_10m_max", i),
            }
        )

    return {
        "timezone": data.get("timezone"),
        "lat": data.get("latitude"),
        "lng": data.get("longitude"),
        # 列表第一天就是当地的「今天」
        "today": days[0]["date"] if days else None,
        "days": days,
    }
