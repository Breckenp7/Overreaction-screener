import unittest
import numpy as np
import pandas as pd
from screener.rebound import evaluate, scan

CFG = {'detection': {'daily_drop_pct': 7, 'multi_day_window': 5, 'multi_day_drop_pct': 12}}

def bars(close=105, high=106, low=101):
    idx = pd.bdate_range('2026-01-01', periods=90)
    data = pd.DataFrame({'Close': np.full(90, 100.), 'High': np.full(90, 101.),
                         'Low': np.full(90, 99.), 'Volume': np.full(90, 1000.)}, index=idx)
    data.iloc[-2, data.columns.get_loc('Close')] = 90
    data.iloc[-2, data.columns.get_loc('High')] = 94
    data.iloc[-2, data.columns.get_loc('Low')] = 89
    data.iloc[-1, data.columns.get_loc('Close')] = close
    data.iloc[-1, data.columns.get_loc('High')] = high
    data.iloc[-1, data.columns.get_loc('Low')] = low
    return data

class ReboundTests(unittest.TestCase):
    def test_confirmation(self):
        self.assertEqual(evaluate(bars(), CFG)['status'], 'CONFIRMED REVERSAL')
    def test_no_intraday_confirmation(self):
        self.assertEqual(evaluate(bars(), CFG, partial=True)['status'], 'WATCHLIST')
    def test_no_breakout(self):
        self.assertEqual(evaluate(bars(close=93, high=96, low=91), CFG)['status'], 'WATCHLIST')
    def test_invalidation(self):
        self.assertEqual(evaluate(bars(close=85, high=91, low=83), CFG)['status'], 'INVALIDATED')
    def test_no_setup(self):
        df = bars()
        df.iloc[-2, df.columns.get_loc('Close')] = 99
        self.assertIsNone(evaluate(df, CFG))
    def test_scan(self):
        self.assertEqual(len(scan({'ABC': bars()}, ['ABC'], CFG)), 1)

if __name__ == '__main__':
    unittest.main()
