"""Data access. Everything the rest of the app needs from the outside world goes
through a "provider" object with these methods:

    prices(tickers, period)   -> {ticker: DataFrame[Open,High,Low,Close,Volume]}
    market_cap(ticker)        -> float | None   (US dollars)
    info(ticker)              -> dict           (fundamentals snapshot)
    earnings(ticker)          -> DataFrame | None  (index = tz-aware timestamps;
                                 columns: estimate, reported, surprise_pct)
    news(ticker)              -> list[{title, publisher, link, time}]

YahooProvider is the real one (free, unofficial Yahoo Finance data through the
`yfinance` library). demo.py contains a fake one for offline testing.
Yahoo data can be delayed, incomplete, or occasionally wrong - the report says so.
"""
import time
import pandas as pd

SECTOR_ETFS = {
    "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Industrials": "XLI",
    "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB", "Communication Services": "XLC",
}
BENCHMARK = "SPY"


def _retry(fn, tries=3, wait=2.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # network hiccups, rate limits
            last = e
            time.sleep(wait * (i + 1))
    raise last


class YahooProvider:
    def __init__(self):
        import yfinance as yf  # imported here so offline tests don't need it
        self.yf = yf
        self._tickers = {}

    def _t(self, ticker):
        if ticker not in self._tickers:
            self._tickers[ticker] = self.yf.Ticker(ticker)
        return self._tickers[ticker]

    # ---------- prices ----------
    def prices(self, tickers, period="1y", chunk=150):
        out = {}
        tickers = list(dict.fromkeys(tickers))
        for i in range(0, len(tickers), chunk):
            part = tickers[i:i + chunk]
            try:
                df = _retry(lambda: self.yf.download(
                    part, period=period, interval="1d", auto_adjust=True,
                    group_by="ticker", threads=True, progress=False))
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for t in part:
                try:
                    sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                    sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    if len(sub) > 30:
                        sub.index = pd.to_datetime(sub.index).tz_localize(None)
                        out[t] = sub
                except Exception:
                    continue
        return out

    # ---------- company data ----------
    def market_cap(self, ticker):
        try:
            return float(_retry(lambda: self._t(ticker).fast_info["market_cap"], tries=2))
        except Exception:
            return None

    def info(self, ticker):
        try:
            return _retry(lambda: self._t(ticker).info, tries=2) or {}
        except Exception:
            return {}

    def earnings(self, ticker):
        try:
            df = _retry(lambda: self._t(ticker).get_earnings_dates(limit=16), tries=2)
        except Exception:
            return None
        if df is None or df.empty:
            return None
        cols = {c.lower(): c for c in df.columns}
        def pick(sub):
            for k, v in cols.items():
                if sub in k:
                    return df[v]
            return pd.Series(index=df.index, dtype=float)
        out = pd.DataFrame({
            "estimate": pick("estimate"),
            "reported": pick("reported"),
            "surprise_pct": pick("surprise"),
        })
        return out.sort_index()

    def news(self, ticker, limit=8):
        try:
            raw = _retry(lambda: self._t(ticker).news, tries=2) or []
        except Exception:
            return []
        items = []
        for n in raw[:limit]:
            c = n.get("content", n)  # newer yfinance nests under "content"
            title = c.get("title")
            if not title:
                continue
            link = ((c.get("canonicalUrl") or {}).get("url")
                    or (c.get("clickThroughUrl") or {}).get("url") or n.get("link"))
            pub = (c.get("provider") or {}).get("displayName") or n.get("publisher")
            when = c.get("pubDate") or n.get("providerPublishTime")
            if isinstance(when, (int, float)):
                when = pd.Timestamp(when, unit="s", tz="UTC").isoformat()
            items.append({"title": title, "publisher": pub, "link": link, "time": when})
        return items
