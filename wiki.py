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
from urllib.parse import quote, unquote, urlencode, urlsplit
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
    image_url: str | None = None


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

    async def first_image(self, pages: list[WikiPage]) -> str | None:
        """Return the first safe article icon available for a search result list."""
        for page in pages[:8]:
            try:
                image_url = (await self._thumbnail_urls([page.title])).get(page.title.casefold())
            except WikiError:
                continue
            if image_url and self.allowed_image_url(image_url):
                return image_url
        return None

    async def _thumbnail_urls(self, titles: list[str]) -> dict[str, str]:
        safe_titles = [
            re.sub(r"\s+", " ", title).strip()[:160]
            for title in titles[:8]
            if isinstance(title, str) and title.strip() and "|" not in title
        ]
        if not safe_titles:
            return {}
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "pageimages|images",
            "titles": "|".join(safe_titles),
            "piprop": "thumbnail",
            "pithumbsize": "400",
            "imlimit": "50",
        }
        payload = await self._fetch_json(API_URL + "?" + urlencode(params))
        pages = (payload.get("query") or {}).get("pages") or []
        if not isinstance(pages, list):
            return {}
        image_urls: dict[str, str] = {}
        file_to_page: dict[str, str] = {}
        file_titles: dict[str, str] = {}
        for page in pages:
            if not isinstance(page, dict):
                continue
            title = page.get("title")
            thumbnail = page.get("thumbnail")
            source = thumbnail.get("source") if isinstance(thumbnail, dict) else None
            if not isinstance(title, str):
                continue
            if isinstance(source, str) and self.allowed_image_url(source):
                image_urls[title.casefold()] = source
                continue

            target_name = re.sub(r"[^a-z0-9]", "", title.casefold())
            images = page.get("images")
            candidates: list[tuple[int, str]] = []
            if isinstance(images, list):
                for image in images:
                    file_title = image.get("title") if isinstance(image, dict) else None
                    if not isinstance(file_title, str) or not file_title.startswith("File:") or "|" in file_title:
                        continue
                    filename = file_title[5:].rsplit(".", 1)[0]
                    normalized_filename = re.sub(r"[^a-z0-9]", "", filename.casefold())
                    if not normalized_filename.startswith(target_name):
                        continue
                    if "skillicon" in normalized_filename:
                        priority = 0
                    elif "inventoryicon" in normalized_filename:
                        priority = 1
                    elif "icon" in normalized_filename:
                        priority = 2
                    else:
                        priority = 3
                    candidates.append((priority, file_title))
            if candidates:
                _, selected_file = min(candidates)
                file_to_page[selected_file.casefold()] = title.casefold()
                file_titles[selected_file.casefold()] = selected_file

        if file_to_page:
            info_params = {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "imageinfo",
                "titles": "|".join(file_titles.values()),
                "iiprop": "url",
                "iiurlwidth": "400",
            }
            info_payload = await self._fetch_json(API_URL + "?" + urlencode(info_params))
            info_pages = (info_payload.get("query") or {}).get("pages") or []
            if isinstance(info_pages, list):
                for page in info_pages:
                    if not isinstance(page, dict):
                        continue
                    file_title = page.get("title")
                    infos = page.get("imageinfo")
                    info = infos[0] if isinstance(infos, list) and infos else None
                    source = (
                        info.get("thumburl") or info.get("url")
                        if isinstance(info, dict)
                        else None
                    )
                    target_page = file_to_page.get(file_title.casefold()) if isinstance(file_title, str) else None
                    if target_page and isinstance(source, str) and self.allowed_image_url(source):
                        image_urls[target_page] = source
        return image_urls

    async def page(self, title: str, max_chars: int = 1200) -> WikiPage | None:
        title = re.sub(r"\s+", " ", title).strip()[:160]
        if not title:
            return None
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "extracts|info|pageimages",
            "titles": title,
            "explaintext": "1",
            "exchars": str(max(1, min(max_chars, 1200))),
            "exlimit": "1",
            "inprop": "url",
            "piprop": "thumbnail",
            "pithumbsize": "400",
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
        thumbnail = result.get("thumbnail")
        image_url = thumbnail.get("source") if isinstance(thumbnail, dict) else None
        if not self.allowed_image_url(image_url):
            try:
                image_url = (await self._thumbnail_urls([actual_title])).get(actual_title.casefold())
            except WikiError:
                image_url = None
        return WikiPage(
            title=actual_title[:160],
            url=url,
            extract=re.sub(r"\s+", " ", extract).strip()[:max_chars],
            image_url=image_url if self.allowed_image_url(image_url) else None,
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
    def allowed_image_url(url: object) -> bool:
        if not isinstance(url, str) or not url or "\\" in url:
            return False
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
            or parts.query
            or parts.fragment
            or not parts.path.startswith("/images/")
        ):
            return False
        return all(
            part not in ("", ".", "..")
            for part in map(unquote, parts.path.split("/")[2:])
        )

    @staticmethod
    def search_url(query: str) -> str:
        return "https://www.poewiki.net/index.php?" + urlencode(
            {"search": query, "title": "Special:Search"}
        )
