import unittest
from urllib.parse import parse_qs, urlsplit

from astrbot_plugin_poe1db.builds import character_search_url


class BuildsUrlTests(unittest.TestCase):
    def test_builds_search_url_contains_current_league_and_name(self):
        url = character_search_url("Mirage", "My Hero")
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.assertEqual(parts.path, "/poe1/builds/Mirage")
        self.assertEqual(query["name"], ["My Hero"])
        self.assertEqual(query["search"], ["name=My Hero"])

    def test_invalid_league_rejected(self):
        with self.assertRaises(ValueError):
            character_search_url("../private", "Character")


if __name__ == "__main__":
    unittest.main()
