"""Historical comparison of selloff-close entry and next-session confirmed entry.

No future data is used to decide entry. Exits use fixed holding periods; no
intraday fills are assumed. Prices are adjusted daily bars, not executable fills.
"""
import numpy as np
import pandas as pd


def backtest_symbol(df, ticker, daily_drop_pct=7.0, hold_days=5, cost_bps=10, cooldown=10):
    if df is None or len(df) < 85:
        return []
    df = df.sort_index().dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
    events = []
    last_setup = -cooldown
    cost = cost_bps / 10000
    # Need one previous day, next-session confirmation, and full holding period.
    for i in range(1, len(df) - hold_days - 1):
        if i - last_setup < cooldown:
            continue
        prior, setup, next_bar = df.iloc[i - 1], df.iloc[i], df.iloc[i + 1]
        if min(prior['Close'], setup['Close'], setup['High'], setup['Low'], next_bar['Close'], next_bar['Low']) <= 0:
            continue
        drop = float(setup['Close'] / prior['Close'] - 1)
        if drop >= -daily_drop_pct / 100:
            continue
        last_setup = i
        confirmed = bool(next_bar['Close'] > setup['High'] and next_bar['Low'] > setup['Low'] and next_bar['Close'] > setup['Close'])
        # Both alternatives are independently evaluated over 5 days from their
        # own entry close. Unconfirmed setups are no-trade for confirmation strategy.
        baseline = float(df.iloc[i + hold_days]['Close'] / setup['Close'] - 1 - cost)
        confirmed_return = float(df.iloc[i + 1 + hold_days]['Close'] / next_bar['Close'] - 1 - cost) if confirmed else None
        events.append({
            'ticker': ticker, 'setup_date': str(df.index[i].date()),
            'confirmation_date': str(df.index[i + 1].date()),
            'drop_pct': round(drop * 100, 2), 'confirmed': confirmed,
            'immediate_return': baseline, 'confirmed_return': confirmed_return,
        })
    return events


def summarize(events):
    confirmed = [e for e in events if e['confirmed']]
    def stats(values):
        if not values:
            return {'n': 0, 'mean_pct': None, 'median_pct': None, 'win_rate_pct': None}
        arr = np.array(values, dtype=float)
        return {'n': len(arr), 'mean_pct': round(float(arr.mean() * 100), 2),
                'median_pct': round(float(np.median(arr) * 100), 2),
                'win_rate_pct': round(float((arr > 0).mean() * 100), 1)}
    return {
        'setups': len(events), 'confirmed': len(confirmed),
        'confirmation_rate_pct': round(100 * len(confirmed) / len(events), 1) if events else None,
        'buy_at_selloff_close_all': stats([e['immediate_return'] for e in events]),
        'buy_at_selloff_close_confirmed_subset': stats([e['immediate_return'] for e in confirmed]),
        'buy_at_next_close_if_confirmed': stats([e['confirmed_return'] for e in confirmed]),
    }


def render(events, hold_days, threshold, cost_bps):
    s = summarize(events)
    lines = ['REBOUND ENTRY BACKTEST — HISTORICAL RESEARCH ONLY',
             f'Setup: single-session drop > {threshold:g}%; confirm at next completed daily close above setup high, higher low, positive close.',
             f'Exit: {hold_days} trading sessions after each respective entry close. Assumed round-trip cost: {cost_bps:g} bps.',
             'CAUTION: close-to-close hypothetical fills, no slippage/market impact, survivorship bias, no delisted stocks, no point-in-time market cap, no out-of-sample validation.',
             'Confirmation strategy makes NO TRADE when next-day conditions fail. Its results must not be compared as if it trades every setup.',
             f"Historical setups: {s['setups']}; next-day confirmed: {s['confirmed']} ({s['confirmation_rate_pct']}%).", '']
    for name, key in [('Immediate entry, ALL setups', 'buy_at_selloff_close_all'),
                      ('Immediate entry, ONLY setups that later confirmed (matched subset)', 'buy_at_selloff_close_confirmed_subset'),
                      ('Wait for next-day confirmation, SAME matched subset', 'buy_at_next_close_if_confirmed')]:
        a = s[key]
        if not a['n']:
            lines.append(f'{name}: insufficient data')
        else:
            lines.append(f"{name}: n={a['n']}; mean {a['mean_pct']:+.2f}%; median {a['median_pct']:+.2f}%; win rate {a['win_rate_pct']:.1f}%")
    lines += ['', 'Per-stock summary (not independently calibrated):']
    for ticker in sorted(set(e['ticker'] for e in events)):
        a = summarize([e for e in events if e['ticker'] == ticker])
        c = a['buy_at_next_close_if_confirmed']
        lines.append(f"{ticker}: setups={a['setups']}, confirmed={a['confirmed']}, confirmed-entry mean={c['mean_pct']}%, win={c['win_rate_pct']}%")
    lines += ['', 'Recent historical events (last 30 by date):']
    for e in sorted(events, key=lambda x: x['setup_date'], reverse=True)[:30]:
        outcome = f"{e['confirmed_return']*100:+.2f}%" if e['confirmed'] else 'NO TRADE'
        lines.append(f"{e['ticker']} {e['setup_date']}: drop {e['drop_pct']:+.1f}%, immediate {e['immediate_return']*100:+.2f}%, confirmed entry {outcome}")
    return '\n'.join(lines) + '\n'
