import asyncio
import unittest
from unittest.mock import patch

from astrbot_plugin_poe1db.wiki import WikiClient


class WikiTests(unittest.TestCase):
    def test_search_parses_titles_and_sanitizes_snippets(self):
        async def scenario():
            client = WikiClient(cache_seconds=0)
            response = {
                "query": {
                    "search": [
                        {"title": "Fireball", "snippet": "A <span>spell</span>."},
                        {"title": "Fireball", "snippet": "Duplicate."},
                    ]
                }
            }
            async def fake_fetch_json(url):
                return response

            with patch.object(client, "_fetch_json", new=fake_fetch_json):
                return await client.search("Fireball")

        pages = asyncio.run(scenario())
        self.assertEqual([page.title for page in pages], ["Fireball"])
        self.assertEqual(pages[0].extract, "A spell.")
        self.assertTrue(pages[0].url.startswith("https://www.poewiki.net/wiki/"))

    def test_page_rejects_external_fullurl(self):
        async def scenario():
            client = WikiClient(cache_seconds=0)
            response = {
                "query": {
                    "pages": [{
                        "title": "Fireball",
                        "fullurl": "https://example.org/steal",
                        "extract": "A fire spell.",
                    }]
                }
            }

            async def fake_fetch_json(url):
                return response

            with patch.object(client, "_fetch_json", new=fake_fetch_json):
                return await client.page("Fireball")

        page = asyncio.run(scenario())
        self.assertIsNotNone(page)
        self.assertEqual(page.extract, "A fire spell.")
        self.assertEqual(page.url, "https://www.poewiki.net/wiki/Fireball")

    def test_endpoint_allowlist(self):
        self.assertTrue(WikiClient.allowed_url("https://www.poewiki.net/w/api.php?action=query"))
        self.assertTrue(WikiClient.allowed_url("https://www.poewiki.net/wiki/Fireball"))
        self.assertFalse(WikiClient.allowed_url("http://www.poewiki.net/w/api.php"))
        self.assertFalse(WikiClient.allowed_url("https://example.org/wiki/Fireball"))


if __name__ == "__main__":
    unittest.main()
