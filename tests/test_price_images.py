import unittest

from astrbot_plugin_poe1db.economy import CurrencyPrice, PriceSnapshot
from astrbot_plugin_poe1db.poecurrency import NationalCurrencyPrice, NationalPriceSnapshot
from astrbot_plugin_poe1db.price_images import render_international_html, render_national_html


class PriceImageTests(unittest.TestCase):
    def test_international_image_uses_national_translation_for_matching_names(self):
        international = PriceSnapshot("Mirage", (
            CurrencyPrice("Divine Orb", 1000, "https://web.poecdn.com/gen/image/divine.png", divine_value=1),
            CurrencyPrice("Fracturing Orb", 500, divine_value=0.5),
            CurrencyPrice("Unmatched Relic", 10, divine_value=0.01),
        ))
        national = NationalPriceSnapshot((
            NationalCurrencyPrice("神圣石", "Divine Orb", 12, 10, "c", "today"),
            NationalCurrencyPrice("裂隙宝珠", "Fracturing Orb", 9, 8, "d", "today"),
            NationalCurrencyPrice("Unmatched Relic", "Unmatched Relic", 1, 1, "c", "today"),
        ), "today")

        html = render_international_html(international, "now", national)

        self.assertIn("神圣石</span>", html)
        self.assertIn("裂隙宝珠</span>", html)
        self.assertIn("Unmatched Relic</span>", html)
        self.assertIn('src="https://web.poecdn.com/gen/image/divine.png"', html)
        self.assertIn("1 神圣石", html)
        self.assertIn("0.5 神圣石", html)

    def test_international_image_escapes_names_shows_icons_and_limits_rows(self):
        rows = (
            CurrencyPrice("Divine Orb", 1000, change_percent=5, trend=(1, 2, 3), divine_value=100),
            CurrencyPrice("Direct Price Wins", 1, divine_value=150),
        ) + tuple(
            CurrencyPrice(
                f"Orb {index}",
                10000 - index,
                "https://web.poecdn.com/gen/image/example.png",
                divine_value=50 - index / 10,
            )
            for index in range(55)
        ) + (CurrencyPrice("Chaos Only Relic", 999999), CurrencyPrice("Zero Divine", 500, divine_value=0))
        snapshot = PriceSnapshot("Allflame", rows)
        html = render_international_html(snapshot, "2026-10-15 18:00:00")
        self.assertIn("Allflame", html)
        self.assertIn("价格（神圣石）", html)
        self.assertIn("150 神圣石", html)
        self.assertIn("100 神圣石", html)
        self.assertIn('<td class="category">通货</td>', html)
        self.assertIn("七日趋势", html)
        self.assertIn("+5.0%", html)
        self.assertIn('src="https://web.poecdn.com/gen/image/example.png"', html)
        self.assertEqual(html.count('<td class="rank">'), 50)
        self.assertLess(html.index("Direct Price Wins"), html.index("Divine Orb"))
        self.assertIn("Orb 47", html)
        self.assertNotIn("Orb 48", html)
        self.assertNotIn("Orb 54", html)
        self.assertNotIn("Chaos Only Relic", html)
        self.assertNotIn("Zero Divine", html)
        self.assertIn(">传奇物品</td>", render_international_html(
            PriceSnapshot("Allflame", (CurrencyPrice("小额物品", 200, divine_value=0.1, category="传奇物品"),)),
            "now",
        ))
        self.assertIn("0.1 神圣石", render_international_html(
            PriceSnapshot("Allflame", (CurrencyPrice("小额物品", 200, divine_value=0.1),)), "now"
        ))

        injected = render_international_html(PriceSnapshot("<script>", (CurrencyPrice("<img>", 1),)), "now")
        self.assertNotIn("<script>", injected)
        self.assertIn("&lt;script&gt;", injected)
        self.assertNotIn('src="https://evil.example/', injected)

    def test_national_image_filters_direct_divine_quotes_and_sorts_local_price_descending(self):
        snapshot = NationalPriceSnapshot((
            NationalCurrencyPrice("神圣石", "Divine Orb", 12, 10, "d", "today"),
            NationalCurrencyPrice("崇高石", "Exalted Orb", 100, 95, "c", "today"),
            NationalCurrencyPrice(
                "卡兰德的魔镜",
                "Mirror of Kalandra",
                5,
                4,
                "d",
                "today",
                "https://cdn.poedb.tw/image/Art/2DItems/Currency/CurrencyDuplicate.webp",
                "通货仓库",
            ),
            NationalCurrencyPrice("崇高石（神圣计价）", "Exalted Orb", 2, 1, "d", "today"),
            NationalCurrencyPrice("未匹配物品", "Unknown Relic", 1, 0.5, "d", "today"),
        ), "2026-10-15 17:00:00")
        html = render_national_html(
            snapshot,
            {"divineorb": "https://web.poecdn.com/gen/image/divine.png"},
        )
        self.assertIn("神圣石计价", html)
        self.assertIn(">#</th>", html)
        self.assertNotIn("国际02", html)
        self.assertNotIn("按混沌石计价", html)
        self.assertIn("2026-10-15 17:00:00", html)
        self.assertIn('src="https://web.poecdn.com/gen/image/divine.png"', html)
        self.assertIn(
            'src="https://cdn.poedb.tw/image/Art/2DItems/Currency/CurrencyDuplicate.webp"',
            html,
        )
        self.assertIn("买入均价（神圣石）", html)
        self.assertIn("通货仓库</td>", html)
        self.assertIn("分类</th>", html)
        self.assertIn(">12 神圣石</td>", html)
        self.assertNotIn("100 崇高石", html)
        self.assertLess(html.index("神圣石</span>"), html.index("卡兰德的魔镜"))
        self.assertLess(html.index("卡兰德的魔镜"), html.index("崇高石（神圣计价）"))

    def test_national_image_caps_rows_and_reports_when_divine_quotes_are_empty(self):
        rows = tuple(
            NationalCurrencyPrice(f"物品 {index}", f"Item {index}", index + 1, index, "d", "today", category="高价命运卡")
            for index in range(55)
        ) + (NationalCurrencyPrice("混沌石物品", "Chaos Item", 100, 80, "c", "today"),)
        html = render_national_html(NationalPriceSnapshot(rows, "today"))
        self.assertEqual(html.count('<td class="rank">'), 50)
        self.assertIn("物品 54", html)
        self.assertIn("物品 5", html)
        self.assertNotIn("物品 4</span>", html)
        self.assertNotIn("混沌石物品", html)

        empty = render_national_html(NationalPriceSnapshot((), "today"))
        self.assertIn("当前没有神圣石计价的国服行情", empty)


if __name__ == "__main__":
    unittest.main()
