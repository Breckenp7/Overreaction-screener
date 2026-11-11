"""Finds sharp declines and works out what kind of situation each one is."""
import numpy as np
import pandas as pd


def pct_change_over(close, n):
    """Return over the last n trading days (n=1 -> latest day)."""
    if len(close) <= n:
        return np.nan
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


def detect_drop(close, cfg):
    """Return a dict describing the drop if the latest bar breaches a threshold."""
    d = cfg["detection"]
    if len(close) < 80:
        return None
    r1 = pct_change_over(close, 1)
    # STRICT: a drop of exactly the configured threshold does not qualify; five-day declines never qualify.
    if not np.isfinite(r1) or not r1 < -d["daily_drop_pct"] / 100:
        return None
    horizon = 1
    ret = r1
    daily = close.pct_change().dropna()
    vol = float(daily.iloc[-61:-1].std()) if len(daily) > 61 else float(daily.std())
    z = abs(ret) / (vol * np.sqrt(horizon)) if vol > 0 else np.nan
    return {
        "type": "single_day",
        "horizon": horizon,
        "return": ret,
        "one_day_return": r1,
        "date": close.index[-1],
        "daily_vol": vol,
        "z_score": float(z),
        "last_close": float(close.iloc[-1]),
    }


def estimate_beta(stock_close, mkt_close, skip_last=5, lookback=250):
    s = stock_close.pct_change()
    m = mkt_close.pct_change()
    df = pd.concat([s, m], axis=1, join="inner").dropna().iloc[:-skip_last].iloc[-lookback:]
    if len(df) < 60 or df.iloc[:, 1].var() == 0:
        return 1.0
    beta = df.iloc[:, 0].cov(df.iloc[:, 1]) / df.iloc[:, 1].var()
    return float(np.clip(beta, 0.3, 2.5))


def decompose(drop, stock_close, spy_close, sector_close=None):
    """Split the move into market-driven and company-specific parts."""
    h = drop["horizon"]
    spy_ret = pct_change_over(spy_close, h)
    sec_ret = pct_change_over(sector_close, h) if sector_close is not None else np.nan
    beta = estimate_beta(stock_close, spy_close)
    ret = drop["return"]
    market_part = beta * spy_ret if not np.isnan(spy_ret) else 0.0
    idio = ret - market_part
    share = idio / ret if ret != 0 else 0.0  # share of the fall that is company-specific
    return {
        "beta": beta, "spy_return": spy_ret, "sector_return": sec_ret,
        "idiosyncratic_return": idio,
        "idio_share": float(np.clip(share, 0, 1)),
        "vs_sector": ret - sec_ret if not np.isnan(sec_ret) else np.nan,
    }


def market_selloff(decomp, cfg):
    b = cfg["categories"]["broad_market"]
    spy_hit = (not np.isnan(decomp["spy_return"])) and decomp["spy_return"] <= -b["spy_drop_pct"] / 100
    sec_hit = (not np.isnan(decomp["sector_return"])) and decomp["sector_return"] <= -b["sector_drop_pct"] / 100
    return spy_hit or sec_hit


# ---------------- earnings matching ----------------
def reaction_date(ts, trading_days):
    """Which trading day first reflects an earnings release stamped `ts`?
    After-close releases (>=16:00 ET) react next day; pre-market releases react the
    same day. A midnight timestamp means 'time unknown' -> we return both days."""
    ts = pd.Timestamp(ts)
    day = ts.tz_localize(None).normalize() if ts.tzinfo is None else ts.tz_convert("America/New_York").tz_localize(None).normalize()
    hour = ts.hour if ts.tzinfo is None else ts.tz_convert("America/New_York").hour
    idx = trading_days.searchsorted(day)
    cands = []
    if idx < len(trading_days):
        same = trading_days[idx]
        nxt = trading_days[idx + 1] if idx + 1 < len(trading_days) else None
        if hour >= 16:
            cands = [nxt] if nxt is not None else []
        elif hour == 0:
            cands = [same] + ([nxt] if nxt is not None else [])
        else:
            cands = [same]
    return [c for c in cands if c is not None]


def match_earnings(earn_df, drop_date, trading_days):
    """Return info about an earnings release that explains the drop, or None."""
    if earn_df is None or earn_df.empty:
        return None
    for ts, row in earn_df.iterrows():
        if pd.isna(row.get("reported")):
            continue  # future / not yet reported
        if pd.Timestamp(drop_date).normalize() in [pd.Timestamp(c).normalize() for c in reaction_date(ts, trading_days)]:
            est, rep = row.get("estimate"), row.get("reported")
            sp = row.get("surprise_pct")
            if pd.isna(sp) and not pd.isna(est) and est != 0:
                sp = (rep - est) / abs(est) * 100
            return {
                "release_time": pd.Timestamp(ts).isoformat(),
                "eps_estimate": None if pd.isna(est) else float(est),
                "eps_reported": float(rep),
                "eps_surprise_pct": None if sp is None or pd.isna(sp) else float(sp),
                "beat": (not pd.isna(sp)) and sp > 0,
                "miss": (not pd.isna(sp)) and sp < 0,
            }
    return None


# ---------------- technical support ----------------
def find_support(df, cfg):
    """Look for a price level (~2 years of history) where the stock repeatedly
    bottomed and bounced, and report it if today's price is near it."""
    t = cfg["categories"]["technical_support"]
    if len(df) < 250:
        return None
    df = df.iloc[-504:]
    low, close = df["Low"].to_numpy(), df["Close"].to_numpy()
    k, n = 5, len(df)
    swings = []
    for i in range(k, n - k):
        if low[i] == low[i - k:i + k + 1].min():
            bounce = close[i + 1:i + 11].max() / low[i] - 1 if i + 1 < n else 0
            swings.append((i, low[i], bounce))
    tol = t["tolerance_pct"] / 100
    swings.sort(key=lambda x: x[1])
    clusters, cur = [], []
    for s in swings:
        if cur and s[1] > cur[0][1] * (1 + tol):
            clusters.append(cur); cur = []
        cur.append(s)
    if cur:
        clusters.append(cur)
    last = float(close[-1])
    best = None
    for c in clusters:
        good = [s for s in c if s[2] >= t["min_bounce_pct"] / 100 and s[0] < n - 6]
        if len(good) < t["min_touches"]:
            continue
        level = float(np.median([s[1] for s in c]))
        if abs(last / level - 1) <= t["near_level_pct"] / 100:
            cand = {"level": level, "touches": len(c), "bounces": len(good),
                    "avg_bounce_pct": float(np.mean([s[2] for s in good]) * 100),
                    "dates": [df.index[s[0]].strftime("%Y-%m-%d") for s in good[-5:]],
                    "distance_pct": (last / level - 1) * 100}
            if best is None or cand["bounces"] > best["bounces"]:
                best = cand
    return best


def classify(drop, decomp, earnings, support, cfg):
    """Return the list of categories that apply (primary first)."""
    cats = []
    if earnings is not None and earnings["miss"] and not cfg["detection"]["include_earnings_misses"]:
        return []  # EPS missed estimates: the selloff is plausibly justified, so hide it by default
    if earnings is not None and not earnings["miss"]:
        cats.append("earnings_overreaction")
    if market_selloff(decomp, cfg) and abs(drop["return"]) * 100 >= cfg["categories"]["broad_market"]["min_stock_drop_pct"]:
        cats.append("broad_market")
    if support is not None:
        cats.append("technical_support")
    if earnings is not None and earnings["miss"] and cfg["detection"]["include_earnings_misses"]:
        cats.append("earnings_miss")
    return cats
