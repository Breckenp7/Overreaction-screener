"""Full-universe price-only historical replay and walk-forward evaluation."""
import argparse, json
from pathlib import Path
from screener.data import YahooProvider
from screener.universe import build_universe
from screener.validation import walk_forward
import yaml

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--tickers',default=None,help='Comma-separated test subset; default current configured index universe')
    p.add_argument('--years',type=int,default=10)
    p.add_argument('--start',default='2024-01-01')
    p.add_argument('--end',default=None)
    p.add_argument('--top-n',type=int,default=5)
    p.add_argument('--chunk',type=int,default=12)
    p.add_argument('--max-symbols',type=int,default=0,help='Optional runtime limit; 0 means all')
    a=p.parse_args()
    if a.years<2 or a.top_n<1 or a.chunk<1 or a.max_symbols<0:p.error('Invalid numeric arguments')
    if a.tickers:tickers=list(dict.fromkeys(t.strip().upper() for t in a.tickers.split(',') if t.strip()))
    else:
        cfg=yaml.safe_load(Path('config.yaml').read_text())
        tickers=build_universe(cfg,Path('.'))[0]
    if a.max_symbols:tickers=tickers[:a.max_symbols]
    print(f'Historical replay downloading {len(tickers)} symbols plus SPY, {a.years} years',flush=True)
    prices=YahooProvider().prices(tickers+['SPY'],period=f'{a.years}y',chunk=a.chunk)
    spy=prices.get('SPY')
    if spy is None or spy.empty:raise SystemExit('SPY benchmark missing; refusing unbenchmarked evaluation')
    downloaded=sum(t in prices for t in tickers)
    if downloaded<max(1,int(len(tickers)*.75)):
        raise SystemExit(f'Only {downloaded}/{len(tickers)} ticker histories downloaded; refusing misleading partial-universe result')
    report=walk_forward(prices,spy,start=a.start,end=a.end,top_n=a.top_n)
    report['universe_requested']=len(tickers)
    report['universe_downloaded']=downloaded
    report['universe_coverage_pct']=round(100*downloaded/len(tickers),1)
    report['full_configured_universe']=a.tickers is None and a.max_symbols==0
    out=Path('output');out.mkdir(exist_ok=True)
    (out/'walkforward_validation.json').write_text(json.dumps(report,indent=2))
    print(f"Replay complete: {report['replay_dates']} dates; {report['selected_events']} selected; coverage {report['universe_coverage_pct']}%")

if __name__=='__main__':main()
