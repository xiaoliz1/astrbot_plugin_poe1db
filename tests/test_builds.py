import unittest
from urllib.parse import parse_qs, urlsplit

from astrbot_plugin_poe1db.builds import character_search_url, extract_character_url


class BuildsUrlTests(unittest.TestCase):
    def test_builds_search_url_contains_current_league_and_name(self):
        url = character_search_url("Allflame", "My Hero")
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.assertEqual(parts.path, "/poe1/builds/allflame")
        self.assertEqual(query["name"], ["My Hero"])
        self.assertEqual(query["search"], ["name=My Hero"])

    def test_invalid_league_rejected(self):
        with self.assertRaises(ValueError):
            character_search_url("../private", "Character")

    def test_extracts_only_safe_exact_name_detail_link(self):
        detail = (
            "https://poe.ninja/poe1/builds/allflame/character/account-123/"
            "%E6%96%B9%E6%BA%90%E9%80%86%E6%B5%81%E6%B2%B3?i=0"
        )
        result = extract_character_url(
            "Allflame",
            "方源逆流河",
            [
                {"name": "方源逆流河", "href": detail},
                {"name": "方源逆流河2", "href": "https://poe.ninja/other"},
                {"name": "方源逆流河", "href": "https://example.org/steal"},
            ],
        )
        self.assertEqual(result, detail)

    def test_duplicate_exact_matches_are_ambiguous(self):
        links = [
            {"name": "Character", "href": f"https://poe.ninja/poe1/builds/allflame/character/a-{i}/Character"}
            for i in (1, 2)
        ]
        self.assertIsNone(extract_character_url("Allflame", "Character", links))


if __name__ == "__main__":
    unittest.main()
