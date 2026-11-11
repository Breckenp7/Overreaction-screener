"""Historical event study.

For each past day on which a stock fell by at least X%, measure what happened
over the NEXT 5/10/20 trading days, measured from that day's close. Only events
whose full forward window has already happened are used (no peeking), and the
current event is excluded. Returns are shown raw, versus SPY, and after an
assumed trading cost.
"""
import numpy as np
import pandas as pd


def find_events(close, threshold, cooldown=10, spy_close=None, spy_floor=None):
    """Indices of days where return <= -threshold (e.g. 0.07), skipping repeat
    events within `cooldown` days. If spy_floor is set (e.g. -0.015), also require
    SPY's same-day return to be >= spy_floor (i.e. a company-specific drop)."""
    ret = close.pct_change()
    mask = ret < -threshold
    if spy_close is not None and spy_floor is not None:
        spy_ret = spy_close.pct_change().reindex(close.index)
        mask &= spy_ret >= spy_floor
    idxs, last = [], -10**9
    for i in np.flatnonzero(mask.to_numpy()):
        if i - last >= cooldown:
            idxs.append(int(i))
            last = i
    return idxs


def measure_event(close, spy_close, i, horizons, cost):
    """Forward outcomes for the event on position i. Returns None if the
    longest horizon hasn't fully elapsed (avoids look-ahead / partial data)."""
    n = len(close)
    hmax = max(horizons)
    if i < 1 or i + hmax >= n:
        return None
    c0, pre = close.iloc[i], close.iloc[i - 1]
    spy_aligned = spy_close.reindex(close.index).ffill()
    s0 = spy_aligned.iloc[i]
    out = {"date": close.index[i], "drop": float(c0 / pre - 1)}
    for h in horizons:
        r = close.iloc[i + h] / c0 - 1
        sr = spy_aligned.iloc[i + h] / s0 - 1 if s0 else np.nan
        out[f"r{h}"] = float(r - cost)
        out[f"x{h}"] = float(r - sr - cost)  # excess over SPY, after cost
    window = close.iloc[i + 1:i + hmax + 1]
    out["max_adverse"] = float(window.min() / c0 - 1)
    after = close.iloc[i + 1:i + 61]
    rec = np.flatnonzero((after >= pre).to_numpy())
    out["recovery_days"] = int(rec[0] + 1) if len(rec) else None  # back to pre-drop close within 60 days
    return out


def summarize(events, horizons):
    """Aggregate a list of measured events into plain statistics."""
    s = {"n": len(events), "horizons": {}}
    if not events:
        return s
    for h in horizons:
        r = np.array([e[f"r{h}"] for e in events])
        x = np.array([e[f"x{h}"] for e in events])
        valid_x = x[np.isfinite(x)]
        s["horizons"][h] = {
            "median_return": float(np.median(r)),
            "mean_return": float(np.mean(r)),
            "win_rate": float(np.mean(r > 0)),
            "win_rate_vs_spy": float(np.mean(valid_x > 0)) if len(valid_x) else None,
            "median_excess": float(np.median(valid_x)) if len(valid_x) else None,
            "p10_return": float(np.percentile(r, 10)),
        }
    adv = np.array([e["max_adverse"] for e in events])
    s["median_max_adverse_20d"] = float(np.median(adv))
    s["worst_max_adverse_20d"] = float(adv.min())
    rec = [e["recovery_days"] for e in events]
    got = [x for x in rec if x is not None]
    s["recovered_within_60d_rate"] = len(got) / len(rec)
    s["median_days_to_recover"] = float(np.median(got)) if got else None
    s["first_date"] = min(e["date"] for e in events).strftime("%Y-%m-%d")
    s["last_date"] = max(e["date"] for e in events).strftime("%Y-%m-%d")
    return s


def same_stock_history(close, spy_close, current_drop, cfg, exclude_last_days=1):
    """Past similar drops for this stock. `current_drop` is a positive fraction."""
    h = cfg["history"]
    horizons = h["horizons"]
    cost = h["round_trip_cost_bps"] / 10000
    thr = h["min_similar_drop_pct"] / 100
    # Historical comparisons use the same configured one-session threshold as the live scan.
    thr = max(thr, cfg["detection"]["daily_drop_pct"] / 100)
    past = close.iloc[:-exclude_last_days] if exclude_last_days else close
    idxs = find_events(past, thr, h["cooldown_days"])
    events = [e for e in (measure_event(past, spy_close, i, horizons, cost) for i in idxs) if e]
    pending = len(idxs) - len(events)
    summ = summarize(events, horizons)
    summ["threshold_pct"] = thr * 100
    summ["pending_excluded"] = pending
    summ["last_five"] = [
        {"date": e["date"].strftime("%Y-%m-%d"), "drop_pct": e["drop"] * 100,
         **{f"r{k}": e[f"r{k}"] * 100 for k in horizons}, "recovery_days": e["recovery_days"]}
        for e in events[-5:]
    ]
    return summ
