#!/usr/bin/env python3
"""Run the Overreaction Screener and send stock reports to ntfy."""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from screener.config import load_config, ROOT
from screener import pipeline, report, notify, rebound
from screener.universe import build_universe


ET = ZoneInfo("America/New_York")

DASHBOARD_URL = (
    "https://breckenp7.github.io/Overreaction-screener/"
)


def resolve_mode(now, mode):
    """Select morning or afternoon scan using Eastern time."""
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
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Invalid state format")

        state.setdefault("runs", {})
        state.setdefault("alerted", {})
        return state

    except (FileNotFoundError, ValueError, TypeError):
        return {"runs": {}, "alerted": {}}


def save_state(path, state, today):
    """Save recent scan history safely."""
    if isinstance(today, datetime):
        today = today.date()

    cutoff = (today - timedelta(days=45)).isoformat()

    state["runs"] = {
        k: v
        for k, v in state.get("runs", {}).items()
        if k.split(":")[0] >= cutoff
    }

    state["alerted"] = {
        k: v
        for k, v in state.get("alerted", {}).items()
        if k.split(":")[-1] >= cutoff
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def send_all(result, cfg, state, html, text, mode, label, today_key):
    """Send a stock report to ntfy after every completed scan."""
    candidates = result.get("candidates", [])
    stats = result.get("stats", {})

    scanned = stats.get("scanned")
    if scanned is None:
        scanned = stats.get("universe_size", "N/A")

    title = f"Stock Screener - {mode.title()} Report"

    lines = [
        f"Date: {today_key}",
        f"Stocks scanned: {scanned}",
        f"Qualified stocks: {len(candidates)}",
        "",
    ]

    if candidates:
        lines.append("Today's opportunities:")

        for candidate in candidates[:10]:
            ticker = candidate["ticker"]
            drop = candidate["drop"]["one_day_return"] * 100
            score = candidate["score"]["score"]

            lines.append(
                f"{ticker}: {drop:.1f}% | Score {score:.0f}"
            )

        if len(candidates) > 10:
            lines.append(
                f"...and {len(candidates) - 10} more."
            )
    else:
        lines.append("No stocks met your criteria this scan.")

    if not result.get("data_ok", True):
        lines.extend([
            "",
            "Warning: Some market data may be incomplete.",
        ])

    lines.extend([
        "",
        "Research only - not investment advice.",
        "Tap to open the full dashboard.",
    ])

    body = "\n".join(lines)

    try:
        sent = notify.send_push(
            title,
            body,
            click_url=DASHBOARD_URL,
            priority="default",
            tags="chart_with_downwards_trend",
        )

        if sent:
            print("Stock report push delivered.")
        else:
            print("Warning: Stock report push not delivered.")

    except Exception as exc:
        print(
            f"Warning: Push notification failed: {exc}"
        )

    # Email is optional. No Yahoo/Gmail setup required.
    if (
        os.environ.get("EMAIL_USER")
        and os.environ.get("EMAIL_APP_PASSWORD")
    ):
        try:
            notify.send_email(title, html, text)
        except Exception as exc:
            print(f"Warning: Email failed: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "open", "close"],
    )
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--demo-selloff", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--config", default=None)

    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    now = datetime.now(ET)

    if args.demo:
        args.force = True

    mode = resolve_mode(now, args.mode)

    if mode is None and args.force:
        mode = "close"

    if mode is None:
        print("Outside scheduled scan windows. Skipping.")
        return 0

    if now.weekday() >= 5 and not args.force:
        print("Weekend - markets closed.")
        return 0

    state_path = ROOT / cfg["state_file"]
    state = load_state(state_path)

    today_key = now.strftime("%Y-%m-%d")
    run_key = f"{today_key}:{mode}"

    if run_key in state["runs"] and not args.force:
        print(f"Scan {run_key} already completed.")
        return 0

    try:
        if args.demo:
            from screener.demo import DemoProvider

            provider = DemoProvider(
                market_selloff=args.demo_selloff
            )
            tickers = provider.tickers()

        else:
            from screener.data import YahooProvider

            provider = YahooProvider()
            tickers, _ = build_universe(cfg, ROOT)

            if not tickers:
                raise RuntimeError(
                    "Stock universe is empty."
                )

        probe = provider.prices(
            ["SPY"],
            period="1y" if args.demo else "1mo",
        ).get("SPY")

        if probe is None or probe.empty:
            raise RuntimeError(
                "Could not reach the market data source."
            )

        last_bar = probe.index[-1].date()

        if not args.force and last_bar != now.date():
            print(
                f"Latest market bar is {last_bar}, "
                f"not {now.date()}. Skipping."
            )
            return 0

        partial = mode == "open"

        result = pipeline.run_scan(
            provider,
            cfg,
            tickers,
            ROOT,
            partial=partial,
            log=print,
        )

        label = (
            "Market-open (intraday)"
            if partial
            else "Market-close"
        )

        stamp = now.strftime(
            "%a %b %d, %-I:%M %p ET"
        )

        text = report.build_text(
            result, cfg, label, stamp
        )

        html = report.build_html(
            result, cfg, label, stamp
        )

        out_dir = ROOT / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        base = f"report_{today_key}_{mode}"

        research = {
            "as_of": str(
                result.get("stats", {}).get(
                    "latest_bar", today_key
                )
            ),
            "threshold_rule": (
                "strictly greater than 7% "
                "close-to-close decline"
            ),
            "universe_size": len(tickers),
            "flagged": result["stats"].get(
                "flagged_before_size_filter", 0
            ),
            "candidates": [],
        }

        for candidate in result["candidates"]:
            research["candidates"].append({
                "ticker": candidate["ticker"],
                "name": candidate["name"],
                "sector": candidate["sector"],
                "daily_drop_pct": round(
                    candidate["drop"]["one_day_return"] * 100,
                    2,
                ),
                "score": round(
                    candidate["score"]["score"], 1
                ),
                "market_cap": candidate["market_cap"],
                "history": candidate["same_history"],
                "score_breakdown": candidate["score"][
                    "breakdown"
                ],
                "score_coverage_pct": candidate["score"][
                    "coverage_pct"
                ],
                "risks": candidate["counterarguments"][:4],
            })

        (out_dir / f"{base}_research.json").write_text(
            json.dumps(
                research,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        (out_dir / f"{base}.html").write_text(
            html,
            encoding="utf-8",
        )

        (out_dir / f"{base}.txt").write_text(
            text,
            encoding="utf-8",
        )

        reversal_text = rebound.render_text(
            result.get("rebound_watchlist", []),
            partial=partial,
        )

        (
            out_dir / f"{base}_rebound_watchlist.txt"
        ).write_text(
            reversal_text,
            encoding="utf-8",
        )

        print(reversal_text)
        print(text)
        print(f"\nSaved: output/{base}.html")

        if args.dry_run:
            print(
                "Dry run: no notifications sent "
                "and state not updated."
            )
            return 0

        # Send the stock report, including on zero-candidate days.
        send_all(
            result,
            cfg,
            state,
            html,
            text,
            mode,
            label,
            today_key,
        )

        state["runs"][run_key] = datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")

        # State persistence should not prevent dashboard publishing.
        try:
            save_state(
                state_path,
                state,
                now.date(),
            )
        except Exception as exc:
            print(
                f"Warning: Could not save scan state: {exc}"
            )

        return 0

    except Exception as exc:
        traceback.print_exc()

        if not args.dry_run and not args.demo:
            try:
                notify.send_push(
                    "Screener FAILED",
                    f"{type(exc).__name__}: {exc}"[:300],
                    priority="high",
                    tags="warning",
                )
            except Exception:
                pass

        return 1


if __name__ == "__main__":
    sys.exit(main())
