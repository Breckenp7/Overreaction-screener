"""Turns scan results into: an HTML email (phone-friendly), plain text, and a
short push-notification message."""
import re
from html import escape

CAT_LABEL = {
    "earnings_overreaction": "Earnings overreaction",
    "technical_support": "Technical support",
    "broad_market": "Broad-market selloff",
    "earnings_miss": "Earnings miss (likely justified?)",
    "other": "Uncategorized drop",
}
COMP_LABEL = {
    "drop_severity": "Drop size vs normal", "market_context": "Market context",
    "earnings_quality": "Earnings quality", "fundamentals": "Financial health",
    "historical_rebound": "Historical rebounds", "valuation": "Valuation",
    "technical_support": "Technical support",
}
DISCLAIMER = ("Research tool only - not investment advice. The score ranks what to research first; "
              "it is not a probability of a rebound. Data is from free sources (Yahoo Finance) and may be "
              "delayed or wrong. Guidance, revenue-vs-estimate and the actual reasons for a selloff are NOT "
              "captured - read the company's press release and filings before acting.")


def money(x):
    if x is None:
        return "n/a"
    return f"${x / 1e9:.1f}B" if x >= 1e9 else f"${x / 1e6:.0f}M"


def pct(x, d=1, signed=True):
    if x is None or x != x:
        return "n/a"
    return f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%"


def _hist_line(stats, label):
    if not stats or not stats.get("n"):
        return f"{label}: no comparable events found."
    parts = []
    for h in sorted(stats["horizons"], key=int):
        v = stats["horizons"][h]
        parts.append(f"{h}d median {pct(v['median_return'])} (beat SPY {v['win_rate_vs_spy'] * 100:.0f}%)")
    rec = stats.get("recovered_within_60d_rate")
    extra = f"; back to pre-drop price within 60d: {rec * 100:.0f}%" if rec is not None else ""
    return (f"{label} (n={stats['n']}, {stats.get('first_date', '?')} to {stats.get('last_date', '?')}): "
            + "; ".join(parts) + extra)


def candidate_text(c, rank):
    d, s = c["drop"], c["score"]
    lines = [f"#{rank} {c['ticker']} - {c['name']}  |  Score {s['score']:.0f}/100  |  {CAT_LABEL.get(c['category'], c['category'])}",
             f"   Market cap {money(c['market_cap'])}; {pct(d['return'])} over {d['type'].replace('_', ' ')} to {d['date'].date()}"
             + (" (INTRADAY - day not finished)" if c["partial"] else ""),
             f"   Score uses {s['coverage_pct']:.0f}% of rubric. " + "; ".join(
                 f"{COMP_LABEL[b['component']]} {b['points']:.0f}/{b['max_points']:.0f}"
                 for b in s["breakdown"] if b["points"] is not None)]
    for pts, why in s["penalties"]:
        lines.append(f"   Penalty -{pts}: {why}")
    e = c["earnings"]
    if e:
        lines.append(f"   Earnings: EPS {e['eps_reported']} vs est {e['eps_estimate']} "
                     f"({e['eps_surprise_pct'] if e['eps_surprise_pct'] is not None else 'n/a'}% surprise). Guidance: not available - check release.")
    for a in c["counterarguments"][:4]:
        lines.append(f"   ! {a}")
    return "\n".join(lines)


def build_text(result, cfg, mode_label, now_label):
    top = result["candidates"][:cfg["report"]["top_n"]]
    out = [f"OVERREACTION SCREENER - {mode_label} scan, {now_label}",
           f"Scanned {result['stats'].get('tickers_with_data', 0)} stocks; {result['stats'].get('flagged_before_size_filter', 0)} fell past threshold; "
           f"{len(result['candidates'])} qualified.", ""]
    for w in result["warnings"][:8]:
        out.append("WARNING: " + w)
    if not top:
        out.append("No candidates met your criteria this scan.")
    for i, c in enumerate(top, 1):
        out += [candidate_text(c, i), ""]
    out.append(DISCLAIMER)
    return "\n".join(out)


def push_summary(result, cfg):
    """Short text for phone notification: top N one-liners."""
    n = cfg["report"]["alert_top_n"]
    top = result["candidates"][:n]
    lines = []
    for c in top:
        d = c["drop"]
        lines.append(f"{c['ticker']} {pct(d['return'], 0)} | score {c['score']['score']:.0f} | "
                     f"{CAT_LABEL.get(c['category'], '')}")
    return "\n".join(lines)


# ---------------- HTML ----------------
CSS = """
body{margin:0;padding:12px;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111;font-size:15px;line-height:1.4}
.card{background:#fff;border-radius:10px;padding:14px;margin:0 auto 14px;max-width:640px;border:1px solid #e5e7eb}
h1{font-size:19px;margin:0 0 4px}h2{font-size:17px;margin:0}
.muted{color:#6b7280;font-size:13px}.score{float:right;font-size:26px;font-weight:700;color:#0f766e}
.tag{display:inline-block;background:#e0f2fe;color:#075985;border-radius:6px;padding:1px 7px;font-size:12px;margin-right:4px}
.warn{background:#fef3c7;color:#92400e;border-radius:8px;padding:8px;margin:8px 0;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:3px 4px;text-align:left;border-bottom:1px solid #f0f0f0}
.bar{background:#e5e7eb;border-radius:4px;height:8px}.fill{background:#14b8a6;height:8px;border-radius:4px}
ul{padding-left:18px;margin:4px 0}a{color:#0369a1}
"""


def _bar(points, maxp):
    w = 0 if not maxp else max(0, min(100, points / maxp * 100))
    return f'<div class="bar"><div class="fill" style="width:{w:.0f}%"></div></div>'


def _hist_table(same):
    rows = same.get("last_five") or []
    if not rows:
        return "<p class='muted'>No comparable past drops for this stock in the data window.</p>"
    hs = [k for k in rows[0] if re.fullmatch(r"r\d+", k)]
    head = "".join(f"<th>{k[1:]}d</th>" for k in hs)
    body = "".join(
        f"<tr><td>{r['date']}</td><td>{r['drop_pct']:.1f}%</td>"
        + "".join(f"<td>{r[k]:+.1f}%</td>" for k in hs)
        + f"<td>{r['recovery_days'] if r['recovery_days'] else '>60'}</td></tr>" for r in rows)
    return (f"<table><tr><th>Date</th><th>Drop</th>{head}<th>Days to recover</th></tr>{body}</table>"
            f"<p class='muted'>Returns after {int(round(same.get('threshold_pct', 0)))}%+ drops, measured from that day's close, "
            f"after assumed costs. n={same['n']} total ({same.get('pending_excluded', 0)} too recent to measure).</p>")


def candidate_html(c, rank):
    d, s, info = c["drop"], c["score"], c["info"]
    e = c["earnings"]
    parts = [f'<div class="card"><span class="score">{s["score"]:.0f}</span>',
             f'<h2>#{rank} {escape(c["ticker"])} <span class="muted">{escape(str(c["name"]))}</span></h2>',
             f'<p><span class="tag">{CAT_LABEL.get(c["category"], c["category"])}</span>'
             + "".join(f'<span class="tag">{CAT_LABEL.get(x, x)}</span>' for x in c["categories"][1:]) + "</p>",
             f'<p><b>{pct(d["return"])}</b> over {d["type"].replace("_", " ")} to {d["date"].date()} '
             f'&middot; cap {money(c["market_cap"])} &middot; sector {escape(str(c["sector"] or "n/a"))}</p>']
    if c["partial"]:
        parts.append('<div class="warn">Intraday reading: the trading day isn\'t finished, so this move can change by the close.</div>')
    dc = c["decomp"]
    parts.append(f'<p class="muted">S&amp;P 500 same period {pct(dc["spy_return"])}; sector ETF {pct(dc["sector_return"])}; '
                 f'company-specific part of the move {pct(dc["idiosyncratic_return"])} (beta {dc["beta"]:.2f})'
                 + (f'; volume {c["volume_ratio"]:.1f}x normal' if c["volume_ratio"] else '') + '</p>')
    # catalyst
    if e:
        parts.append(f'<p><b>Catalyst - earnings:</b> EPS {e["eps_reported"]} vs estimate {e["eps_estimate"]} '
                     f'({"n/a" if e["eps_surprise_pct"] is None else format(e["eps_surprise_pct"], "+.1f") + "%"} surprise). '
                     f'<i>Guidance and revenue vs. estimate: not in free data - check the press release.</i></p>')
    elif not c["earnings_data_available"]:
        parts.append('<p class="muted">Earnings data unavailable for this ticker - could not check whether earnings caused the drop.</p>')
    else:
        parts.append('<p class="muted">No earnings release matched this drop day.</p>')
    if c["support"]:
        sp = c["support"]
        parts.append(f'<p><b>Support:</b> price is {abs(sp["distance_pct"]):.1f}% from ${sp["level"]:.2f}, '
                     f'which held {sp["bounces"]} times (avg bounce {sp["avg_bounce_pct"]:.1f}%; last: {", ".join(sp["dates"][-3:])}).</p>')
    # score
    parts.append(f'<p><b>Score breakdown</b> <span class="muted">(uses {s["coverage_pct"]:.0f}% of rubric; category multiplier {s["category_multiplier"]})</span></p><table>')
    for b in s["breakdown"]:
        if b["points"] is None:
            parts.append(f'<tr><td>{COMP_LABEL[b["component"]]}</td><td colspan="2" class="muted">not scored - {escape(b["note"])}</td></tr>')
        else:
            parts.append(f'<tr><td>{COMP_LABEL[b["component"]]}</td><td style="width:90px">{_bar(b["points"], b["max_points"])}</td>'
                         f'<td>{b["points"]:.0f}/{b["max_points"]:.0f} <span class="muted">{escape(b["note"])}</span></td></tr>')
    for pts, why in s["penalties"]:
        parts.append(f'<tr><td>Penalty</td><td></td><td>-{pts} <span class="muted">{escape(why)}</span></td></tr>')
    parts.append("</table>")
    # fundamentals
    f = [("Rev growth", pct(info.get("revenueGrowth"))), ("Net margin", pct(info.get("profitMargins"), signed=False)),
         ("Fwd P/E", "n/a" if not info.get("forwardPE") else f'{info["forwardPE"]:.1f}'),
         ("Analyst target", "n/a" if not info.get("targetMeanPrice") else f'${info["targetMeanPrice"]:.2f}'),
         ("Rating", str(info.get("recommendationKey") or "n/a"))]
    parts.append('<p class="muted">' + " &middot; ".join(f"{k}: {v}" for k, v in f) + "</p>")
    # counterarguments
    parts.append("<p><b>Why this selloff might be justified</b></p><ul>" + "".join(f"<li>{escape(a)}</li>" for a in c["counterarguments"]) + "</ul>")
    # history
    parts.append("<p><b>Last similar drops for this stock</b></p>" + _hist_table(c["same_history"]))
    p = c["pooled"]
    if p and p.get("n"):
        h20 = (p["horizons"].get("20") or p["horizons"].get(20) or {})
        parts.append(f'<p class="muted"><b>Across many stocks</b> ({c["pooled_bucket"].replace("_", " ")}; n={p["n"]}, {p.get("distinct_dates", "?")} distinct dates): '
                     f'20-day median {pct(h20.get("median_return"))}, beat SPY {h20.get("win_rate_vs_spy", 0) * 100:.0f}% of the time. '
                     f'Survivorship-biased (likely flattering).</p>')
    else:
        parts.append('<p class="muted">Pooled cross-stock statistics not available yet (run the weekly pool job).</p>')
    # news
    if c["news"]:
        parts.append("<p><b>Recent headlines</b></p><ul>" + "".join(
            f'<li><a href="{escape(n.get("link") or "#")}">{escape(n["title"])}</a> <span class="muted">{escape(str(n.get("publisher") or ""))}</span></li>'
            for n in c["news"]) + "</ul>")
    else:
        parts.append('<p class="muted">No headlines returned by the data source.</p>')
    parts.append("</div>")
    return "".join(parts)


def build_html(result, cfg, mode_label, now_label):
    top = result["candidates"][:cfg["report"]["top_n"]]
    st = result["stats"]
    head = (f'<div class="card"><h1>Overreaction Screener</h1><div class="muted">{mode_label} scan &middot; {now_label}</div>'
            f'<p>Scanned {st.get("tickers_with_data", 0)} stocks &middot; {st.get("flagged_before_size_filter", 0)} fell past your threshold &middot; '
            f'<b>{len(result["candidates"])}</b> qualified (cap &ge; ${cfg["universe"]["min_market_cap_billions"]}B).</p>'
            + "".join(f'<div class="warn">{escape(w)}</div>' for w in result["warnings"][:8])
            + ('' if top else '<p>No candidates met your criteria this scan.</p>') + '</div>')
    body = "".join(candidate_html(c, i) for i, c in enumerate(top, 1))
    foot = f'<div class="card muted">{escape(DISCLAIMER)}</div>'
    return f"<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>{CSS}</style></head><body>{head}{body}{foot}</body></html>"
