import unittest

from astrbot_plugin_poe1db.economy import CurrencyPrice, PriceSnapshot
from astrbot_plugin_poe1db.poecurrency import NationalCurrencyPrice, NationalPriceSnapshot
from astrbot_plugin_poe1db.price_images import render_international_html, render_national_html


class PriceImageTests(unittest.TestCase):
    def test_international_image_escapes_names_shows_icons_and_limits_rows(self):
        rows = (CurrencyPrice("Divine Orb", 1000, change_percent=5, trend=(1, 2, 3)),) + tuple(
            CurrencyPrice(f"Orb {index}", 100 - index, "https://web.poecdn.com/gen/image/example.png")
            for index in range(55)
        )
        snapshot = PriceSnapshot("Allflame", rows)
        html = render_international_html(snapshot, "2026-10-15 18:00:00")
        self.assertIn("Allflame", html)
        self.assertIn("价格（神圣石）", html)
        self.assertIn("1 神圣石", html)
        self.assertIn("0.1 神圣石", html)
        self.assertIn('<td class="category">通货</td>', html)
        self.assertIn("七日趋势", html)
        self.assertIn("+5.0%", html)
        self.assertIn('src="https://web.poecdn.com/gen/image/example.png"', html)
        self.assertEqual(html.count('<td class="rank">'), 50)
        self.assertNotIn("Orb 54", html)

        injected = render_international_html(PriceSnapshot("<script>", (CurrencyPrice("<img>", 1),)), "now")
        self.assertNotIn("<script>", injected)
        self.assertIn("&lt;script&gt;", injected)
        self.assertNotIn('src="https://evil.example/', injected)

    def test_national_image_uses_divine_quotes_and_follows_international_order(self):
        snapshot = NationalPriceSnapshot((
            NationalCurrencyPrice("神圣石", "Divine Orb", 12, 10, "d", "today"),
            NationalCurrencyPrice("崇高石", "Exalted Orb", 100, 95, "c", "today"),
            NationalCurrencyPrice("卡兰德的魔镜", "Mirror of Kalandra", 5, 4, "d", "today"),
            NationalCurrencyPrice("崇高石（神圣计价）", "Exalted Orb", 2, 1, "d", "today"),
            NationalCurrencyPrice("未匹配物品", "Unknown Relic", 1, 0.5, "d", "today"),
        ), "2026-10-15 17:00:00")
        international = PriceSnapshot("Mirage", (
            CurrencyPrice("Mirror of Kalandra", 1000),
            CurrencyPrice("Divine Orb", 100),
            CurrencyPrice("Exalted Orb", 50),
        ))
        html = render_national_html(
            snapshot,
            international,
            {"divineorb": "https://web.poecdn.com/gen/image/divine.png"},
        )
        self.assertIn("神圣石计价", html)
        self.assertIn("排序来源", html)
        self.assertIn("国际02", html)
        self.assertIn(">国服</td>", html)
        self.assertNotIn("按混沌石计价", html)
        self.assertIn("2026-10-15 17:00:00", html)
        self.assertIn('src="https://web.poecdn.com/gen/image/divine.png"', html)
        self.assertIn("买入均价（神圣石）", html)
        self.assertIn(">12 神圣石</td>", html)
        self.assertNotIn("100 崇高石", html)
        self.assertLess(
            html.index("卡兰德的魔镜"),
            html.index("神圣石</span>"),
        )
        self.assertLess(
            html.index("神圣石</span>"),
            html.index("崇高石（神圣计价）"),
        )

    def test_national_image_caps_rows_and_reports_when_divine_quotes_are_empty(self):
        rows = tuple(
            NationalCurrencyPrice(f"物品 {index}", f"Item {index}", 50 - index, 40 - index, "d", "today")
            for index in range(55)
        ) + (NationalCurrencyPrice("混沌石物品", "Chaos Item", 10, 8, "c", "today"),)
        html = render_national_html(NationalPriceSnapshot(rows, "today"))
        self.assertEqual(html.count('<td class="rank">'), 50)
        self.assertIn("物品 49", html)
        self.assertNotIn("物品 50", html)
        self.assertNotIn("混沌石物品", html)

        empty = render_national_html(NationalPriceSnapshot((), "today"))
        self.assertIn("当前没有神圣石计价的国服行情", empty)


if __name__ == "__main__":
    unittest.main()
