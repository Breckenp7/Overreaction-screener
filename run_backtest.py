"""Run a historical five-day entry comparison using a manageable sample."""
import argparse
from pathlib import Path
from screener.data import YahooProvider
from screener.backtest import backtest_symbol, render

DEFAULT = 'SOFI,MCHP,SMCI,AMAT,HALO,DVN,QCOM,NVDA,AMD,STX,LRCX,KLAC'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tickers', default=DEFAULT, help='Comma-separated symbols')
    p.add_argument('--years', type=int, default=10)
    p.add_argument('--threshold', type=float, default=7.0)
    p.add_argument('--hold', type=int, default=5)
    p.add_argument('--cost-bps', type=float, default=10)
    args = p.parse_args()
    if args.years < 1 or args.hold < 1 or args.threshold <= 0 or args.cost_bps < 0:
        p.error('years, hold, threshold must be positive and cost-bps nonnegative')
    tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    prices = YahooProvider().prices(tickers, period=f'{args.years}y', chunk=8)
    events = []
    for ticker in tickers:
        events.extend(backtest_symbol(prices.get(ticker), ticker, args.threshold, args.hold, args.cost_bps))
    report = render(events, args.hold, args.threshold, args.cost_bps)
    Path('output').mkdir(exist_ok=True)
    target = Path('output/rebound_entry_backtest.txt')
    target.write_text(report, encoding='utf-8')
    print(report)
    print(f'Saved: {target}')


if __name__ == '__main__':
    main()
