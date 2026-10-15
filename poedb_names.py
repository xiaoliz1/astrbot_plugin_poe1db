"""Cached Simplified-Chinese item names from PoEDB pages."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

BASE_URL = "https://poedb.tw/cn/"
USER_AGENT = "AstrBot-PoE1DB/0.4.5 (+https://github.com/xiaoliz1/astrbot_plugin_poe1db)"
MAX_RESPONSE_BYTES = 1_500_000
CACHE_VERSION = 1
CACHE_MAX_ENTRIES = 1_000
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
NEGATIVE_CACHE_TTL_SECONDS = 12 * 60 * 60
LOCALIZED_FALLBACKS = {
    # These generated Valdo-map rewards have no dedicated localized item page on PoEDB.
    "secludedziggurat": "幽隐金字塔",
    "forgottenpool": "遗忘之池",
    "ancestralrefuge": "先祖庇护所",
    "destinylake": "命运之湖",
    "hiddencorridors": "隐秘回廊",
    "ancestralrealm": "先祖领域",
    "ghastlyfrontier": "幽怖边境",
    "tempestuouspanorama": "风暴全景",
    "demoncrate": "恶魔宝箱",
    "cursededge": "诅咒之境",
    "destitutecrossroads": "荒芜十字路口",
    "menacingcrown": "威胁之冠",
    "wraithrealm": "幽魂领域",
    "anguishnexus": "苦痛枢纽",
    "buriedslough": "埋葬沼泽",
    "cyclopeantrap": "独眼巨人陷阱",
    "forsakentrap": "遗弃陷阱",
    "10increasedliferecoveryfromflasks10increasedmanarecoveryfromflasks": "药剂生命回复提高 10%，药剂魔力回复提高 10%",
}


def normalize_english_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _has_chinese(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _poedb_slug(name: str) -> str | None:
    name = re.sub(r"\s+", "_", name.strip())
    if (
        not name
        or len(name) > 120
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _'’()!.,:&+-]*", name)
    ):
        return None
    return quote(name, safe="_-'()")


class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2", "h3", "h4"} and self._heading_tag is None:
            self._heading_tag = tag
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False
        if self._heading_tag == tag.casefold():
            heading = " ".join("".join(self._heading_parts).split())
            if heading:
                self.headings.append(heading)
            self._heading_tag = None
            self._heading_parts = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if self._heading_tag is not None:
            self._heading_parts.append(data)


def _chinese_page_title(page_html: str, english_name: str) -> str | None:
    parser = _PageTextParser()
    try:
        parser.feed(page_html)
    except Exception:
        return None
    candidate_key = normalize_english_name(english_name)
    page_key = normalize_english_name(" ".join(parser.text_parts))
    if not candidate_key or candidate_key not in page_key:
        return None
    for heading in parser.headings:
        if _has_chinese(heading) and len(heading) <= 120:
            return heading
    title = " ".join("".join(parser.title_parts).split())
    title = title.split(" - ", 1)[0]
    for part in title.split():
        if _has_chinese(part) and len(part) <= 120:
            return part
    return None


class PoEDBNameClient:
    """Resolve up to a price table's missing names and persist the cache."""

    def __init__(
        self,
        cache_path: str | Path,
        timeout_seconds: float = 8,
        max_concurrency: int = 5,
    ):
        self.cache_path = Path(cache_path)
        self.timeout_seconds = timeout_seconds
        self.max_concurrency = max(1, min(max_concurrency, 8))
        self._cache = self._load_cache()
        self._lock = asyncio.Lock()

    def _load_cache(self) -> dict[str, dict[str, object]]:
        try:
            if self.cache_path.stat().st_size > 2_000_000:
                return {}
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            return {}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return {}
        clean: dict[str, dict[str, object]] = {}
        for key, value in list(entries.items())[-CACHE_MAX_ENTRIES:]:
            if (
                isinstance(key, str)
                and 1 <= len(key) <= 120
                and isinstance(value, dict)
                and isinstance(value.get("name"), str)
                and isinstance(value.get("checked_at"), (int, float))
                and math.isfinite(value["checked_at"])
            ):
                clean[key] = {
                    "name": value["name"][:120],
                    "checked_at": float(value["checked_at"]),
                }
        return clean

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            entries = dict(list(self._cache.items())[-CACHE_MAX_ENTRIES:])
            temporary = self.cache_path.with_name(self.cache_path.name + ".tmp")
            temporary.write_text(
                json.dumps(
                    {"version": CACHE_VERSION, "entries": entries},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(self.cache_path)
        except OSError:
            # A cache write failure must not stop price collection or image rendering.
            return

    def _fetch_page_title(self, english_name: str) -> tuple[str | None, bool]:
        slug = _poedb_slug(english_name)
        if not slug:
            return None, True
        url = BASE_URL + slug
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                final = urlsplit(response.geturl())
                if (
                    final.scheme != "https"
                    or final.hostname != "poedb.tw"
                    or not final.path.startswith("/cn/")
                    or final.query
                    or final.fragment
                    or response.headers.get_content_type() != "text/html"
                ):
                    return None, False
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return None, False
        except HTTPError as exc:
            return None, exc.code in (404, 410)
        except (URLError, TimeoutError, OSError):
            return None, False
        page_html = raw.decode("utf-8", errors="replace")
        title = _chinese_page_title(page_html, english_name)
        return title, True

    def _fetch_translation(self, english_name: str) -> tuple[str | None, bool]:
        match = re.match(r"(?i)^Foulborn\s+(.+)$", english_name.strip())
        page_name = match.group(1).strip() if match else english_name.strip()
        title, cacheable = self._fetch_page_title(page_name)
        if title and match:
            title = f"秽生·{title}"
        return title, cacheable

    async def resolve_names(self, names: list[str]) -> dict[str, str]:
        """Return normalized-English-name -> Simplified-Chinese display name."""
        unique: dict[str, str] = {}
        for name in names:
            if isinstance(name, str) and name.strip():
                unique.setdefault(normalize_english_name(name), name.strip())
        unique.pop("", None)
        now = time.time()
        resolved: dict[str, str] = {}
        missing: list[tuple[str, str]] = []
        for key, name in unique.items():
            local_translation = LOCALIZED_FALLBACKS.get(key)
            if local_translation:
                resolved[key] = local_translation
                continue
            cached = self._cache.get(key)
            if cached is None:
                missing.append((key, name))
                continue
            translation = cached.get("name")
            checked_at = cached.get("checked_at")
            ttl = CACHE_TTL_SECONDS if translation else NEGATIVE_CACHE_TTL_SECONDS
            if (
                isinstance(checked_at, (int, float))
                and now - checked_at <= ttl
            ):
                if isinstance(translation, str) and translation:
                    resolved[key] = translation
                continue
            missing.append((key, name))

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def lookup(key: str, name: str) -> tuple[str, str, bool]:
            async with semaphore:
                try:
                    title, cacheable = await asyncio.to_thread(
                        self._fetch_translation, name
                    )
                except Exception:
                    title, cacheable = None, False
                return key, title or "", cacheable

        if missing:
            async with self._lock:
                fetched = await asyncio.gather(
                    *(lookup(key, name) for key, name in missing)
                )
                for key, title, cacheable in fetched:
                    previous = self._cache.get(key)
                    if cacheable:
                        self._cache[key] = {"name": title, "checked_at": now}
                        if title:
                            resolved[key] = title
                    elif previous and isinstance(previous.get("name"), str) and previous["name"]:
                        resolved[key] = previous["name"]
                self._save_cache()
        return resolved
