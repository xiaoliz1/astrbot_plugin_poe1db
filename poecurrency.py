"""PoE1 Chinese-realm currency prices from poecurrency.top's public API."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SUMMARY_URL = "https://poecurrency.top/api/summary?version=1"
USER_AGENT = "AstrBot-PoE1DB/0.4.2 (+https://github.com/xiaoliz1/astrbot_plugin_poe1db)"
MAX_RESPONSE_BYTES = 2_500_000
CURRENCY_NAMES = {"c": "混沌石", "e": "崇高石", "d": "神圣石"}


class NationalEconomyError(RuntimeError):
    """The Chinese-realm economy service is unavailable or malformed."""


@dataclass(frozen=True)
class NationalCurrencyPrice:
    name: str
    english_name: str
    buy_average: float
    sell_average: float
    currency_unit: str
    updated_at: str
    icon_url: str | None = None


@dataclass(frozen=True)
class NationalPriceSnapshot:
    prices: tuple[NationalCurrencyPrice, ...]
    latest_update: str


def _valid_summary_url(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname == "poecurrency.top"
        and parts.port is None
        and parts.username is None
        and parts.password is None
        and parts.path == "/api/summary"
        and parse_qs(parts.query, keep_blank_values=True) == {"version": ["1"]}
        and not parts.fragment
    )


class _SummaryRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _valid_summary_url(newurl):
            raise NationalEconomyError("国服行情接口跳转到了不受支持的地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) and converted >= 0 else None


def parse_national_summary(payload: object) -> NationalPriceSnapshot:
    if not isinstance(payload, list):
        raise NationalEconomyError("国服行情数据格式不正确")
    category = next(
        (
            value
            for value in payload
            if isinstance(value, dict) and value.get("category_label") == "通货仓库"
        ),
        None,
    )
    rows = category.get("items") if isinstance(category, dict) else None
    if not isinstance(rows, list):
        raise NationalEconomyError("国服行情没有返回通货仓库数据")

    prices: list[NationalCurrencyPrice] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("error") is True:
            continue
        name = row.get("item_name")
        english_name = row.get("engname", "")
        unit = row.get("currency_unit")
        buy_average = _number(row.get("buy_avg"))
        sell_average = _number(row.get("sell_avg"))
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(english_name, str)
            or not isinstance(unit, str)
            or unit not in CURRENCY_NAMES
            or buy_average is None
            or sell_average is None
            or max(buy_average, sell_average) <= 0
        ):
            continue
        updated_at = row.get("latest_datetime", "")
        icon_url = row.get("item_icon")
        prices.append(
            NationalCurrencyPrice(
                name=name.strip(),
                english_name=english_name.strip(),
                buy_average=buy_average,
                sell_average=sell_average,
                currency_unit=unit,
                updated_at=updated_at.strip() if isinstance(updated_at, str) else "",
                icon_url=(
                    icon_url.strip()
                    if isinstance(icon_url, str) and len(icon_url.strip()) <= 2048
                    else None
                ),
            )
        )
    if not prices:
        raise NationalEconomyError("当前赛季暂时没有可用的国服通货价格")
    latest_update = max((price.updated_at for price in prices if price.updated_at), default="")
    return NationalPriceSnapshot(tuple(prices), latest_update)


class NationalEconomyClient:
    def __init__(self, timeout_seconds: int = 15, cache_seconds: int = 3600):
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, NationalPriceSnapshot] | None = None
        self._lock = asyncio.Lock()

    def invalidate_cache(self) -> None:
        """Expire the cached snapshot so manual/hourly refreshes fetch fresh data."""
        if self._cache is not None:
            self._cache = (0.0, self._cache[1])

    def _download(self) -> object:
        if not _valid_summary_url(SUMMARY_URL):
            raise NationalEconomyError("国服行情接口地址校验失败")
        request = Request(
            SUMMARY_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with build_opener(_SummaryRedirects()).open(
                request, timeout=self.timeout_seconds
            ) as response:
                response_url = response.geturl()
                if not _valid_summary_url(response_url):
                    raise NationalEconomyError("国服行情响应来自非预期地址")
                if response.headers.get_content_type() not in ("application/json", "text/plain"):
                    raise NationalEconomyError("国服行情接口返回了非 JSON 数据")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise NationalEconomyError(f"国服行情接口返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise NationalEconomyError("连接 poecurrency.top 失败或超时") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise NationalEconomyError("国服行情响应超过安全读取上限")
        try:
            return json.loads(payload.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise NationalEconomyError("国服行情接口没有返回有效 JSON") from exc

    async def currency_snapshot(self) -> NationalPriceSnapshot:
        cached = self._cache
        if cached and cached[0] > time.monotonic():
            return cached[1]
        async with self._lock:
            cached = self._cache
            if cached and cached[0] > time.monotonic():
                return cached[1]
            payload = await asyncio.to_thread(self._download)
            snapshot = parse_national_summary(payload)
            if self.cache_seconds > 0:
                self._cache = (time.monotonic() + self.cache_seconds, snapshot)
            return snapshot
