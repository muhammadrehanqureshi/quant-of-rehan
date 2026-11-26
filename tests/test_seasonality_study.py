"""The weekday seasonality study's own arithmetic, pinned offline.

The document this study writes is evidence, so the parts that decide what
counts as evidence are tested here on numbers small enough to check by hand:
the exact binomial tail, the Wilson interval, the Benjamini-Hochberg pass, and
an end to end run on a synthetic panel where the green days are placed on
purpose. No network, no dataset, no clock.
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

import pandas as pd

from scripts import seasonality_study as ss


class BinomialTailTest(unittest.TestCase):
    def test_all_successes_against_a_coin(self) -> None:
        # Ten of ten at p = 0.5 is 1/1024.
        self.assertAlmostEqual(ss.binomial_tail(10, 10, 0.5), 1 / 1024, places=12)

    def test_no_hits_is_certain(self) -> None:
        self.assertEqual(ss.binomial_tail(0, 20, 0.4), 1.0)

    def test_half_the_sample_at_the_base_rate_is_about_a_half(self) -> None:
        # P(X >= 50 | 100, 0.5) is 0.5398 by symmetry.
        self.assertAlmostEqual(ss.binomial_tail(50, 100, 0.5), 0.5398, places=4)

    def test_a_certain_coin_never_misses(self) -> None:
        self.assertEqual(ss.binomial_tail(5, 5, 1.0), 1.0)
        self.assertEqual(ss.binomial_tail(1, 5, 0.0), 0.0)

    def test_the_tail_shrinks_as_the_hits_grow(self) -> None:
        xs = [ss.binomial_tail(k, 60, 0.4) for k in (20, 30, 40, 50)]
        self.assertEqual(xs, sorted(xs, reverse=True))
        self.assertLess(xs[-1], 0.0001)


class WilsonTest(unittest.TestCase):
    def test_the_interval_holds_the_rate(self) -> None:
        lo, hi = ss.wilson(30, 100)
        self.assertLess(lo, 0.30)
        self.assertGreater(hi, 0.30)

    def test_a_small_sample_is_wide(self) -> None:
        small = ss.wilson(3, 5)
        big = ss.wilson(300, 500)
        self.assertGreater(small[1] - small[0], big[1] - big[0])

    def test_an_empty_sample_is_the_whole_range(self) -> None:
        self.assertEqual(ss.wilson(0, 0), (0.0, 1.0))


class BHHTest(unittest.TestCase):
    def test_one_small_p_value_survives_and_the_rest_do_not(self) -> None:
        q = ss.bh_qvalues([0.00001, 0.4, 0.5, 0.9])
        self.assertLess(q[0], 0.05)
        self.assertGreater(q[1], 0.05)

    def test_q_values_are_monotone_in_the_p_values(self) -> None:
        p = [0.02, 0.001, 0.3, 0.04]
        q = ss.bh_qvalues(p)
        pairs = sorted(zip(p, q))
        self.assertEqual([b for _, b in pairs], sorted(b for _, b in pairs))

    def test_nothing_to_correct(self) -> None:
        self.assertEqual(ss.bh_qvalues([]), [])


def synthetic_panel() -> pd.DataFrame:
    """Two scrips over eight weeks: ALFA is green on Mondays only, BETA never."""
    days = []
    d = dt.date(2026, 1, 5)  # a Monday
    while len(days) < 40:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    rows = []
    alfa, beta = 100.0, 100.0
    for day in days:
        # ALFA steps up 2 percent every Monday, BETA moves 0.2 percent daily.
        alfa *= 1.02 if day.weekday() == 0 else 1.0005
        beta *= 1.0005
        rows.append({"symbol": "ALFA", "date": day, "close": alfa})
        rows.append({"symbol": "BETA", "date": day, "close": beta})
    return pd.DataFrame(rows)


class StudyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.df = synthetic_panel()
        self.ret = ss.load_returns_from_frame(self.df)

    def test_returns_are_close_to_close_per_scrip(self) -> None:
        alfa = self.ret[self.ret["symbol"] == "ALFA"]
        # The first session of the panel has no previous close, so the first
        # measured return is the session after it, and every return at or above
        # the bar falls on a Monday.
        self.assertAlmostEqual(float(alfa["ret_pct"].iloc[0]), 0.05, places=6)
        self.assertAlmostEqual(float(alfa["ret_pct"].max()), 2.0, places=6)
        big = alfa[alfa["ret_pct"] >= 1.5]
        self.assertTrue((big["date"].dt.weekday == 0).all())

    def test_the_monday_scrip_is_found_with_its_dates(self) -> None:
        report = ss.study(self.ret, {"ALFA", "BETA"}, green=1.5,
                          min_sessions=4, min_symbol_sessions=4)
        best = report["rows"][0]
        self.assertEqual((best["symbol"], best["weekday"]), ("ALFA", "MONDAY"))
        self.assertEqual(best["green_sessions"], best["sessions"])
        self.assertEqual(best["missed_sessions"], 0)
        for entry in best["green_dates"]:
            self.assertEqual(dt.date.fromisoformat(entry["date"]).weekday(), 0)
        # A scrip that never clears the bar has no green dates anywhere.
        for row in report["rows"]:
            if row["symbol"] == "BETA":
                self.assertEqual(row["green_dates"], [])

    def test_a_perfect_row_is_reported_as_perfect(self) -> None:
        report = ss.study(self.ret, {"ALFA", "BETA"}, green=1.5,
                          min_sessions=4, min_symbol_sessions=4)
        self.assertTrue(report["perfect_rows"])
        said = ss.always_statement(report)
        self.assertEqual(said["perfect_pairs"], len(report["perfect_rows"]))

    def test_a_short_weekday_sample_is_not_tested(self) -> None:
        report = ss.study(self.ret, {"ALFA", "BETA"}, green=1.5,
                          min_sessions=99, min_symbol_sessions=4)
        self.assertEqual(report["study"]["tests"], 0)

    def test_the_whole_universe_is_reported_and_no_others(self) -> None:
        report = ss.study(self.ret, {"ALFA"}, green=1.5,
                          min_sessions=4, min_symbol_sessions=4)
        self.assertEqual(report["coverage"]["symbols"], 1)
        self.assertEqual({r["symbol"] for r in report["rows"]}, {"ALFA"})

    def test_the_document_renders_the_counts_and_the_dates(self) -> None:
        report = ss.study(self.ret, {"ALFA", "BETA"}, green=1.5,
                          min_sessions=4, min_symbol_sessions=4)
        report["generated"] = "2026-11-26T00:00:00+00:00"
        text = ss.render_markdown(report, 1.5, 5.0)
        self.assertIn("ALFA", text)
        self.assertIn("MONDAY", text)
        self.assertIn("always go green", text)
        self.assertIn(report["top"][0]["green_dates"][0]["date"], text)


class PanelTest(unittest.TestCase):
    def test_the_window_is_measured_back_from_the_last_session(self) -> None:
        df = synthetic_panel()
        ret = ss.load_returns_from_frame(df)
        window = ss.window_slice(ret, years=0.05, end=None)
        self.assertLessEqual(window["date"].max(), ret["date"].max())
        self.assertGreater(len(window), 0)
        self.assertLess(len(window), len(ret))


if __name__ == "__main__":
    unittest.main()
