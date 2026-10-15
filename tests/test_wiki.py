import asyncio
import unittest
from unittest.mock import patch

from astrbot_plugin_poe1db.wiki import WikiClient, WikiPage


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

    def test_first_image_uses_matching_wiki_icon(self):
        async def scenario():
            client = WikiClient(cache_seconds=0)
            pages = [
                WikiPage("Fireball", "https://www.poewiki.net/wiki/Fireball", ""),
                WikiPage("Fireball Support", "https://www.poewiki.net/wiki/Fireball_Support", ""),
            ]

            async def fake_thumbnails(titles):
                if titles == ["Fireball"]:
                    return {"fireball": "https://www.poewiki.net/images/2/27/Fireball_skill_icon.png"}
                return {}

            with patch.object(client, "_thumbnail_urls", new=fake_thumbnails):
                return await client.first_image(pages)

        self.assertEqual(
            asyncio.run(scenario()),
            "https://www.poewiki.net/images/2/27/Fireball_skill_icon.png",
        )

    def test_page_rejects_external_fullurl(self):
        async def scenario():
            client = WikiClient(cache_seconds=0)
            response = {
                "query": {
                    "pages": [{
                        "title": "Fireball",
                        "fullurl": "https://example.org/steal",
                        "extract": "A fire spell.",
                        "thumbnail": {
                            "source": "https://www.poewiki.net/images/2/27/Fireball_skill_icon.png"
                        },
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
        self.assertIsNotNone(page.image_url)

    def test_endpoint_allowlist(self):
        self.assertTrue(WikiClient.allowed_url("https://www.poewiki.net/w/api.php?action=query"))
        self.assertTrue(WikiClient.allowed_url("https://www.poewiki.net/wiki/Fireball"))
        self.assertFalse(WikiClient.allowed_url("http://www.poewiki.net/w/api.php"))
        self.assertFalse(WikiClient.allowed_url("https://example.org/wiki/Fireball"))

    def test_image_allowlist_rejects_external_hosts_and_query_urls(self):
        self.assertTrue(
            WikiClient.allowed_image_url(
                "https://www.poewiki.net/images/2/27/Fireball_skill_icon.png"
            )
        )
        self.assertFalse(
            WikiClient.allowed_image_url("https://example.org/images/fireball.png")
        )
        self.assertFalse(
            WikiClient.allowed_image_url("https://www.poewiki.net/images/fireball.png?next=https://evil.example")
        )


if __name__ == "__main__":
    unittest.main()
