#!/usr/bin/env python3
"""Run one scan.

Examples
  python run_scan.py --demo --dry-run        # fake data, no internet, no messages sent
  python run_scan.py --mode close --dry-run  # real data, but only print/save the report
  python run_scan.py --mode auto             # what the cloud schedule runs
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from screener.config import load_config, ROOT
from screener import pipeline, report, notify, rebound
from screener.universe import build_universe

ET = ZoneInfo("America/New_York")


def resolve_mode(now, mode):
    """'auto' picks open/close from the Eastern-time clock. The cloud schedule fires at
    both the winter and summer UTC times; only the one that lands in a window runs."""
    if mode != "auto":
        return mode
    minutes = now.hour * 60 + now.minute
    if 10 * 60 <= minutes < 11 * 60:
        return "open"
    if 16 * 60 + 15 <= minutes < 17 * 60 + 30:
        return "close"
    return None


def load_state(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {"runs": {}, "alerted": {}}


def save_state(path, state, today):
    cutoff = (today - timedelta(days=45)).strftime("%Y-%m-%d")
    state["runs"] = {k: v for k, v in state["runs"].items() if k.split(":")[0] >= cutoff}
    state["alerted"] = {k: v for k, v in state["alerted"].items() if k.split(":")[-1] >= cutoff}
    Path(path).write_text(json.dumps(state, indent=1, sort_keys=True))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="auto", choices=["auto", "open", "close"])
    ap.add_argument("--demo", action="store_true", help="use synthetic data (no internet)")
    ap.add_argument("--demo-selloff", action="store_true", help="demo with a broad market selloff")
    ap.add_argument("--dry-run", action="store_true", help="don't send push/email or update state")
    ap.add_argument("--force", action="store_true", help="ignore time-of-day, weekend and already-ran checks")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    now = datetime.now(ET)
    if args.demo:
        args.force = True
    mode = resolve_mode(now, args.mode)
    if mode is None and args.force:
        mode = "close"
    if mode is None:
        print(f"{now:%Y-%m-%d %H:%M} ET is outside both scan windows - nothing to do (this is normal for the duplicate schedule slot).")
        return 0
    if now.weekday() >= 5 and not args.force:
        print("Weekend - markets closed.")
        return 0

    state_path = ROOT / cfg["state_file"]
    state = load_state(state_path)
    today_key = now.strftime("%Y-%m-%d")
    run_key = f"{today_key}:{mode}"
    if run_key in state["runs"] and not args.force:
        print(f"Scan '{run_key}' already completed - skipping duplicate.")
        return 0

    try:
        if args.demo:
            from screener.demo import DemoProvider
            provider = DemoProvider(market_selloff=args.demo_selloff)
            tickers = provider.tickers()
        else:
            from screener.data import YahooProvider
            provider = YahooProvider()
            tickers, _ = build_universe(cfg, ROOT)
            if not tickers:
                raise RuntimeError("Stock universe is empty (could not download index lists and no saved copy exists).")

        probe = provider.prices(["SPY"], period="1mo" if not args.demo else "1y").get("SPY")
        if probe is None or probe.empty:
            raise RuntimeError("Could not reach the price data source (SPY probe failed).")
        last_bar = probe.index[-1].date()
        if not args.force and last_bar != now.date():
            print(f"Latest market bar is {last_bar}, not today ({now.date()}) - market holiday or data not updated. Skipping.")
            return 0

        partial = (mode == "open")
        result = pipeline.run_scan(provider, cfg, tickers, ROOT, partial=partial, log=print)
        label = "Market-open (intraday)" if partial else "Market-close"
        stamp = now.strftime("%a %b %d, %-I:%M %p ET")
        text = report.build_text(result, cfg, label, stamp)
        html = report.build_html(result, cfg, label, stamp)

        out_dir = ROOT / "output"
        out_dir.mkdir(exist_ok=True)
        base = f"report_{today_key}_{mode}"
        # Machine-readable candidate research for the Master Dashboard.
        research = {"as_of": str(result.get("stats", {}).get("latest_bar", today_key)),
                    "threshold_rule": "strictly greater than 7% close-to-close decline",
                    "universe_size": len(tickers), "flagged": result["stats"].get("flagged_before_size_filter", 0),
                    "candidates": []}
        for c in result["candidates"]:
            research["candidates"].append({
                "ticker": c["ticker"], "name": c["name"], "sector": c["sector"],
                "daily_drop_pct": round(c["drop"]["one_day_return"] * 100, 2),
                "score": round(c["score"]["score"], 1),
                "market_cap": c["market_cap"], "history": c["same_history"],
                "risks": c["counterarguments"][:4]})
        (out_dir / f"{base}_research.json").write_text(json.dumps(research, indent=2, allow_nan=False), encoding="utf-8")
        (out_dir / f"{base}.html").write_text(html, encoding="utf-8")
        (out_dir / f"{base}.txt").write_text(text, encoding="utf-8")
        reversal_text = rebound.render_text(result.get("rebound_watchlist", []), partial=partial)
        (out_dir / f"{base}_rebound_watchlist.txt").write_text(reversal_text, encoding="utf-8")
        print(reversal_text)
        print(text)
        print(f"\nSaved: output/{base}.html")

        if args.dry_run:
            print("Dry run: nothing sent, state not updated.")
            return 0

        send_all(result, cfg, state, html, text, mode, label, today_key)
        state["runs"][run_key] = datetime.utcnow().isoformat(timespec="seconds")
        save_state(state_path, state, now)
        return 0
    except Exception as e:
        traceback.print_exc()
        if not args.dry_run and not args.demo:
            notify.send_push("Screener FAILED", f"{type(e).__name__}: {e}"[:300], priority="high", tags="warning")
        return 1


def send_all(result, cfg, state, html, text, mode, label, today_key):
    cands = result["candidates"]
    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    if not result.get("data_ok", True):
        notify.send_push("Screener: data problem", result["warnings"][0][:300], priority="high", tags="warning", click_url=run_url)

    # Push: only NEW high-scoring candidates (avoid repeating the same event at the close)
    min_score = cfg["report"]["min_alert_score"]
    fresh = [c for c in cands if f"{c['ticker']}:{c['drop']['date'].date()}" not in state["alerted"]
             and c["score"]["score"] >= min_score][:cfg["report"]["alert_top_n"]]
    if fresh and result.get("data_ok", True):
        sub = dict(result, candidates=fresh)
        body = report.push_summary(sub, cfg) + "\n(Research only - open the email for details.)"
        ok = notify.send_push(f"{len(fresh)} possible overreaction{'s' if len(fresh) > 1 else ''} ({mode})", body,
                              click_url=run_url, priority="high" if fresh[0]["score"]["score"] >= 70 else "default")
        if ok:
            for c in fresh:
                state["alerted"][f"{c['ticker']}:{c['drop']['date'].date()}"] = c["score"]["score"]
    elif not cands and cfg["schedule"]["send_push_when_empty"]:
        notify.send_push(f"Screener ({mode}): nothing today", "No candidates met your criteria.")

    # Email: full ranked report
    if cands or cfg["schedule"]["send_email_when_empty"].get(mode, False):
        top = cands[0] if cands else None
        subject = (f"[Screener {mode}] {len(cands)} candidates - top {top['ticker']} {top['score']['score']:.0f}"
                   if top else f"[Screener {mode}] no candidates")
        notify.send_email(subject, html, text)


if __name__ == "__main__":
    sys.exit(main())
