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
USER_AGENT = "AstrBot-PoE1DB/0.1.0 (+https://github.com/xiaoliz1)"
MAX_RESPONSE_BYTES = 2_500_000


class EconomyError(RuntimeError):
    """The public PoE 1 economy API is unavailable or malformed."""


@dataclass(frozen=True)
class CurrencyPrice:
    name: str
    chaos_value: float


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
        self._lock = asyncio.Lock()

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
        async with self._lock:
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

    async def currency_snapshot(self) -> PriceSnapshot:
        league = await self.current_league()
        prices: dict[str, float] = {}
        for category in ("Currency", "Fragment"):
            query = urlencode({"league": league, "type": category})
            payload = await self._fetch_json(
                f"{BASE_URL}/stash/current/currency/overview?{query}"
            )
            if not isinstance(payload, dict):
                continue
            rows = payload.get("lines")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("currencyTypeName")
                value = row.get("chaosEquivalent")
                if (
                    isinstance(name, str)
                    and name.strip()
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    and float(value) > 0
                ):
                    prices[name.strip()] = float(value)
        if not prices:
            raise EconomyError("当前赛季暂时没有可用的通货价格")
        sorted_prices = tuple(
            CurrencyPrice(name, value)
            for name, value in sorted(prices.items(), key=lambda pair: (-pair[1], pair[0]))
        )
        return PriceSnapshot(league=league, prices=sorted_prices)
