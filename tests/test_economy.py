import asyncio
import time
import unittest
from unittest.mock import patch

from astrbot_plugin_poe1db.economy import EconomyClient, _cache_ttl


class EconomyTests(unittest.TestCase):
    def test_cache_ttl_respects_server_max_age(self):
        class Headers(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        self.assertEqual(_cache_ttl(Headers({"Cache-Control": "public, max-age=120"}), 300), 120)
        self.assertEqual(_cache_ttl(Headers({"Cache-Control": "no-cache"}), 300), 0)
        self.assertEqual(_cache_ttl(Headers({"Cache-Control": "no-store"}), 300), -1)

    def test_stale_response_uses_etag_and_reuses_body_on_not_modified(self):
        async def scenario():
            client = EconomyClient(cache_seconds=300)
            url = "https://poe.ninja/poe1/api/economy/leagues"
            client._cache[url] = (time.monotonic() - 1, ["cached"], '"abc"')
            with patch.object(
                client,
                "_download_json",
                return_value=(None, 300, '"abc"', True),
            ) as download:
                body = await client._fetch_json(url)
            return body, download

        body, download = asyncio.run(scenario())
        self.assertEqual(body, ["cached"])
        self.assertEqual(download.call_args.args, ("https://poe.ninja/poe1/api/economy/leagues", '"abc"'))

    def test_currency_snapshot_reads_and_sorts_supported_categories(self):
        async def scenario():
            client = EconomyClient()
            async def fake_league():
                return "Mirage"

            async def fake_fetch(url):
                    if "type=Currency" in url:
                        return {
                            "currencyDetails": [{
                                "name": "Divine Orb",
                                "icon": "https://web.poecdn.com/gen/image/divine.png",
                            }],
                            "lines": [
                            {"currencyTypeName": "Divine Orb", "chaosEquivalent": 160,
                             "receiveSparkLine": {"totalChange": 5, "data": [1, 2, 3]}},
                            {"currencyTypeName": "Chaos Orb", "chaosEquivalent": 1},
                            ]
                        }
                    return {"lines": [
                        {"currencyTypeName": "Maven's Invitation", "chaosEquivalent": 12},
                        {"currencyTypeName": "Bad", "chaosEquivalent": float("nan")},
                    ]}

            with patch.object(client, "current_league", new=fake_league):
                with patch.object(client, "_fetch_json", new=fake_fetch):
                    return await client.currency_snapshot()

        snapshot = asyncio.run(scenario())
        self.assertEqual(snapshot.league, "Mirage")
        self.assertEqual(
            [price.name for price in snapshot.prices],
            ["Divine Orb", "Maven's Invitation", "Chaos Orb"],
        )
        self.assertEqual(snapshot.prices[0].icon_url, "https://web.poecdn.com/gen/image/divine.png")
        self.assertEqual(snapshot.prices[0].category, "通货")
        self.assertEqual(snapshot.prices[0].change_percent, 5)
        self.assertEqual(snapshot.prices[0].trend, (1.0, 2.0, 3.0))

    def test_invalidate_cache_expires_entries_without_discarding_etag(self):
        client = EconomyClient()
        url = "https://poe.ninja/poe1/api/economy/leagues"
        client._cache[url] = (time.monotonic() + 300, ["Allflame"], '"abc"')
        client.invalidate_cache()
        self.assertEqual(client._cache[url][1:], (["Allflame"], '"abc"'))
        self.assertLessEqual(client._cache[url][0], time.monotonic())


if __name__ == "__main__":
    unittest.main()
