import unittest
from datetime import datetime, timedelta, timezone

import localtime


class CalendarTest(unittest.TestCase):
    def test_round_trip_matches_datetime(self):
        epoch = datetime(1970, 1, 1)
        for days in range(-800, 30000, 37):
            d = epoch + timedelta(days=days)
            self.assertEqual(localtime.days_from_civil(d.year, d.month, d.day), days)
            self.assertEqual(localtime.civil_from_days(days), (d.year, d.month, d.day))

    def test_weekday(self):
        self.assertEqual(localtime.weekday(1970, 1, 1), 4)   # Thursday
        self.assertEqual(localtime.weekday(2026, 10, 25), 0)  # Sunday
        self.assertEqual(localtime.weekday(2026, 3, 8), 0)

    def test_nth_sunday(self):
        self.assertEqual(localtime.nth_sunday(2026, 3, 2), 8)
        self.assertEqual(localtime.nth_sunday(2026, 11, 1), 1)
        self.assertEqual(localtime.nth_sunday(2027, 3, 2), 14)
        self.assertEqual(localtime.nth_sunday(2027, 11, 1), 7)


class DstTest(unittest.TestCase):
    def test_edges_in_standard_time(self):
        # 2026: DST 8 March 02:00 PST to 1 November 01:00 PST.
        self.assertFalse(localtime.us_dst_active(2026, 3, 8, 119))
        self.assertTrue(localtime.us_dst_active(2026, 3, 8, 120))
        self.assertTrue(localtime.us_dst_active(2026, 7, 4, 0))
        self.assertTrue(localtime.us_dst_active(2026, 11, 1, 59))
        self.assertFalse(localtime.us_dst_active(2026, 11, 1, 60))
        self.assertFalse(localtime.us_dst_active(2026, 1, 15, 600))
        self.assertFalse(localtime.us_dst_active(2026, 12, 15, 600))


class ToLocalTest(unittest.TestCase):
    PACIFIC = -8 * 60

    def test_fixed_offset_crosses_midnight(self):
        self.assertEqual(localtime.to_local((2026, 1, 1, 3, 30, 0), self.PACIFIC), (2025, 12, 31, 19, 30))

    def test_summer_adds_an_hour(self):
        self.assertEqual(localtime.to_local((2026, 7, 4, 12, 0, 0), self.PACIFIC, True), (2026, 7, 4, 5, 0))

    def test_winter_does_not(self):
        self.assertEqual(localtime.to_local((2026, 1, 4, 12, 0, 0), self.PACIFIC, True), (2026, 1, 4, 4, 0))

    def test_against_zoneinfo(self):
        try:
            from zoneinfo import ZoneInfo
            la = ZoneInfo("America/Los_Angeles")
        except Exception:  # no tz database on this machine
            self.skipTest("zoneinfo unavailable")
        t = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2028, 1, 1, tzinfo=timezone.utc)
        step = timedelta(minutes=17 * 60 + 23)
        while t < end:
            want = t.astimezone(la)
            got = localtime.to_local((t.year, t.month, t.day, t.hour, t.minute, 0), self.PACIFIC, True)
            self.assertEqual(got, (want.year, want.month, want.day, want.hour, want.minute), t.isoformat())
            t += step

    def test_minute_of_day(self):
        self.assertEqual(localtime.minute_of_day((2026, 1, 1, 7, 15)), 435)


if __name__ == "__main__":
    unittest.main()
