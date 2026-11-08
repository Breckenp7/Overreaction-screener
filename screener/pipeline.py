"""Orchestrates one scan: download -> detect drops -> filter by size -> enrich ->
classify -> score -> rank."""
import traceback
import pandas as pd
from . import events, history, scoring, rebound, pool as poolmod
from .data import BENCHMARK, SECTOR_ETFS

INFO_KEYS = ["shortName", "sector", "revenueGrowth", "earningsGrowth", "profitMargins",
             "operatingMargins", "debtToEquity", "currentRatio", "forwardPE", "trailingPE",
             "targetMeanPrice", "recommendationKey", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"]


def run_scan(provider, cfg, tickers, root, partial=False, log=print):
    result = {"candidates": [], "warnings": [], "stats": {}}
    sector_etfs = sorted(set(SECTOR_ETFS.values()))
    log(f"Downloading prices for {len(tickers)} tickers + benchmarks...")
    px = provider.prices(list(dict.fromkeys(tickers + [BENCHMARK] + sector_etfs)), period="1y")
    spy = px.get(BENCHMARK)
    if spy is None:
        raise RuntimeError("Could not download the S&P 500 benchmark (SPY). Aborting so you aren't sent bad results.")

    got = sum(1 for t in tickers if t in px)
    coverage = got / max(len(tickers), 1)
    result["stats"].update(universe_size=len(tickers), tickers_with_data=got,
                           latest_bar=str(spy.index[-1].date()), partial_day=partial)
    if coverage < 0.8:
        result["warnings"].append(
            f"DATA QUALITY: only {got} of {len(tickers)} tickers returned prices ({coverage:.0%}). "
            "Yahoo may be rate-limiting; results below are incomplete.")
        raise RuntimeError(result["warnings"][-1] + " Aborting incomplete scan.")
    else:
        result["data_ok"] = True

    # Independent previous-session reversal watchlist. Only uses already-downloaded
    # OHLC bars and is kept separate from the original scoring rubric.
    result["rebound_watchlist"] = rebound.scan(px, tickers, cfg, partial=partial)
    result["stats"]["rebound_setups"] = len(result["rebound_watchlist"])
    result["stats"]["confirmed_reversals"] = sum(
        r["status"] == "CONFIRMED REVERSAL" for r in result["rebound_watchlist"])

    # 1) Which stocks fell enough?
    flagged = []
    for t in tickers:
        df = px.get(t)
        if df is None:
            continue
        if df.index[-1] != spy.index[-1]:  # stale: last bar isn't the latest session
            continue
        drop = events.detect_drop(df["Close"], cfg)
        if drop:
            flagged.append((t, drop))
    result["stats"]["flagged_before_size_filter"] = len(flagged)
    log(f"{len(flagged)} stocks breached the drop threshold; checking market caps...")

    # 2) Size filter (only for stocks that actually fell)
    min_cap = cfg["universe"]["min_market_cap_billions"] * 1e9
    big = []
    for t, drop in flagged:
        cap = provider.market_cap(t)
        if cap is None:
            result["warnings"].append(f"{t}: market cap unavailable - skipped.")
        elif cap >= min_cap:
            big.append((t, drop, cap))
    result["stats"]["flagged_after_size_filter"] = len(big)

    pool_stats = poolmod.load(root / cfg["pooled_stats_file"])
    result["stats"]["pooled_stats_date"] = (pool_stats or {}).get("generated_utc")

    # 3) Enrich, classify, score
    for t, drop, cap in big:
        try:
            cand = build_candidate(provider, cfg, t, drop, cap, px, spy, pool_stats, partial, log)
            if cand:
                result["candidates"].append(cand)
        except Exception as e:
            result["warnings"].append(f"{t}: skipped after error ({type(e).__name__}: {e})")
            log(traceback.format_exc())
    result["candidates"].sort(key=lambda c: c["score"]["score"], reverse=True)
    result["stats"]["candidates"] = len(result["candidates"])
    return result


def build_candidate(provider, cfg, t, drop, cap, px, spy, pool_stats, partial, log):
    long_df = provider.prices([t], period=f"{cfg['history']['years']}y").get(t)
    df = long_df if long_df is not None and len(long_df) > len(px[t]) else px[t]
    close = df["Close"]
    info_full = provider.info(t)
    info = {k: info_full.get(k) for k in INFO_KEYS}
    sector_etf = SECTOR_ETFS.get(info.get("sector"))
    sector_close = px[sector_etf]["Close"] if sector_etf in px else None

    decomp = events.decompose(drop, close, spy["Close"], sector_close)
    decomp["sector_etf"] = sector_etf
    earn_df = provider.earnings(t)
    earn = events.match_earnings(earn_df, drop["date"], close.index)
    support = events.find_support(df, cfg)
    cats = events.classify(drop, decomp, earn, support, cfg)
    if not cats:
        if cfg["detection"]["include_uncategorized"]:
            cats = ["other"]
        else:
            return None
    primary = cats[0]

    same = history.same_stock_history(close, spy["Close"], abs(drop["one_day_return"] if drop["horizon"] == 1 else drop["return"]) , cfg)
    bucket_name = {"earnings_overreaction": "earnings_beat_drop",
                   "broad_market": "market_selloff_drop"}.get(primary, "idiosyncratic_drop")
    pooled = ((pool_stats or {}).get("buckets") or {}).get(bucket_name)
    if bucket_name == "earnings_beat_drop" and (not pooled or pooled.get("n", 0) < 20):
        bucket_name = "idiosyncratic_drop"
        pooled = ((pool_stats or {}).get("buckets") or {}).get(bucket_name)

    news = provider.news(t)
    sc = scoring.score_candidate(cfg, primary, drop, decomp, earn, info, support, same, pooled, news)
    counters = scoring.counterarguments(drop, decomp, earn, info, support, sc["negative_headlines"], same)
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    vol_ratio = None if partial or not avg_vol else float(df["Volume"].iloc[-1] / avg_vol)
    return {
        "ticker": t, "name": info.get("shortName") or t, "sector": info.get("sector"),
        "market_cap": cap, "drop": drop, "decomp": decomp, "categories": cats, "category": primary,
        "earnings": earn, "earnings_data_available": earn_df is not None,
        "support": support, "info": info, "same_history": same,
        "pooled_bucket": bucket_name, "pooled": pooled,
        "news": news[:cfg["report"]["news_items"]], "score": sc, "counterarguments": counters,
        "volume_ratio": vol_ratio, "partial": partial,
    }
