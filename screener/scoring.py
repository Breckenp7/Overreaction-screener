"""The 0-100 "overreaction score" - a research-priority score, NOT a probability
that the stock will rebound.

Each component is rated 0.0-1.0 (or None if data is missing), multiplied by its
weight from config.yaml. Missing components are dropped and the rest re-scaled,
so a candidate isn't punished for data we couldn't get - the report shows how
much of the rubric was usable ("coverage").
"""
import numpy as np

NEG_WORDS = [
    "lowers guidance", "cuts guidance", "cut guidance", "guidance cut", "lowered outlook",
    "downgrade", "downgraded", "investigation", "subpoena", "sec probe", "lawsuit",
    "fraud", "restatement", "short seller", "short report", "recall", "bankruptcy",
    "going concern", "steps down", "resigns", "profit warning", "weak outlook",
    "misses", "missed estimates", "delisting", "data breach",
]


def _clip(x, lo=0.0, hi=1.0):
    return float(min(max(x, lo), hi))


def _num(info, key):
    v = info.get(key)
    return float(v) if isinstance(v, (int, float)) and not np.isnan(v) else None


def drop_severity(drop):
    z = drop.get("z_score")
    if z is None or np.isnan(z):
        return None, "volatility unavailable"
    return _clip((z - 2) / 4), f"drop = {z:.1f}x this stock's normal daily swing"


def market_context(decomp, category):
    share = decomp["idio_share"]
    if category not in ("broad_market", "earnings_overreaction"):
        return None, "not applicable to this setup"
    if category == "broad_market":
        s = 1 - share  # more market-driven = more likely sentiment, less company-specific
        return _clip(s), f"{(1 - share) * 100:.0f}% of the fall looks market/sector-driven"
    return _clip(share), f"{share * 100:.0f}% of the fall looks company-specific"


def earnings_quality(earn, info):
    if earn is None:
        return None, "no earnings release matched this drop"
    parts, notes = [], []
    sp = earn.get("eps_surprise_pct")
    if sp is not None:
        parts.append((0.6, _clip(sp / 10) if sp > 0 else 0.0))
        notes.append(f"EPS surprise {sp:+.1f}%")
    g = _num(info, "revenueGrowth")
    if g is not None:
        parts.append((0.4, _clip(g / 0.15)))
        notes.append(f"revenue growth {g * 100:+.1f}% y/y")
    if not parts:
        return None, "earnings matched but no surprise/growth data"
    w = sum(p[0] for p in parts)
    return sum(p[0] * p[1] for p in parts) / w, "; ".join(notes)


def fundamentals(info):
    subs, notes = [], []
    g = _num(info, "revenueGrowth")
    if g is not None:
        subs.append(_clip(g / 0.15)); notes.append(f"rev growth {g * 100:+.1f}%")
    m = _num(info, "profitMargins")
    if m is not None:
        subs.append(_clip(m / 0.15)); notes.append(f"net margin {m * 100:.1f}%")
    de = _num(info, "debtToEquity")
    if de is not None:
        subs.append(_clip((300 - de) / 200)); notes.append(f"debt/equity {de:.0f}%")
    cr = _num(info, "currentRatio")
    if cr is not None:
        subs.append(_clip((cr - 0.8) / 0.7)); notes.append(f"current ratio {cr:.2f}")
    if len(subs) < 2:
        return None, "too little fundamental data"
    return float(np.mean(subs)), "; ".join(notes)


def valuation(info, price):
    subs, notes = [], []
    tgt = _num(info, "targetMeanPrice")
    if tgt and price:
        up = tgt / price - 1
        subs.append(_clip(up / 0.30)); notes.append(f"analyst mean target {up * 100:+.0f}% vs price")
    fpe = _num(info, "forwardPE")
    if fpe and fpe > 0:
        subs.append(_clip((60 - fpe) / 35)); notes.append(f"forward P/E {fpe:.1f}")
    if not subs:
        return None, "no valuation data"
    return float(np.mean(subs)), "; ".join(notes)


def historical_rebound(same, pool, horizon=20):
    """Blend of this stock's own record and the pooled record, shrunk toward
    'no edge' (50% win rate) so thin samples can't produce a high score."""
    def sub(stats):
        h = (stats or {}).get("horizons", {}).get(horizon) or (stats or {}).get("horizons", {}).get(str(horizon))
        if not h:
            return None
        return _clip((h["win_rate_vs_spy"] - 0.45) / 0.20)
    n_s = (same or {}).get("n", 0)
    n_p = (pool or {}).get("n", 0)
    s_s, s_p = sub(same), sub(pool)
    num, den, notes = 10 * 0.25, 10.0, []   # prior: 10 pseudo-events at a neutral 50% win rate
    if s_s is not None and n_s:
        num += n_s * s_s; den += n_s
        notes.append(f"own history n={n_s}")
    if s_p is not None and n_p:
        eff = min(n_p, 30)
        num += eff * s_p; den += eff
        notes.append(f"pooled n={n_p}")
    if len(notes) == 0:
        return 0.25, "no comparable history available - treated as neutral (no evidence of an edge)"
    return num / den, f"{horizon}-day win-rate vs SPY, shrunk for sample size ({', '.join(notes)})"


def technical(support):
    if support is None:
        return 0.0, "no repeated-bounce level nearby"
    return _clip(support["bounces"] / 5), (
        f"price within {abs(support['distance_pct']):.1f}% of ${support['level']:.2f}, "
        f"which held {support['bounces']} times")


def news_penalty(news, cfg):
    hits = []
    for n in news:
        t = (n.get("title") or "").lower()
        for w in NEG_WORDS:
            if w in t:
                hits.append((w, n["title"]))
                break
    pts = min(len(hits) * 4, cfg["scoring"]["max_news_penalty"])
    return pts, hits


def score_candidate(cfg, category, drop, decomp, earn, info, support, same, pool, news):
    w = cfg["scoring"]["weights"]
    comps = {
        "drop_severity": drop_severity(drop),
        "market_context": market_context(decomp, category),
        "earnings_quality": earnings_quality(earn, info),
        "fundamentals": fundamentals(info),
        "historical_rebound": historical_rebound(same, pool),
        "valuation": valuation(info, drop["last_close"]),
        "technical_support": technical(support),
    }
    avail = {k: v for k, v in comps.items() if v[0] is not None}
    wsum = sum(w[k] for k in avail)
    mult = cfg["scoring"]["category_multiplier"].get(category, cfg["scoring"]["category_multiplier"]["other"])
    breakdown = []
    total = 0.0
    for k, (s, note) in comps.items():
        if s is None:
            breakdown.append({"component": k, "weight": w[k], "points": None, "max_points": None, "note": note})
            continue
        scaled_w = w[k] / wsum * 100
        pts = s * scaled_w * mult
        total += pts
        breakdown.append({"component": k, "weight": w[k], "rating": s,
                          "points": pts, "max_points": scaled_w * mult, "note": note})
    penalties = []
    if earn is not None and earn["miss"]:
        penalties.append((cfg["scoring"]["eps_miss_penalty"], "EPS came in below estimates"))
    npts, hits = news_penalty(news, cfg)
    if npts:
        penalties.append((npts, "negative-sounding headlines: " + "; ".join(f'"{h[1]}"' for h in hits[:3])))
    final = float(np.clip(total - sum(p[0] for p in penalties), 0, 100))
    return {
        "score": round(final, 1),
        "coverage_pct": round(wsum, 0),
        "category_multiplier": mult,
        "breakdown": breakdown,
        "penalties": penalties,
        "negative_headlines": [h[1] for h in hits],
    }


def counterarguments(drop, decomp, earn, info, support, news_hits, same):
    """Rule-based reasons the selloff might be justified. Only uses data we have."""
    out = []
    if earn is not None and earn["miss"]:
        out.append("EPS was below analyst estimates.")
    if earn is not None and earn["beat"]:
        out.append("An EPS beat alone doesn't mean the report was good: guidance, revenue "
                   "and margins vs. expectations are NOT in this free data. Read the press release and call.")
    g = _num(info, "revenueGrowth")
    if g is not None and g < 0:
        out.append(f"Revenue is shrinking ({g * 100:+.1f}% y/y).")
    m = _num(info, "profitMargins")
    if m is not None and m < 0:
        out.append("The company is not currently profitable.")
    fpe = _num(info, "forwardPE")
    if fpe and fpe > 40:
        out.append(f"Valuation is still rich (forward P/E {fpe:.0f}), so expectations may have been too high.")
    tgt, price = _num(info, "targetMeanPrice"), drop["last_close"]
    if tgt and tgt < price:
        out.append("Average analyst target is below the current price.")
    de = _num(info, "debtToEquity")
    if de is not None and de > 200:
        out.append(f"High leverage (debt/equity {de:.0f}%).")
    if decomp["idio_share"] > 0.8 and not np.isnan(decomp["spy_return"]) and decomp["spy_return"] > -0.005:
        out.append("The market was calm, so this is a company-specific move - something about the company changed.")
    if news_hits:
        out.append("Recent headlines contain negative keywords (see score penalties).")
    if same.get("n", 0) < 5:
        out.append(f"Only {same.get('n', 0)} comparable past drops for this stock - too few to draw conclusions.")
    out.append("Past rebounds are not a forecast; many drops are followed by further declines.")
    return out
