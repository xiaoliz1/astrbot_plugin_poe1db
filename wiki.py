"""Small, cached client for the community-maintained Path of Exile Wiki."""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

API_URL = "https://www.poewiki.net/w/api.php"
PAGE_BASE_URL = "https://www.poewiki.net/wiki/"
USER_AGENT = "AstrBot-PoE1DB/0.1.0 (+https://github.com/xiaoliz1)"
MAX_RESPONSE_BYTES = 2_000_000


class WikiError(RuntimeError):
    """The PoE Wiki could not be queried or returned invalid data."""


@dataclass(frozen=True)
class WikiPage:
    title: str
    url: str
    extract: str


class _SameHostRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not WikiClient.allowed_url(newurl):
            raise WikiError("PoE Wiki 将请求跳转到不受支持的地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WikiClient:
    def __init__(self, timeout_seconds: int = 15, cache_seconds: int = 900):
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, Any]] = {}
        self._semaphore = asyncio.Semaphore(3)

    @staticmethod
    def allowed_url(url: str) -> bool:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        if (
            parts.scheme != "https"
            or parts.hostname != "www.poewiki.net"
            or parts.username is not None
            or parts.password is not None
            or port is not None
        ):
            return False
        if parts.path == "/w/api.php":
            return True
        if not parts.path.startswith("/wiki/") or "\\" in parts.path:
            return False
        return all(part not in ("", ".", "..") for part in parts.path.split("/")[2:])

    def _download_json(self, url: str) -> dict[str, Any]:
        if not self.allowed_url(url):
            raise WikiError("请求地址不在 PoE Wiki 范围内")
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        opener = build_opener(_SameHostRedirects())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                if not self.allowed_url(response.geturl()):
                    raise WikiError("PoE Wiki 跳转到了不受支持的地址")
                if response.headers.get_content_type() not in ("application/json", "text/plain"):
                    raise WikiError("PoE Wiki 返回了非 JSON 数据")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise WikiError(f"PoE Wiki 返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise WikiError("连接 PoE Wiki 失败或超时") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise WikiError("PoE Wiki 响应超过安全读取上限")
        try:
            result = json.loads(payload.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise WikiError("PoE Wiki 没有返回有效 JSON") from exc
        if not isinstance(result, dict) or "error" in result:
            raise WikiError("PoE Wiki API 返回了错误数据")
        return result

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        async with self._semaphore:
            cached = self._cache.get(url)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            payload = await asyncio.to_thread(self._download_json, url)
            if self.cache_seconds > 0:
                self._cache[url] = (time.monotonic() + self.cache_seconds, payload)
                if len(self._cache) > 48:
                    self._cache.pop(next(iter(self._cache)))
            return payload

    async def search(
        self, query: str, limit: int = 5, max_chars: int = 400
    ) -> list[WikiPage]:
        query = re.sub(r"\s+", " ", query).strip()[:120]
        if not query:
            return []
        limit = max(1, min(int(limit), 8))
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": query,
            "srnamespace": "0",
            "srlimit": str(limit),
        }
        payload = await self._fetch_json(API_URL + "?" + urlencode(params))
        pages = (payload.get("query") or {}).get("search") or []
        if not isinstance(pages, list):
            return []
        results: list[WikiPage] = []
        seen: set[str] = set()
        for page in pages:
            if not isinstance(page, dict):
                continue
            title = page.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            url = page.get("fullurl")
            if not isinstance(url, str) or not self._is_page_url(url):
                url = PAGE_BASE_URL + quote(title.replace(" ", "_"), safe="()'")
            snippet = page.get("snippet")
            if not isinstance(snippet, str):
                snippet = ""
            snippet = html.unescape(re.sub(r"<[^>]*>", "", snippet))
            results.append(
                WikiPage(
                    title=re.sub(r"\s+", " ", title).strip()[:160],
                    url=url,
                    extract=re.sub(r"\s+", " ", snippet).strip()[:max_chars],
                )
            )
        return results

    async def page(self, title: str, max_chars: int = 1200) -> WikiPage | None:
        title = re.sub(r"\s+", " ", title).strip()[:160]
        if not title:
            return None
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "extracts|info",
            "titles": title,
            "explaintext": "1",
            "exchars": str(max(1, min(max_chars, 1200))),
            "exlimit": "1",
            "inprop": "url",
        }
        payload = await self._fetch_json(API_URL + "?" + urlencode(params))
        pages = (payload.get("query") or {}).get("pages") or []
        if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
            return None
        result = pages[0]
        actual_title = result.get("title")
        extract = result.get("extract")
        if not isinstance(actual_title, str) or not isinstance(extract, str) or not extract.strip():
            return None
        url = result.get("fullurl")
        if not isinstance(url, str) or not self._is_page_url(url):
            url = PAGE_BASE_URL + quote(actual_title.replace(" ", "_"), safe="()'")
        return WikiPage(
            title=actual_title[:160],
            url=url,
            extract=re.sub(r"\s+", " ", extract).strip()[:max_chars],
        )

    @classmethod
    def _is_page_url(cls, url: str) -> bool:
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        return (
            cls.allowed_url(url)
            and parts.path.startswith("/wiki/")
            and not parts.query
            and not parts.fragment
        )

    @staticmethod
    def search_url(query: str) -> str:
        return "https://www.poewiki.net/index.php?" + urlencode(
            {"search": query, "title": "Special:Search"}
        )
