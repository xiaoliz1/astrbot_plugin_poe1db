import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from astrbot_plugin_poe1db.main import (
    Poe1DBPlugin,
    _ambiguous_wiki_candidates,
    _format_disambiguation_prompt,
)
from astrbot_plugin_poe1db.wiki import WikiPage


class QueryHelperTests(unittest.TestCase):
    def test_similar_titles_require_choice_and_prompt_lists_numbered_options(self):
        pages = [
            WikiPage("Fireball", "https://www.poewiki.net/wiki/Fireball", ""),
            WikiPage("Fireball Support", "https://www.poewiki.net/wiki/Fireball_Support", ""),
            WikiPage("Fireball Totem", "https://www.poewiki.net/wiki/Fireball_Totem", ""),
            WikiPage("Fire Trap", "https://www.poewiki.net/wiki/Fire_Trap", ""),
        ]

        candidates = _ambiguous_wiki_candidates("Fireball", pages)

        self.assertEqual([page.title for page in candidates], ["Fireball", "Fireball Support", "Fireball Totem"])
        prompt = _format_disambiguation_prompt("Fireball", candidates)
        self.assertIn("1. Fireball", prompt)
        self.assertIn("2. Fireball Support", prompt)
        self.assertIn("60 秒", prompt)
        self.assertIn("取消", prompt)

    def test_single_match_does_not_interrupt_answer(self):
        pages = [WikiPage("Fireball", "https://www.poewiki.net/wiki/Fireball", "")]
        self.assertEqual(_ambiguous_wiki_candidates("Fireball", pages), [])

    def test_selected_sources_load_in_query_order_and_respect_limit(self):
        plugin = object.__new__(Poe1DBPlugin)
        pages = [
            WikiPage(f"Page {index}", f"https://www.poewiki.net/wiki/Page_{index}", f"Text {index}")
            for index in range(3)
        ]
        plugin.wiki = SimpleNamespace(page=AsyncMock(side_effect=pages))
        grouped = [(f"term {index}", [page]) for index, page in enumerate(pages)]

        selected = asyncio.run(plugin._load_selected_wiki_pages(grouped, 2))

        self.assertEqual(selected, pages[:2])
        self.assertEqual(plugin.wiki.page.await_count, 2)


if __name__ == "__main__":
    unittest.main()
