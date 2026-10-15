"""Resolve public PoE1 character pages from poe.ninja Builds search results."""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode, urlsplit

BASE_URL = "https://poe.ninja/poe1/builds"


class BuildSearchError(RuntimeError):
    """The public Builds page could not be searched with Playwright."""


def league_slug(league: str) -> str:
    league = league.strip()
    if not league or len(league) > 80 or not re.fullmatch(r"[A-Za-z0-9 _-]+", league):
        raise ValueError("赛季标识格式不正确")
    slug = re.sub(r"[^a-z0-9]+", "", league.casefold())
    if not slug:
        raise ValueError("赛季标识格式不正确")
    return slug


def character_search_url(league: str, character_name: str) -> str:
    slug = league_slug(league)
    character_name = re.sub(r"\s+", " ", character_name).strip()
    if not character_name or len(character_name) > 64:
        raise ValueError("角色名须为 1–64 个字符")
    query = urlencode(
        {"i": "0", "search": f"name={character_name}", "name": character_name}
    )
    return f"{BASE_URL}/{quote(slug, safe='')}?{query}"


def extract_character_url(
    league: str, character_name: str, candidate_links: list[object]
) -> str | None:
    """Return a safe detail URL from exact-name matches, or None if ambiguous/missing."""
    slug = league_slug(league)
    expected = re.sub(r"\s+", " ", character_name).strip().casefold()
    prefix = f"/poe1/builds/{slug}/character/"
    matches: list[str] = []
    for candidate in candidate_links:
        if not isinstance(candidate, dict):
            continue
        found_name = candidate.get("name")
        href = candidate.get("href")
        if (
            not isinstance(found_name, str)
            or re.sub(r"\s+", " ", found_name).strip().casefold() != expected
            or not isinstance(href, str)
        ):
            continue
        parts = urlsplit(href)
        if (
            parts.scheme != "https"
            or parts.hostname != "poe.ninja"
            or parts.port is not None
            or parts.username is not None
            or parts.password is not None
            or not parts.path.startswith(prefix)
        ):
            continue
        matches.append(href)
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


async def find_character_url(
    league: str, character_name: str, timeout_seconds: int = 20
) -> str | None:
    """Open the public search page and read the exact character's detail link.

    Returns None when no unique exact match is listed.
    """
    character_name = re.sub(r"\s+", " ", character_name).strip()
    search_url = character_search_url(league, character_name)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BuildSearchError("未安装 Playwright") from exc

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = await browser.new_page()
                await page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_seconds * 1000,
                )
                await page.locator('input[placeholder="Name"]').wait_for(
                    state="visible", timeout=timeout_seconds * 1000
                )
                await page.wait_for_function(
                    r"""(name) => {
                      const input = document.querySelector('input[placeholder="Name"]');
                      return input?.value === name && /Found\s+\d+\s+characters?/i.test(document.body.innerText);
                    }""",
                    arg=character_name,
                    timeout=timeout_seconds * 1000,
                )
                candidate_links = await page.locator("a").evaluate_all(
                    """(anchors, name) => anchors
                      .map(a => ({name: (a.textContent || '').trim(), href: a.href}))""",
                    character_name,
                )
                return extract_character_url(league, character_name, candidate_links)
            finally:
                await browser.close()
    except BuildSearchError:
        raise
    except Exception as exc:
        raise BuildSearchError("打开或读取 poe.ninja Builds 搜索页失败") from exc
