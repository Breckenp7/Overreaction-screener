#!/usr/bin/env python3
"""Weekly job: builds data/pool_stats.json (pooled cross-stock event study).
  python run_pool.py --demo          # fake data
  python run_pool.py                 # real data (takes several minutes)
  python run_pool.py --no-earnings   # faster; skips the earnings-beat bucket
"""
import argparse
from screener.config import load_config, ROOT
from screener import pool
from screener.universe import build_universe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-earnings", action="store_true")
    ap.add_argument("--max-tickers", type=int, default=0, help="limit for quick tests")
    args = ap.parse_args()
    cfg = load_config()
    if args.demo:
        from screener.demo import DemoProvider
        provider = DemoProvider(); tickers = provider.tickers(); years = 10
    else:
        from screener.data import YahooProvider
        provider = YahooProvider(); tickers, _ = build_universe(cfg, ROOT); years = cfg["history"]["years"]
    if args.max_tickers:
        tickers = tickers[:args.max_tickers]
    stats = pool.run_pool(provider, tickers, cfg, years=years, with_earnings=not args.no_earnings)
    out = ROOT / ("data/pool_stats_demo.json" if args.demo else cfg["pooled_stats_file"])
    pool.save(stats, out)
    for k, v in stats["buckets"].items():
        print(f"{k}: n={v['n']}, distinct dates={v.get('distinct_dates')}")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
