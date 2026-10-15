"""PoE 1 economy access through poe.ninja's documented public API."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://poe.ninja/poe1/api/economy"
USER_AGENT = "AstrBot-PoE1DB/0.4.5 (+https://github.com/xiaoliz1/astrbot_plugin_poe1db)"
MAX_RESPONSE_BYTES = 2_500_000

ITEM_CATEGORIES = {
    "Wombgift": "胎礼",
    "Corpse": "尸体",
    "Incubator": "孵化器",
    "UniqueWeapon": "传奇武器",
    "UniqueArmour": "传奇护甲",
    "UniqueAccessory": "传奇饰品",
    "UniqueFlask": "传奇药剂",
    "UniqueJewel": "传奇珠宝",
    "ForbiddenJewel": "禁断珠宝",
    "ShrineBelt": "神龛腰带",
    "UniqueTincture": "传奇滴剂",
    "UniqueRelic": "传奇遗物",
    "SkillGem": "技能宝石",
    "ImbuedGem": "灌注宝石",
    "ClusterJewel": "星团珠宝",
    "Map": "地图",
    "BlightedMap": "凋落地图",
    "BlightRavagedMap": "凋落蔓延地图",
    "UniqueMap": "传奇地图",
    "ValdoMap": "瓦尔多地图",
    "Invitation": "邀请",
    "Memory": "记忆",
    "IncursionTemple": "神庙",
    "ScryingOrb": "预言之镜",
    "BaseType": "基底",
    "Flask": "药剂",
    "Beast": "野兽",
    "Vial": "圣物瓶",
}


class EconomyError(RuntimeError):
    """The public PoE 1 economy API is unavailable or malformed."""


@dataclass(frozen=True)
class CurrencyPrice:
    name: str
    chaos_value: float
    icon_url: str | None = None
    category: str = "通货"
    change_percent: float | None = None
    trend: tuple[float, ...] = ()
    divine_value: float | None = None


@dataclass(frozen=True)
class PriceSnapshot:
    league: str
    prices: tuple[CurrencyPrice, ...]


def _cache_ttl(headers, fallback: int) -> int:
    directives = str(headers.get("Cache-Control", "")).casefold()
    if "no-store" in directives:
        return -1
    if "no-cache" in directives:
        return 0
    match = re.search(r"(?:^|,)\s*max-age=(\d+)", directives)
    if not match:
        return max(0, fallback)
    return min(max(0, fallback), int(match.group(1)))


class _EconomyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if (
            parts.scheme != "https"
            or parts.hostname != "poe.ninja"
            or parts.port is not None
            or parts.username is not None
            or parts.password is not None
            or not parts.path.startswith("/poe1/api/economy/")
        ):
            raise EconomyError("poe.ninja 将请求跳转到了不受支持的地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class EconomyClient:
    def __init__(self, timeout_seconds: int = 15, cache_seconds: int = 300):
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, object, str | None]] = {}
        self._url_locks: dict[str, asyncio.Lock] = {}

    def invalidate_cache(self) -> None:
        """Expire cached responses while retaining ETags for conditional refreshes."""
        for url, (_, payload, etag) in tuple(self._cache.items()):
            self._cache[url] = (0.0, payload, etag)

    def _download_json(
        self, url: str, etag: str | None
    ) -> tuple[object | None, int, str | None, bool]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        request = Request(
            url,
            headers=headers,
        )
        try:
            with build_opener(_EconomyRedirects()).open(
                request, timeout=self.timeout_seconds
            ) as response:
                if urlsplit(response.geturl()).hostname != "poe.ninja":
                    raise EconomyError("poe.ninja 响应跳转到了非预期站点")
                if response.headers.get_content_type() not in ("application/json", "text/plain"):
                    raise EconomyError("poe.ninja 返回了非 JSON 数据")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                ttl = _cache_ttl(response.headers, self.cache_seconds)
                response_etag = response.headers.get("ETag") or etag
        except HTTPError as exc:
            if exc.code == 304 and etag:
                return None, _cache_ttl(exc.headers, self.cache_seconds), etag, True
            raise EconomyError(f"poe.ninja 返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise EconomyError("连接 poe.ninja 经济接口失败或超时") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise EconomyError("poe.ninja 响应超过安全读取上限")
        try:
            value = json.loads(payload.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise EconomyError("poe.ninja 没有返回有效 JSON") from exc
        return value, ttl, response_etag, False

    async def _fetch_json(self, url: str) -> object:
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        lock = self._url_locks.setdefault(url, asyncio.Lock())
        async with lock:
            cached = self._cache.get(url)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            etag = cached[2] if cached else None
            value, ttl, response_etag, not_modified = await asyncio.to_thread(
                self._download_json, url, etag
            )
            if not_modified:
                if cached is None:
                    raise EconomyError("poe.ninja 返回了没有缓存依据的 304 响应")
                value = cached[1]
            if value is None:
                raise EconomyError("poe.ninja 没有返回行情数据")
            if self.cache_seconds > 0:
                if ttl >= 0:
                    self._cache[url] = (time.monotonic() + ttl, value, response_etag)
                    if len(self._cache) > 8:
                        self._cache.pop(next(iter(self._cache)))
                else:
                    self._cache.pop(url, None)
            return value

    async def current_league(self) -> str:
        payload = await self._fetch_json(BASE_URL + "/leagues")
        if not isinstance(payload, list):
            raise EconomyError("poe.ninja 赛季列表格式不正确")
        for league in payload:
            if isinstance(league, dict):
                league_id = league.get("id")
                if isinstance(league_id, str) and league_id.strip() and len(league_id) <= 80:
                    return league_id.strip()
        raise EconomyError("poe.ninja 暂未返回可用赛季")

    async def item_snapshot(self) -> PriceSnapshot:
        league = await self.current_league()
        categories = tuple(ITEM_CATEGORIES)

        async def fetch_category(category: str) -> tuple[str, object | Exception]:
            query = urlencode({"league": league, "type": category})
            url = f"{BASE_URL}/stash/current/item/overview?{query}"
            try:
                return category, await self._fetch_json(url)
            except Exception as exc:
                return category, exc

        # Keep concurrency modest while covering all documented PoE 1 item
        # categories. One unavailable category should not discard the others.
        responses: list[tuple[str, object | Exception]] = []
        for start in range(0, len(categories), 4):
            responses.extend(
                await asyncio.gather(
                    *(fetch_category(category) for category in categories[start : start + 4])
                )
            )

        prices: list[CurrencyPrice] = []
        for category, payload in responses:
            if isinstance(payload, Exception) or not isinstance(payload, dict):
                continue
            rows = payload.get("lines")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("name")
                divine_value = row.get("divineValue")
                chaos_value = row.get("chaosValue")
                icon = row.get("icon")
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or isinstance(divine_value, bool)
                    or not isinstance(divine_value, (int, float))
                    or not math.isfinite(float(divine_value))
                    or float(divine_value) <= 0
                ):
                    continue
                chaos = (
                    float(chaos_value)
                    if isinstance(chaos_value, (int, float))
                    and not isinstance(chaos_value, bool)
                    and math.isfinite(float(chaos_value))
                    and float(chaos_value) >= 0
                    else 0.0
                )
                sparkline = row.get("sparkLine")
                change = None
                trend: tuple[float, ...] = ()
                if isinstance(sparkline, dict):
                    raw_change = sparkline.get("totalChange")
                    if (
                        isinstance(raw_change, (int, float))
                        and not isinstance(raw_change, bool)
                        and math.isfinite(float(raw_change))
                    ):
                        change = float(raw_change)
                    raw_trend = sparkline.get("data")
                    if isinstance(raw_trend, list):
                        trend = tuple(
                            float(point)
                            for point in raw_trend
                            if isinstance(point, (int, float))
                            and not isinstance(point, bool)
                            and math.isfinite(float(point))
                        )
                item = CurrencyPrice(
                    name=name.strip(),
                    chaos_value=chaos,
                    icon_url=icon if isinstance(icon, str) else None,
                    category=ITEM_CATEGORIES[category],
                    change_percent=change,
                    trend=trend,
                    divine_value=float(divine_value),
                )
                prices.append(item)

        if not prices:
            raise EconomyError("当前赛季暂时没有可用的神圣石直接计价物品")
        sorted_prices = tuple(
            sorted(prices, key=lambda price: (-(price.divine_value or 0), price.name.casefold()))
        )
        return PriceSnapshot(league=league, prices=sorted_prices)
