import unittest
from pathlib import Path
import numpy as np
import pandas as pd

from screener.config import load_config, ROOT
from screener import events, history, scoring, pipeline
from screener.demo import DemoProvider
from screener.report import build_html, build_text

CFG = load_config()


def series(vals, start="2020-01-01"):
    idx = pd.bdate_range(start=start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


class TestEvents(unittest.TestCase):
    def test_detect_single_day_drop(self):
        rng = np.random.default_rng(1)
        c = series(100 * np.cumprod(1 + rng.normal(0, 0.01, 200)))
        c.iloc[-1] = c.iloc[-2] * 0.92
        d = events.detect_drop(c, CFG)
        self.assertIsNotNone(d)
        self.assertEqual(d["type"], "single_day")
        self.assertAlmostEqual(d["return"], -0.08, places=3)

    def test_no_drop_below_threshold(self):
        c = series(np.linspace(100, 110, 200))
        c.iloc[-1] = c.iloc[-2] * 0.95
        self.assertIsNone(events.detect_drop(c, CFG))

    def test_multi_day_drop(self):
        c = series(np.full(200, 100.0))
        c.iloc[-5:] = [97, 94, 92, 90, 87]  # -13% over 5 days, no single day >= 7%
        d = events.detect_drop(c, CFG)
        self.assertEqual(d["type"], "5_day")

    def test_reaction_date_after_close_goes_to_next_day(self):
        days = pd.bdate_range("2026-11-02", periods=6)
        ts = pd.Timestamp("2026-11-04 16:05", tz="America/New_York")
        self.assertEqual([x.date() for x in events.reaction_date(ts, days)], [pd.Timestamp("2026-11-05").date()])

    def test_reaction_date_premarket_same_day(self):
        days = pd.bdate_range("2026-11-02", periods=6)
        ts = pd.Timestamp("2026-11-04 07:00", tz="America/New_York")
        self.assertEqual([x.date() for x in events.reaction_date(ts, days)], [pd.Timestamp("2026-11-04").date()])

    def test_earnings_match_ignores_unreported(self):
        days = pd.bdate_range("2026-11-02", periods=6)
        df = pd.DataFrame({"estimate": [1.0], "reported": [np.nan], "surprise_pct": [np.nan]},
                          index=[pd.Timestamp("2026-11-04 07:00", tz="America/New_York")])
        self.assertIsNone(events.match_earnings(df, days[2], days))


class TestHistoryNoLookahead(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        r = rng.normal(0.0003, 0.012, 1500)
        for p in (300, 600, 900, 1200, 1480):
            r[p] = -0.10
        self.close = series(100 * np.cumprod(1 + r))
        self.spy = series(100 * np.cumprod(1 + rng.normal(0.0003, 0.009, 1500)))

    def test_recent_event_excluded_until_window_complete(self):
        idxs = history.find_events(self.close, 0.08)
        measured = [history.measure_event(self.close, self.spy, i, [5, 10, 20], 0.001) for i in idxs]
        self.assertIsNone(measured[-1])  # event at 1480: fewer than 20 days remain
        self.assertTrue(all(m is not None for m in measured[:-1]))

    def test_future_data_cannot_change_past_event(self):
        i = 600
        full = history.measure_event(self.close, self.spy, i, [5, 10, 20], 0.001)
        trunc = history.measure_event(self.close.iloc[:i + 25], self.spy.iloc[:i + 25], i, [5, 10, 20], 0.001)
        self.assertEqual(full["r20"], trunc["r20"])
        # and truncating to less than the 20d window refuses to measure
        self.assertIsNone(history.measure_event(self.close.iloc[:i + 15], self.spy.iloc[:i + 15], i, [5, 10, 20], 0.001))

    def test_costs_reduce_returns(self):
        a = history.measure_event(self.close, self.spy, 600, [5], 0.0)
        b = history.measure_event(self.close, self.spy, 600, [5], 0.01)
        self.assertAlmostEqual(a["r5"] - b["r5"], 0.01)

    def test_cooldown_dedupes_clusters(self):
        c = series(np.full(100, 100.0))
        c.iloc[50] = 90; c.iloc[51] = 80; c.iloc[52] = 70
        self.assertEqual(len(history.find_events(c, 0.07, cooldown=10)), 1)

    def test_same_stock_excludes_current_day(self):
        s = history.same_stock_history(self.close.iloc[:1481], self.spy.iloc[:1481], 0.10, CFG)
        dates = [r["date"] for r in s["last_five"]]
        self.assertNotIn(str(self.close.index[1480].date()), dates)


class TestScoring(unittest.TestCase):
    def test_weights_sum_to_100(self):
        self.assertEqual(sum(CFG["scoring"]["weights"].values()), 100)

    def test_score_bounds_and_missing_data(self):
        drop = {"z_score": 5.0, "last_close": 100.0, "return": -0.1}
        decomp = {"idio_share": 0.9, "spy_return": 0.0}
        sc = scoring.score_candidate(CFG, "technical_support", drop, decomp, None, {}, None, {}, None, [])
        self.assertTrue(0 <= sc["score"] <= 100)
        self.assertLess(sc["coverage_pct"], 100)

    def test_thin_history_cannot_max_out(self):
        same = {"n": 2, "horizons": {20: {"win_rate_vs_spy": 1.0}}}
        s, _ = scoring.historical_rebound(same, None)
        self.assertLess(s, 0.45)

    def test_no_history_is_neutral_not_skipped(self):
        s, _ = scoring.historical_rebound({"n": 0}, None)
        self.assertEqual(s, 0.25)


class TestEndToEnd(unittest.TestCase):
    def run_scan(self, **kw):
        p = DemoProvider(**kw)
        return pipeline.run_scan(p, CFG, p.tickers(), ROOT, log=lambda *_: None)

    def test_demo_filters_and_ranks(self):
        res = self.run_scan()
        names = [c["ticker"] for c in res["candidates"]]
        self.assertNotIn("DEMOS", names)   # too small
        self.assertNotIn("DEMOC", names)   # EPS miss
        self.assertNotIn("DEMOD", names)   # uncategorized
        self.assertEqual(names[0], "DEMOA")  # clean earnings beat ranks first
        self.assertEqual(names[-1], "DEMOB")  # beat with red flags ranks last
        scores = [c["score"]["score"] for c in res["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_broad_market_category(self):
        res = self.run_scan(market_selloff=True)
        by = {c["ticker"]: c for c in res["candidates"]}
        self.assertIn("broad_market", by["DEMOD"]["categories"])  # now explained by market

    def test_reports_render(self):
        res = self.run_scan()
        html = build_html(res, CFG, "Market-close", "test")
        text = build_text(res, CFG, "Market-close", "test")
        self.assertIn("DEMOA", html)
        self.assertIn("not investment advice", text)

    def test_data_quality_warning(self):
        p = DemoProvider()
        tickers = p.tickers() + [f"MISSING{i}" for i in range(100)]
        res = pipeline.run_scan(p, CFG, tickers, ROOT, log=lambda *_: None)
        self.assertFalse(res["data_ok"])
        self.assertTrue(any("DATA QUALITY" in w for w in res["warnings"]))


if __name__ == "__main__":
    unittest.main()
