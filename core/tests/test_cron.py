"""
test_cron.py — five-field cron evaluator and the "which tasks are due"
decision of the scheduler (clock simulated, no daemon).
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_task
from mc_task import Cron, CronError

D = datetime.datetime


class TestParsing(unittest.TestCase):

    def test_star_matches_every_minute(self):
        self.assertTrue(Cron("* * * * *").matches(D(2026, 10, 3, 12, 34)))

    def test_list_range_step(self):
        cron = Cron("0,30 8-10 * * *")
        self.assertEqual(cron.minutes, {0, 30})
        self.assertEqual(cron.hours, {8, 9, 10})
        self.assertEqual(Cron("*/15 * * * *").minutes, {0, 15, 30, 45})
        self.assertEqual(Cron("10-30/10 * * * *").minutes, {10, 20, 30})
        self.assertEqual(Cron("5/20 * * * *").minutes, {5, 25, 45})

    def test_names(self):
        cron = Cron("0 4 1 jan,mar mon-fri")
        self.assertEqual(cron.months, {1, 3})
        self.assertEqual(cron.weekdays, {1, 2, 3, 4, 5})

    def test_sunday_is_zero_or_seven(self):
        self.assertEqual(Cron("0 0 * * 7").weekdays, {0})
        self.assertEqual(Cron("0 0 * * 0").weekdays, {0})

    def test_invalid(self):
        for text in ("", "* * * *", "* * * * * *", "60 * * * *", "* 24 * * *", "* * 0 * *",
                     "* * * 13 *", "*/0 * * * *", "5-1 * * * *", "a * * * *", "1,,2 * * * *", "*/x * * * *"):
            with self.subTest(text=text), self.assertRaises(CronError):
                Cron(text)


class TestMatching(unittest.TestCase):

    def test_daily_four_am(self):
        cron = Cron("0 4 * * *")
        self.assertTrue(cron.matches(D(2026, 10, 3, 4, 0)))
        self.assertFalse(cron.matches(D(2026, 10, 3, 4, 1)))
        self.assertFalse(cron.matches(D(2026, 10, 3, 5, 0)))

    def test_weekday_only(self):
        cron = Cron("0 4 * * 1")   # Monday
        self.assertTrue(cron.matches(D(2026, 10, 5, 4, 0)))
        self.assertFalse(cron.matches(D(2026, 10, 6, 4, 0)))

    def test_day_or_weekday_when_both_restricted(self):
        cron = Cron("0 0 13 * 5")   # the 13th, or any Friday
        self.assertTrue(cron.matches(D(2026, 10, 13, 0, 0)))   # Tuesday the 13th
        self.assertTrue(cron.matches(D(2026, 10, 2, 0, 0)))    # Friday the 2nd
        self.assertFalse(cron.matches(D(2026, 10, 14, 0, 0)))

    def test_month(self):
        cron = Cron("0 0 1 12 *")
        self.assertTrue(cron.matches(D(2026, 12, 1, 0, 0)))
        self.assertFalse(cron.matches(D(2026, 11, 1, 0, 0)))


class TestNextRun(unittest.TestCase):

    def test_next_is_strictly_after(self):
        cron = Cron("*/10 * * * *")
        self.assertEqual(cron.next_after(D(2026, 10, 3, 12, 10, 30)), D(2026, 10, 3, 12, 20))
        self.assertEqual(cron.next_after(D(2026, 10, 3, 12, 9)), D(2026, 10, 3, 12, 10))

    def test_rolls_over_day_month_year(self):
        self.assertEqual(Cron("0 4 * * *").next_after(D(2026, 10, 3, 5, 0)), D(2026, 10, 4, 4, 0))
        self.assertEqual(Cron("0 0 1 * *").next_after(D(2026, 12, 31, 12, 0)), D(2027, 1, 1, 0, 0))

    def test_february_29(self):
        self.assertEqual(Cron("0 0 29 2 *").next_after(D(2026, 3, 1)), D(2028, 2, 29, 0, 0))

    def test_impossible_date_returns_none(self):
        self.assertIsNone(Cron("0 0 31 2 *").next_after(D(2026, 1, 1)))


def _config(*tasks):
    return {"tasks": list(tasks)}


def _task(**kw):
    return dict({"id": 1, "name": "t", "cron": "0 4 * * *", "action": "backup", "enabled": True}, **kw)


class TestDue(unittest.TestCase):

    def test_due_on_the_minute_once(self):
        fired = {}
        config = _config(_task())
        self.assertEqual(len(mc_task.due_tasks(config, fired, D(2026, 10, 3, 4, 0, 5))), 1)
        self.assertEqual(mc_task.due_tasks(config, fired, D(2026, 10, 3, 4, 0, 35)), [])
        self.assertEqual(len(mc_task.due_tasks(config, fired, D(2026, 10, 4, 4, 0, 5))), 1)

    def test_not_due_off_the_minute(self):
        self.assertEqual(mc_task.due_tasks(_config(_task()), {}, D(2026, 10, 3, 3, 59, 59)), [])

    def test_disabled_and_broken_are_ignored(self):
        config = _config(_task(enabled=False), _task(id=2, cron="nope"))
        self.assertEqual(mc_task.due_tasks(config, {}, D(2026, 10, 3, 4, 0)), [])

    def test_missed_minute_is_not_caught_up(self):
        self.assertEqual(mc_task.due_tasks(_config(_task()), {}, D(2026, 10, 3, 4, 7)), [])

    def test_warnings_start_the_task_early(self):
        config = _config(_task(action="restart", warn=[600, 60]))
        due = mc_task.due_tasks(config, {}, D(2026, 10, 3, 3, 50, 10))
        self.assertEqual([t for _, t in due], [D(2026, 10, 3, 4, 0)])
        self.assertEqual(mc_task.due_tasks(config, {}, D(2026, 10, 3, 4, 0)), [])


if __name__ == "__main__":
    unittest.main()
