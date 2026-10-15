import unittest
from datetime import datetime, time, timedelta

from astrbot_plugin_poe1db.price_schedule import (
    DEFAULT_REFRESH_TIMES,
    next_hourly_price_refresh_at,
    next_price_refresh_at,
    normalize_utc_offset_hours,
    parse_daily_refresh_times,
    timezone_for_utc_offset,
)


class PriceScheduleTests(unittest.TestCase):
    def test_refresh_times_parse_and_fall_back(self):
        self.assertEqual(parse_daily_refresh_times("06:00,12:00\n18:00,24:00"), (
            time(0, 0), time(6, 0), time(12, 0), time(18, 0)
        ))
        self.assertEqual(parse_daily_refresh_times("invalid"), DEFAULT_REFRESH_TIMES)

    def test_utc_offset_is_clamped_and_finite(self):
        self.assertEqual(normalize_utc_offset_hours(20), 14)
        self.assertEqual(normalize_utc_offset_hours(float("nan")), 8)
        self.assertEqual(timezone_for_utc_offset(5.5).utcoffset(None), timedelta(hours=5, minutes=30))

    def test_hourly_and_notification_deadlines_are_next_slots(self):
        zone = timezone_for_utc_offset(8)
        now = datetime(2026, 10, 15, 17, 42, tzinfo=zone)
        self.assertEqual(next_hourly_price_refresh_at(now), datetime(2026, 10, 15, 18, 0, tzinfo=zone))
        self.assertEqual(next_price_refresh_at(now, "00:00,06:00,12:00,18:00"), datetime(2026, 10, 15, 18, 0, tzinfo=zone))
        after_slot = datetime(2026, 10, 15, 18, 0, 1, tzinfo=zone)
        self.assertEqual(next_price_refresh_at(after_slot, "18:00"), datetime(2026, 10, 16, 18, 0, tzinfo=zone))


if __name__ == "__main__":
    unittest.main()
