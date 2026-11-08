"""Short-term reversal watchlist using only observed OHLC bars.

A prior-session selloff is a setup, not an entry. A confirmation is a
rule-based research signal, not a validated prediction or trading order.
"""
import math
import pandas as pd
from .events import detect_drop


def evaluate(df, cfg, partial=False):
    """Evaluate latest session against the previous session's selloff.

    On a partial day, daily Yahoo OHLC bars can be incomplete; never label
    an intraday signal confirmed. Requires at least 82 bars.
    """
    if df is None or len(df) < 82:
        return None
    prior = df.iloc[:-1]
    drop = detect_drop(prior['Close'], cfg)
    if not drop:
        return None
    prev, cur = df.iloc[-2], df.iloc[-1]
    vals = [prev['High'], prev['Low'], prev['Close'], cur['Close'], cur['High'], cur['Low']]
    if not all(math.isfinite(float(v)) and float(v) > 0 for v in vals):
        return None
    # Confirmation deliberately uses CLOSE above the previous high, not an
    # intraday touch. This avoids claiming a breakout before the bar closes.
    close_breakout = float(cur['Close']) > float(prev['High'])
    higher_low = float(cur['Low']) > float(prev['Low'])
    positive_close = float(cur['Close']) > float(prev['Close'])
    confirmed = close_breakout and higher_low and positive_close and not partial
    invalidated = float(cur['Close']) < float(prev['Low']) and not partial
    status = 'CONFIRMED REVERSAL' if confirmed else ('INVALIDATED' if invalidated else 'WATCHLIST')
    return {
        'status': status, 'setup_date': str(df.index[-2].date()),
        'signal_date': str(df.index[-1].date()), 'setup_drop_pct': round(100 * drop['return'], 2),
        'close': round(float(cur['Close']), 2), 'prior_high': round(float(prev['High']), 2),
        'prior_low': round(float(prev['Low']), 2),
        'higher_low': higher_low, 'positive_close': positive_close,
        'close_breakout': close_breakout, 'partial': partial,
    }


def scan(prices, tickers, cfg, partial=False):
    found = []
    for ticker in tickers:
        item = evaluate(prices.get(ticker), cfg, partial)
        if item:
            found.append({'ticker': ticker, **item})
    order = {'CONFIRMED REVERSAL': 0, 'WATCHLIST': 1, 'INVALIDATED': 2}
    return sorted(found, key=lambda x: (order[x['status']], x['setup_drop_pct']))


def render_text(rows, partial=False):
    title = 'SHORT-TERM REBOUND CONFIRMATION (1-5 DAY RESEARCH WATCHLIST)'
    out = [title, 'Requires a prior-session threshold decline; confirmation = completed close above prior high AND higher low.',
           'Intraday bars never count as confirmed. This is not a backtested probability or investment recommendation.',
           f'Previous-session setups: {len(rows)}; confirmed: {sum(x["status"] == "CONFIRMED REVERSAL" for x in rows)}', '']
    for r in rows[:50]:
        out.append(f'{r["ticker"]}: {r["status"]} | prior decline {r["setup_drop_pct"]:+.1f}% | close ${r["close"]:.2f} | prior high ${r["prior_high"]:.2f} | prior low ${r["prior_low"]:.2f} | higher low {r["higher_low"]}')
    if not rows:
        out.append('No prior-session setups found. This is normal on quiet days.')
    return '\n'.join(out) + '\n'
