import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astrbot_plugin_poe1db.poedb_names import (
    LOCALIZED_FALLBACKS,
    PoEDBNameClient,
    _chinese_page_title,
    _poedb_slug,
    normalize_english_name,
)


class PoEDBNameTests(unittest.TestCase):
    def test_slug_preserves_canonical_words_and_encodes_spaces(self):
        self.assertEqual(_poedb_slug("The Original Scripture"), "The_Original_Scripture")
        self.assertEqual(_poedb_slug("Hinekora's Lock"), "Hinekora's_Lock")
        self.assertIsNone(_poedb_slug("../external"))

    def test_extracts_chinese_title_only_when_page_contains_requested_english_name(self):
        page = "<html><body><h3>法师之血</h3><h1>Mageblood</h1></body></html>"
        self.assertEqual(_chinese_page_title(page, "Mageblood"), "法师之血")
        self.assertIsNone(_chinese_page_title(page, "Different Item"))
        self.assertIsNone(_chinese_page_title("<h3>Mageblood</h3>", "Mageblood"))

    def test_uses_poedb_localized_html_title_when_page_has_no_chinese_heading(self):
        page = (
            "<html><head><title>虚空掌控 - 流亡编年史, Path of Exile Wiki cn</title></head>"
            "<body><h4>Community Wiki</h4><h1>Harness the Void</h1></body></html>"
        )
        self.assertEqual(_chinese_page_title(page, "Harness the Void"), "虚空掌控")

    def test_foulborn_uses_base_unique_translation_and_keeps_variant_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            client = PoEDBNameClient(Path(directory) / "names.json")
            with patch.object(client, "_fetch_page_title", return_value=("法师之血", True)) as fetch:
                translated, cacheable = client._fetch_translation("Foulborn Mageblood")
        self.assertEqual(translated, "秽生·法师之血")
        self.assertTrue(cacheable)
        fetch.assert_called_once_with("Mageblood")

    def test_translation_cache_survives_client_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "names.json"
            first = PoEDBNameClient(cache_path)

            async def save_first_name():
                with patch.object(first, "_fetch_translation", return_value=("均衡之符", True)):
                    return await first.resolve_names(["Astramentis"])

            result = asyncio.run(save_first_name())
            self.assertEqual(result, {normalize_english_name("Astramentis"): "均衡之符"})

            second = PoEDBNameClient(cache_path)

            async def read_cached_name():
                with patch.object(second, "_fetch_translation") as fetch:
                    cached = await second.resolve_names(["Astramentis"])
                fetch.assert_not_called()
                return cached

            self.assertEqual(asyncio.run(read_cached_name()), result)

    def test_generated_valdo_map_names_use_simplified_chinese_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            client = PoEDBNameClient(Path(directory) / "names.json")
            result = asyncio.run(
                client.resolve_names(
                    ["Secluded Ziggurat", "Ancestral Refuge", "Forgotten Pool"]
                )
            )
        self.assertEqual(result[normalize_english_name("Secluded Ziggurat")], "幽隐金字塔")
        self.assertEqual(result[normalize_english_name("Ancestral Refuge")], "先祖庇护所")
        self.assertEqual(result[normalize_english_name("Forgotten Pool")], "遗忘之池")
        self.assertGreaterEqual(len(LOCALIZED_FALLBACKS), 10)


if __name__ == "__main__":
    unittest.main()
