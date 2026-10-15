"""Build-page links for poe.ninja; no unsupported profile API access."""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode


def character_search_url(league: str, character_name: str) -> str:
    league = league.strip()
    character_name = re.sub(r"\s+", " ", character_name).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", league):
        raise ValueError("赛季标识格式不正确")
    if not character_name or len(character_name) > 64:
        raise ValueError("角色名须为 1–64 个字符")
    query = urlencode(
        {"i": "0", "search": f"name={character_name}", "name": character_name}
    )
    return f"https://poe.ninja/poe1/builds/{quote(league, safe='')}?{query}"
