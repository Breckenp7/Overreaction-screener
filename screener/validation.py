"""Point-in-time PRICE-ONLY walk-forward replay; not a reconstruction of fundamental scores."""
from collections import defaultdict
import numpy as np
import pandas as pd

HORIZONS = (1, 2, 3, 5, 10, 20)

def events_for_symbol(df, ticker, threshold=7.0, cost_bps=10, cooldown=10):
    if df is None or len(df) < 100: return []
    df = df.sort_index().dropna(subset=['Close']).copy()
    close = df['Close'].astype(float).to_numpy()
    dates = pd.to_datetime(df.index)
    out=[]; last=-cooldown
    for i in range(1,len(close)-max(HORIZONS)):
        if i-last < cooldown or close[i-1]<=0 or close[i]<=0: continue
        drop=100*(close[i]/close[i-1]-1)
        if not drop < -threshold: continue
        last=i
        outcomes={str(h):100*(close[i+h]/close[i]-1-cost_bps/10000) for h in HORIZONS}
        out.append({'ticker':ticker,'date':str(dates[i].date()),'drop_pct':round(float(drop),3),'returns':outcomes,
                    'close':float(close[i])})
    return out

def score_from_past(past):
    """Only outcomes of events whose 20-day holding window ended before the replay date are supplied."""
    if len(past)<5: return None
    r=np.array([e['returns']['5'] for e in past],dtype=float)
    # A descriptive shrinkage score, not a probability.
    win=float((r>0).mean()); mean=float(np.clip(r.mean(),-15,15))
    return round(100*(len(past)*win+10*.5)/(len(past)+10)+mean*.5,2)

def walk_forward(prices, spy, threshold=7.0, cost_bps=10, cooldown=10, start='2024-01-01', end=None, top_n=5):
    spy_close=None
    if spy is not None and not spy.empty:
        spy_close=spy['Close'].dropna().astype(float)
        spy_close.index=pd.to_datetime(spy_close.index).normalize()
    all_events=[]; histories={}
    for ticker,df in prices.items():
        if ticker=='SPY': continue
        events=events_for_symbol(df,ticker,threshold,cost_bps,cooldown)
        histories[ticker]=events; all_events+=events
    # Index into each ticker's actual daily calendar to ensure outcomes are mature at evaluation date.
    calendars={t:list(pd.to_datetime(df.dropna(subset=['Close']).sort_index().index).date) for t,df in prices.items() if t!='SPY' and df is not None and not df.empty}
    by_date=defaultdict(list)
    for e in all_events:
        if e['date']>=start and (end is None or e['date']<=end):
            past=[]; dates=calendars.get(e['ticker'],[])
            for old in histories[e['ticker']]:
                if old['date']>=e['date']: break
                # Require 20 fully completed trading days before this setup; no lookahead.
                j=pd.Timestamp(old['date']).date()
                try: mature=dates[dates.index(j)+20]
                except (ValueError,IndexError): continue
                if mature < pd.Timestamp(e['date']).date(): past.append(old)
            s=score_from_past(past)
            e=dict(e,score=s,prior_events=len(past))
            if spy_close is not None:
                dt=pd.Timestamp(e['date'])
                idx=spy_close.index.searchsorted(dt)
                if idx<len(spy_close) and spy_close.index[idx]==dt:
                    e['spy_returns']={}
                    for h in HORIZONS:
                        if idx+h<len(spy_close):e['spy_returns'][str(h)]=float(100*(spy_close.iloc[idx+h]/spy_close.iloc[idx]-1))
            by_date[e['date']].append(e)
    dates=sorted(by_date)
    replays=[]; chosen=[]; all_eligible=[]
    for date in dates:
        ranked=sorted(by_date[date],key=lambda e:(e['score'] is not None,e['score'] if e['score'] is not None else -999),reverse=True)
        eligible=[e for e in ranked if e['score'] is not None]
        picks=eligible[:top_n]
        chosen.extend(picks);all_eligible.extend(eligible)
        replays.append({'date':date,'setups':len(ranked),'rankable':len(eligible),'picks':picks,
                        'unranked':[{'ticker':e['ticker'],'drop_pct':e['drop_pct'],'prior_events':e['prior_events']} for e in ranked if e['score'] is None]})
    def aggregate(events):
        result={}
        for h in HORIZONS:
            k=str(h); vals=[e['returns'][k] for e in events]
            excess=[e['returns'][k]-e['spy_returns'][k] for e in events if k in e.get('spy_returns',{})]
            result[k]={'n':len(vals),'mean_pct':round(float(np.mean(vals)),2) if vals else None,
                       'win_rate_pct':round(float(100*np.mean(np.array(vals)>0)),1) if vals else None,
                       'mean_excess_spy_pct':round(float(np.mean(excess)),2) if excess else None,'spy_matched_n':len(excess)}
        return result
    return {'method':'price-only walk-forward; 5-day win rate shrunk toward 50%, min 5 matured prior events; NOT calibrated probability',
            'threshold_rule':'strictly greater than 7% close-to-close','start':start,'end':end,'top_n':top_n,
            'symbols_downloaded':len(prices),'historical_events_total':len(all_events),
            'replay_dates':len(replays),'rankable_events':len(all_eligible),'selected_events':len(chosen),
            'selected':aggregate(chosen),'all_rankable':aggregate(all_eligible),'replays':replays,
            'limitations':['Current index membership creates survivorship and membership lookahead bias; not a historical point-in-time universe.',
                           'Fundamentals, earnings, market cap, and original composite score are NOT replayed.',
                           'Daily close hypothetical fills, assumed costs, no slippage or market impact.',
                           'Repeated events can overlap; results are not independent.',
                           'Historical ranking is exploratory; no calibrated predictive probability or proven out-of-sample edge.']}
