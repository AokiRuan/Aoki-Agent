"""圣地数据访问层。讲解见 docs/03-mcp-server.md。

把「数据从哪来」和「MCP 工具怎么用」隔开：server.py 只依赖 SeichiRepository 接口，
将来 Anitabi 解封换成 AnitabiRepository 时，server.py 一行不用改。

当前用 MockRepository —— Anitabi 被 Cloudflare 拦截，且线上 API 已不再返回
地标级 geo（实测 0/84），接真实 API 时需要额外解决坐标补全。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).parent / "data" / "mock_spots.json"


class SeichiRepository(ABC):
    @abstractmethod
    def search_anime(self, title: str, limit: int = 5) -> list[dict[str, Any]]:
        """按标题模糊搜索作品。"""

    @abstractmethod
    def list_spots(self, anime_id: int) -> list[dict[str, Any]]:
        """列出某作品的全部圣地。"""

    @abstractmethod
    def get_spot(self, spot_id: str) -> dict[str, Any] | None:
        """单个圣地详情。"""


class MockRepository(SeichiRepository):
    """读本地 JSON。零网络依赖，演示不会因为限流翻车。"""

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self._data_file = data_file

    @property
    def _anime(self) -> list[dict[str, Any]]:
        return _load(self._data_file)["anime"]

    def search_anime(self, title: str, limit: int = 5) -> list[dict[str, Any]]:
        q = title.strip().lower()
        if not q:
            return []
        hits = []
        for a in self._anime:
            haystack = " ".join(
                str(a.get(k, "")) for k in ("cn", "title", "city")
            ).lower()
            if q in haystack:
                hits.append(_anime_brief(a))
            if len(hits) >= limit:
                break
        return hits

    def list_spots(self, anime_id: int) -> list[dict[str, Any]]:
        for a in self._anime:
            if a["id"] == anime_id:
                return [_spot_out(p, a) for p in a["points"]]
        return []

    def get_spot(self, spot_id: str) -> dict[str, Any] | None:
        for a in self._anime:
            for p in a["points"]:
                if p["id"] == spot_id:
                    return _spot_out(p, a)
        return None


@lru_cache(maxsize=1)
def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _anime_brief(a: dict[str, Any]) -> dict[str, Any]:
    """作品摘要。不含 points，避免一次塞爆 LLM 上下文。"""
    return {
        "anime_id": a["id"],
        "title_cn": a.get("cn"),
        "title_ja": a.get("title"),
        "city": a.get("city"),
        "cover": a.get("cover"),
        "center": a.get("geo"),
        "spots_count": len(a.get("points", [])),
    }


def _spot_out(p: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    """地标输出格式。字段名对 LLM 友好，geo 拆成 lat/lng 便于前端直接打点。"""
    geo = p.get("geo") or [None, None]
    return {
        "spot_id": p["id"],
        "name_ja": p.get("name"),
        "name_cn": p.get("cn"),
        "lat": geo[0],
        "lng": geo[1],
        "episode": p.get("ep"),
        "timestamp_sec": p.get("s"),
        "image": p.get("image"),
        "anime_id": a["id"],
        "anime_title": a.get("cn") or a.get("title"),
        "city": a.get("city"),
        # 展示时需标注来源并支持跳转（Anitabi 数据遵循 CC BY-NC-SA 4.0）
        "origin": p.get("origin"),
        "origin_url": p.get("originURL"),
    }


def get_repository() -> SeichiRepository:
    """当前使用的数据源。Anitabi 解封后在这里切换实现。"""
    return MockRepository()
