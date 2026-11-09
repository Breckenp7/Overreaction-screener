import numpy as np
import pandas as pd
from screener.validation import events_for_symbol, walk_forward, score_from_past

def synthetic():
    dates=pd.bdate_range('2023-01-02',periods=450)
    close=np.full(450,100.0)
    for i in (35,70,105,140,175,210,245,280,315,350,385):
        close[i]=90
    return pd.DataFrame({'Close':close,'Open':close,'High':close,'Low':close,'Volume':100},index=dates)

def test_strict_drop_and_horizons():
    d=synthetic();events=events_for_symbol(d,'TEST')
    assert events and all(e['drop_pct'] < -7 for e in events)
    assert set(events[0]['returns'])=={'1','2','3','5','10','20'}

def test_replay_only_uses_matured_prior_events():
    d=synthetic();v=walk_forward({'TEST':d},d,start='2023-01-01')
    for replay in v['replays']:
        for pick in replay['picks']:
            assert pick['prior_events']>=5
    assert v['selected_events']>0

def test_insufficient_history_not_probability():
    assert score_from_past([]) is None
