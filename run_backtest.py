"""Historical selloff backtest for 1, 2, 3, 5, 10 and 20 trading days."""
import argparse
import json
from pathlib import Path
from screener.data import YahooProvider
from screener.backtest import backtest_symbol, summarize, render

DEFAULT = 'SOFI,MCHP,SMCI,AMAT,HALO,DVN,QCOM,NVDA,AMD,STX,LRCX,KLAC'
DEFAULT_PERIODS = [1, 2, 3, 5, 10, 20]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tickers', default=DEFAULT)
    p.add_argument('--years', type=int, default=10)
    p.add_argument('--threshold', type=float, default=7.0)
    p.add_argument('--hold', type=int, default=5, help='Legacy text report holding period')
    p.add_argument('--periods', default='1,2,3,5,10,20')
    p.add_argument('--cost-bps', type=float, default=10)
    args = p.parse_args()
    periods = sorted(set(int(x.strip()) for x in args.periods.split(',')))
    if args.years < 1 or args.hold < 1 or min(periods) < 1 or args.threshold <= 0 or args.cost_bps < 0:
        p.error('years, holding periods and threshold must be positive; costs nonnegative')
    tickers = list(dict.fromkeys(t.strip().upper() for t in args.tickers.split(',') if t.strip()))
    prices = YahooProvider().prices(tickers, period=f'{args.years}y', chunk=8)
    # Build events for the longest horizon first, so each horizon uses identical setups.
    # Avoid including events without a full 20-day outcome in the 1-day comparison.
    all_by_period = {}
    for hold in periods:
        events=[]
        for ticker in tickers:
            events.extend(backtest_symbol(prices.get(ticker), ticker, args.threshold, hold, args.cost_bps))
        all_by_period[str(hold)] = events
    # Align events across periods to the same complete-history sample.
    common = set.intersection(*(set((e['ticker'],e['setup_date']) for e in ev) for ev in all_by_period.values())) if all_by_period else set()
    for k in all_by_period:
        all_by_period[k]=[e for e in all_by_period[k] if (e['ticker'],e['setup_date']) in common]
    def shape(s):
        return {'immediate_all':s['buy_at_selloff_close_all'], 'immediate_matched':s['buy_at_selloff_close_confirmed_subset'], 'confirmed_matched':s['buy_at_next_close_if_confirmed']}
    anchor=all_by_period[str(periods[0])]
    by_stock={}
    for ticker in tickers:
        a=[e for e in anchor if e['ticker']==ticker]
        by_stock[ticker]={'setups':len(a),'confirmed':sum(e['confirmed'] for e in a),'periods':{k:shape(summarize([e for e in events if e['ticker']==ticker])) for k,events in all_by_period.items()}}
    output={'periods':periods,'threshold':args.threshold,'cost_bps':args.cost_bps,'tickers':tickers,'setups':len(anchor),'confirmed':sum(e['confirmed'] for e in anchor),'summary':{k:shape(summarize(ev)) for k,ev in all_by_period.items()},'by_stock':by_stock}
    Path('output').mkdir(exist_ok=True)
    Path('output/rebound_backtest.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    text=render(all_by_period.get(str(args.hold),anchor),args.hold,args.threshold,args.cost_bps)
    Path('output/rebound_entry_backtest.txt').write_text(text,encoding='utf-8')
    print('Saved six-period backtest: output/rebound_backtest.json')
    print(text[:1500])

if __name__=='__main__':main()
