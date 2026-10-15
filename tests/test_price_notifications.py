import unittest

from astrbot_plugin_poe1db.price_notifications import (
    group_umo_parts,
    parse_notification_targets,
    ready_price_requests,
    select_notification_targets,
)


class PriceNotificationTests(unittest.TestCase):
    def test_targets_parse_and_pending_requests_wait_for_their_market(self):
        self.assertEqual(parse_notification_targets("123, 456\n123"), ("123", "456"))
        pending = {("qq:GroupMessage:1", "international"), ("qq:GroupMessage:2", "national")}
        self.assertEqual(ready_price_requests(pending, {"national"}), [("qq:GroupMessage:2", "national")])
        self.assertEqual(group_umo_parts("qq:GroupMessage:1"), ("qq", "GroupMessage", "1"))
        self.assertIsNone(group_umo_parts("qq:FriendMessage:1"))

    def test_whitelist_and_blacklist_have_distinct_group_semantics(self):
        known = {"qq:GroupMessage:123", "qq:GroupMessage:456"}
        self.assertEqual(
            select_notification_targets("whitelist", "123", known, ["qq"]),
            ["qq:GroupMessage:123"],
        )
        self.assertEqual(
            select_notification_targets("blacklist", "123", known),
            ["qq:GroupMessage:456"],
        )
        self.assertEqual(select_notification_targets("whitelist", "789", set(), ["qq"]), ["qq:GroupMessage:789"])
        self.assertEqual(select_notification_targets("whitelist", "789", set(), ["qq", "other"]), [])


if __name__ == "__main__":
    unittest.main()
