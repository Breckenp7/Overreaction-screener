"""Pooled study across many stocks: "when a large company fell >= X% in a day,
what did the next 5/10/20 days look like on average?"

Buckets (all use only information known on the event day - no look-ahead):
  idiosyncratic_drop   : stock fell >= threshold while SPY fell no more than 1.5%
  earnings_beat_drop   : same, and an earnings release with an EPS beat explains the day
                         (needs per-stock earnings history; slower, optional)
  market_selloff_drop  : stock fell >= 5% while SPY fell >= 2%

KNOWN BIASES (shown in the report):
  * Survivorship: the stock list is today's index membership, so companies that
    collapsed and were removed are missing. Results likely look BETTER than reality.
  * Market-selloff events cluster in a few dates (e.g. March 2020), so the effective
    sample is much smaller than the raw count. We report distinct dates.
  * Market cap is today's; stocks may have been smaller when the event happened.
"""
import json
from datetime import datetime, timezone
import numpy as np
from . import history, events
from .data import BENCHMARK


def run_pool(provider, tickers, cfg, years=10, with_earnings=True, log=print):
    h = cfg["history"]
    horizons, cost = h["horizons"], h["round_trip_cost_bps"] / 10000
    thr = cfg["detection"]["daily_drop_pct"] / 100
    log(f"Pool study: downloading {years}y of prices for {len(tickers)} tickers...")
    px = provider.prices([BENCHMARK] + tickers, period=f"{years}y")
    spy = px.get(BENCHMARK)
    if spy is None:
        raise RuntimeError("Could not download SPY benchmark data.")
    spy_close = spy["Close"]
    buckets = {"idiosyncratic_drop": [], "earnings_beat_drop": [], "market_selloff_drop": []}
    dates = {k: set() for k in buckets}
    used = 0
    for t in tickers:
        df = px.get(t)
        if df is None or len(df) < 300:
            continue
        used += 1
        close = df["Close"]
        idio = history.find_events(close, thr, h["cooldown_days"], spy_close, spy_floor=-0.015)
        mkt = history.find_events(close, 0.05, h["cooldown_days"])
        spy_ret = spy_close.pct_change().reindex(close.index)
        mkt = [i for i in mkt if spy_ret.iloc[i] <= -0.02]
        earn_df = provider.earnings(t) if with_earnings else None
        for i in idio:
            ev = history.measure_event(close, spy_close, i, horizons, cost)
            if not ev:
                continue
            buckets["idiosyncratic_drop"].append(ev)
            dates["idiosyncratic_drop"].add(ev["date"])
            m = events.match_earnings(earn_df, close.index[i], close.index) if earn_df is not None else None
            if m and m["beat"]:
                buckets["earnings_beat_drop"].append(ev)
                dates["earnings_beat_drop"].add(ev["date"])
        for i in mkt:
            ev = history.measure_event(close, spy_close, i, horizons, cost)
            if ev:
                buckets["market_selloff_drop"].append(ev)
                dates["market_selloff_drop"].add(ev["date"])
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers_used": used, "years": years, "drop_threshold_pct": thr * 100,
        "round_trip_cost_bps": h["round_trip_cost_bps"],
        "earnings_bucket_included": with_earnings,
        "caveats": ["Survivorship bias: uses today's index members; likely overstates results.",
                    "Events cluster in time; see distinct_dates.",
                    "Uses Yahoo adjusted closes; entry assumed at the event-day close."],
        "buckets": {},
    }
    for k, evs in buckets.items():
        s = history.summarize(evs, horizons)
        s["distinct_dates"] = len(dates[k])
        out["buckets"][k] = s
    return out


def save(stats, path):
    with open(path, "w") as f:
        json.dump(stats, f, indent=1, default=str)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None
