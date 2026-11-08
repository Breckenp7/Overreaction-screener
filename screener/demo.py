"""Fake market data for trying the app with no internet and for automated tests.
ALL NUMBERS ARE SYNTHETIC - none of these companies are real."""
import numpy as np
import pandas as pd
from .data import SECTOR_ETFS

N_DAYS = 2520  # ~10 years


class DemoProvider:
    def __init__(self, seed=7, market_selloff=False, n_filler=60, end="2026-11-06"):
        self.rng = np.random.default_rng(seed)
        self.idx = pd.bdate_range(end=end, periods=N_DAYS)
        self.market_selloff = market_selloff
        self._px, self._info, self._cap, self._earn, self._news = {}, {}, {}, {}, {}
        self._build(n_filler)

    # ------------ synthetic generation ------------
    def _walk(self, vol=0.017, drift=0.0003, start=100.0, rets=None):
        r = self.rng.normal(drift, vol, N_DAYS) if rets is None else rets
        return start * np.cumprod(1 + r), r

    def _frame(self, close):
        noise = np.abs(self.rng.normal(0, 0.004, len(close)))
        return pd.DataFrame({
            "Open": close * (1 + self.rng.normal(0, 0.003, len(close))),
            "High": close * (1 + noise), "Low": close * (1 - noise),
            "Close": close, "Volume": self.rng.integers(2_000_000, 6_000_000, len(close)).astype(float),
        }, index=self.idx)

    def _inject_past_drops(self, r, k=6, size=-0.09):
        pos = self.rng.choice(np.arange(300, N_DAYS - 40), k, replace=False)
        for p in pos:
            r[p] = size + self.rng.normal(0, 0.01)
            r[p + 1:p + 11] += self.rng.normal(0.003, 0.004, 10)  # mild rebound drift, for realism only
        return r

    def _earn_table(self, last_ts=None, beat=True, est=1.00, surprise=8.0):
        rows = []
        for q in range(7, 0, -1):  # earlier quarters
            ts = self.idx[-1 - 63 * q].tz_localize("America/New_York") + pd.Timedelta(hours=16, minutes=5)
            e = 1.0 + 0.02 * (7 - q)
            rows.append((ts, e, e * 1.03, 3.0))
        if last_ts is not None:
            rep = est * (1 + surprise / 100)
            rows.append((last_ts, est, rep, surprise))
        df = pd.DataFrame(rows, columns=["ts", "estimate", "reported", "surprise_pct"]).set_index("ts")
        return df

    def _add(self, t, close, cap, info, earn=None, news=None):
        self._px[t] = self._frame(close)
        self._cap[t] = cap
        self._info[t] = info
        self._earn[t] = earn
        self._news[t] = news or []

    def _build(self, n_filler):
        # benchmark + sector ETFs
        spy_c, spy_r = self._walk(vol=0.009, drift=0.0004, start=400)
        if self.market_selloff:
            spy_r[-1] = -0.025
            spy_c = 400 * np.cumprod(1 + spy_r)
        self._px["SPY"] = self._frame(spy_c)
        for etf in sorted(set(SECTOR_ETFS.values())):
            c, r = self._walk(vol=0.011, start=100)
            if self.market_selloff:
                r[-1] = -0.035
                c = 100 * np.cumprod(1 + r)
            self._px[etf] = self._frame(c)

        good = dict(sector="Technology", revenueGrowth=0.22, profitMargins=0.18, operatingMargins=0.24,
                    debtToEquity=45, currentRatio=2.1, forwardPE=22.0, trailingPE=30.0,
                    targetMeanPrice=None, recommendationKey="buy", earningsGrowth=0.2,
                    fiftyTwoWeekHigh=None, fiftyTwoWeekLow=None)
        last_after_close = self.idx[-2].tz_localize("America/New_York") + pd.Timedelta(hours=16, minutes=5)

        def scenario(ticker, name, last_ret, cap, info_over=None, earn=None, news=None, vol=0.017):
            c, r = self._walk(vol=vol, start=120)
            r = self._inject_past_drops(r)
            r[-1] = last_ret
            c = 120 * np.cumprod(1 + r)
            info = {**good, "shortName": name, **(info_over or {})}
            info["targetMeanPrice"] = info.get("targetMeanPrice") or float(c[-1] * 1.3)
            self._add(ticker, c, cap, info, earn, news)

        # 1) Strong earnings beat, sold off anyway
        scenario("DEMOA", "Demo Beat Corp", -0.105, 38e9,
                 earn=self._earn_table(last_after_close, est=1.00, surprise=9.0),
                 news=[{"title": "Demo Beat Corp posts record quarterly revenue; shares slide on valuation worries",
                        "publisher": "Synthetic News", "link": "https://example.com/a", "time": "2026-11-06"}])
        # 2) Beat but with red flags (negative growth, bad headlines)
        scenario("DEMOB", "Demo Flags Inc", -0.09, 21e9,
                 info_over=dict(revenueGrowth=-0.06, profitMargins=-0.02, forwardPE=55, targetMeanPrice=1.0, debtToEquity=320),
                 earn=self._earn_table(last_after_close, est=0.50, surprise=2.0),
                 news=[{"title": "Analyst downgrade after Demo Flags Inc lowers guidance", "publisher": "Synthetic News",
                        "link": "https://example.com/b", "time": "2026-11-06"}])
        # 3) Earnings miss
        scenario("DEMOC", "Demo Miss Ltd", -0.12, 15e9,
                 earn=self._earn_table(last_after_close, est=2.00, surprise=-6.0))
        # 4) Drop on a company too small
        scenario("DEMOS", "Demo Small Co", -0.09, 4e9,
                 earn=self._earn_table(last_after_close, est=1.0, surprise=5.0))
        # 5) Unexplained single-stock drop, no earnings
        scenario("DEMOD", "Demo Mystery Co", -0.08, 30e9, earn=self._earn_table(None))
        # 6) Technical support: oscillates between ~100 and ~116 for two years, lands on 100
        t = np.arange(N_DAYS)
        c = 108 + 8 * np.sin(2 * np.pi * t / 40) + self.rng.normal(0, 0.25, N_DAYS)
        # make sure the final stretch is a drop into the old low
        c[-2], c[-1] = 109.0, 100.6
        self._add("DEMOE", c, 25e9, {**good, "shortName": "Demo Support Co", "sector": "Industrials",
                                     "targetMeanPrice": 118.0}, self._earn_table(None))
        # filler: ordinary stocks that did not fall
        for i in range(n_filler):
            c, r = self._walk(vol=0.016)
            r[-1] = self.rng.normal(0, 0.012)
            c = 100 * np.cumprod(1 + r)
            self._add(f"FILL{i:02d}", c, float(self.rng.uniform(5e9, 90e9)),
                      {**good, "shortName": f"Filler {i}"}, self._earn_table(None))

    # ------------ provider interface ------------
    def prices(self, tickers, period="1y"):
        n = {"1y": 252, "5y": 1260, "10y": 2520}.get(period, 252)
        return {t: self._px[t].iloc[-n:].copy() for t in tickers if t in self._px}

    def market_cap(self, ticker):
        return self._cap.get(ticker)

    def info(self, ticker):
        return dict(self._info.get(ticker, {}))

    def earnings(self, ticker):
        return self._earn.get(ticker)

    def news(self, ticker):
        return list(self._news.get(ticker, []))

    def tickers(self):
        return [t for t in self._px if t != "SPY" and t not in set(SECTOR_ETFS.values())]
