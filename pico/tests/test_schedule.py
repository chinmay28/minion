import unittest

import schedule

TARGETS = (7 * 60 + 15, 19 * 60 + 15)
TICK = 120


class NextStateTest(unittest.TestCase):
    def test_missing_file_refreshes(self):
        self.assertEqual(schedule.next_state(None), (True, None))

    def test_garbage_refreshes(self):
        self.assertEqual(schedule.next_state("banana"), (True, None))
        self.assertEqual(schedule.next_state(""), (True, None))

    def test_counts_down(self):
        self.assertEqual(schedule.next_state("6\n"), (False, 5))
        self.assertEqual(schedule.next_state("2"), (False, 1))

    def test_one_or_less_refreshes(self):
        self.assertEqual(schedule.next_state("1"), (True, None))
        self.assertEqual(schedule.next_state("0"), (True, None))
        self.assertEqual(schedule.next_state("-3"), (True, None))


class MinutesUntilTest(unittest.TestCase):
    def test_forward(self):
        self.assertEqual(schedule.minutes_until(0, 60), 60)

    def test_wraps_midnight(self):
        self.assertEqual(schedule.minutes_until(23 * 60, 60), 120)

    def test_same_time_is_a_day(self):
        self.assertEqual(schedule.minutes_until(435, 435), 1440)


class TicksUntilNextTest(unittest.TestCase):
    def test_on_time_morning_to_evening(self):
        self.assertEqual(schedule.ticks_until_next(7 * 60 + 15, TARGETS, TICK), 6)

    def test_on_time_evening_to_morning(self):
        self.assertEqual(schedule.ticks_until_next(19 * 60 + 15, TARGETS, TICK), 6)

    def test_late_drift_corrects_down(self):
        # Woke at 08:20 instead of 07:15: 10h55 to 19:15 rounds to 5 ticks,
        # landing at 18:20, which is inside half a tick of the target.
        self.assertEqual(schedule.ticks_until_next(8 * 60 + 20, TARGETS, TICK), 5)

    def test_early_drift_corrects_up(self):
        # Woke at 06:20: 07:15 is under half a tick away so it counts as
        # served; 12h55 to 19:15 rounds to 6 ticks (landing 18:20).
        self.assertEqual(schedule.ticks_until_next(6 * 60 + 20, TARGETS, TICK), 6)

    def test_retry_wake_between_targets(self):
        # A failed run retried at 13:15 aims at 19:15: 3 ticks.
        self.assertEqual(schedule.ticks_until_next(13 * 60 + 15, TARGETS, TICK), 3)

    def test_never_below_one(self):
        self.assertEqual(schedule.ticks_until_next(0, (70,), 120), 1)
        self.assertEqual(schedule.ticks_until_next(0, (100,), 120), 1)

    def test_target_within_half_tick_counts_as_served(self):
        # 30 minutes to the only target: this refresh was it, next one is tomorrow.
        self.assertEqual(schedule.ticks_until_next(0, (30,), 120), 12)

    def test_single_target_daily(self):
        self.assertEqual(schedule.ticks_until_next(7 * 60, (7 * 60,), 120), 12)

    def test_no_targets(self):
        self.assertEqual(schedule.ticks_until_next(0, (), 120), 1)


class ParseQuoteTimestampTest(unittest.TestCase):
    def test_parses(self):
        self.assertEqual(schedule.parse_quote_timestamp("05/23 07:12:03"), 7 * 60 + 12)
        self.assertEqual(schedule.parse_quote_timestamp(" 12/31 23:59:59\n"), 23 * 60 + 59)

    def test_rejects(self):
        for bad in (None, "", "garbage", "05/23", "05/23 25:00:00", "05/23 07:60:00", 42):
            self.assertIsNone(schedule.parse_quote_timestamp(bad), repr(bad))


if __name__ == "__main__":
    unittest.main()
