import asyncio
import unittest
from unittest.mock import patch

from astrbot_plugin_poe1db.poecurrency import (
    NationalEconomyClient,
    NationalEconomyError,
    _valid_summary_url,
    parse_national_summary,
)


class PoECurrencyTests(unittest.TestCase):
    def test_summary_parses_poe1_currency_rows_and_skips_invalid_data(self):
        snapshot = parse_national_summary([
            {
                "category_label": "通货仓库",
                "items": [
                    {
                        "item_name": "神圣石",
                        "engname": "Divine Orb",
                        "buy_avg": 1000.5,
                        "sell_avg": 950,
                        "currency_unit": "c",
                        "latest_datetime": "2026-10-15 15:00:00",
                        "item_icon": "https://cdn.poedb.tw/image/Art/2DItems/Currency/DivineOrb.webp",
                    },
                    {
                        "item_name": "错误行情",
                        "engname": "Bad",
                        "buy_avg": float("nan"),
                        "sell_avg": 0,
                        "currency_unit": "c",
                    },
                    {
                        "item_name": "异常行情",
                        "engname": "Bad",
                        "buy_avg": 100,
                        "sell_avg": 99,
                        "currency_unit": "c",
                        "error": True,
                    },
                ],
            },
            {"category_label": "圣甲虫", "items": [{"item_name": "忽略", "buy_avg": 9}]},
        ])
        self.assertEqual(len(snapshot.prices), 1)
        self.assertEqual(snapshot.prices[0].name, "神圣石")
        self.assertEqual(snapshot.prices[0].currency_unit, "c")
        self.assertEqual(
            snapshot.prices[0].icon_url,
            "https://cdn.poedb.tw/image/Art/2DItems/Currency/DivineOrb.webp",
        )
        self.assertEqual(snapshot.latest_update, "2026-10-15 15:00:00")

    def test_summary_rejects_missing_currency_category(self):
        with self.assertRaises(NationalEconomyError):
            parse_national_summary([{"category_label": "圣甲虫", "items": []}])

    def test_summary_endpoint_is_exactly_allowlisted(self):
        self.assertTrue(_valid_summary_url("https://poecurrency.top/api/summary?version=1"))
        self.assertFalse(_valid_summary_url("https://poecurrency.top/api/summary?version=2"))
        self.assertFalse(_valid_summary_url("https://poecurrency.top.evil/api/summary?version=1"))
        self.assertFalse(_valid_summary_url("http://poecurrency.top/api/summary?version=1"))

    def test_client_caches_parsed_snapshot(self):
        async def scenario():
            client = NationalEconomyClient()
            payload = [{
                "category_label": "通货仓库",
                "items": [{
                    "item_name": "神圣石",
                    "engname": "Divine Orb",
                    "buy_avg": 1000,
                    "sell_avg": 950,
                    "currency_unit": "c",
                    "latest_datetime": "2026-10-15 15:00:00",
                }],
            }]
            with patch.object(client, "_download", return_value=payload) as download:
                first = await client.currency_snapshot()
                second = await client.currency_snapshot()
            return first, second, download

        first, second, download = asyncio.run(scenario())
        self.assertIs(first, second)
        download.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
