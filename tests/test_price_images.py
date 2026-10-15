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

    def test_national_image_groups_three_price_units_and_shows_latest_time(self):
        snapshot = NationalPriceSnapshot((
            NationalCurrencyPrice("神圣石", "Divine Orb", 12, 10, "d", "today"),
            NationalCurrencyPrice("崇高石", "Exalted Orb", 100, 95, "c", "today"),
        ), "2026-10-15 17:00:00")
        html = render_national_html(snapshot, {"divineorb": "https://web.poecdn.com/gen/image/divine.png"})
        self.assertIn("按神圣石计价", html)
        self.assertIn("按混沌石计价", html)
        self.assertIn("2026-10-15 17:00:00", html)
        self.assertIn('src="https://web.poecdn.com/gen/image/divine.png"', html)
        self.assertIn("买 12 神圣石", html)


if __name__ == "__main__":
    unittest.main()
