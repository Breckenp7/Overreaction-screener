import unittest
import pandas as pd
from screener.backtest import backtest_symbol, summarize, render


class TestBacktest(unittest.TestCase):
    def make_data(self, confirm=True):
        dates = pd.bdate_range('2024-01-01', periods=100)
        close = [100.0] * 100
        close[85] = 90.0
        close[86] = 102.0 if confirm else 91.0
        close[91] = 110.0
        high = [x + 1 for x in close]
        low = [x - 1 for x in close]
        high[85], low[85] = 95, 88
        low[86] = 89 if confirm else 87
        return pd.DataFrame({'Open': close, 'High': high, 'Low': low, 'Close': close}, index=dates)

    def test_confirmed_and_matched_return(self):
        events = backtest_symbol(self.make_data(), 'TEST')
        target = [e for e in events if e['setup_date'] == '2024-04-29']
        self.assertEqual(len(target), 1)
        self.assertTrue(target[0]['confirmed'])
        self.assertAlmostEqual(target[0]['immediate_return'], 100 / 90 - 1 - .001, places=6)
        self.assertAlmostEqual(target[0]['confirmed_return'], 110 / 102 - 1 - .001, places=6)

    def test_no_trade_if_unconfirmed(self):
        events = backtest_symbol(self.make_data(False), 'TEST')
        target = [e for e in events if e['drop_pct'] == -10.0]
        self.assertFalse(target[0]['confirmed'])
        self.assertIsNone(target[0]['confirmed_return'])

    def test_short_history(self):
        self.assertEqual(backtest_symbol(self.make_data().iloc[:30], 'TEST'), [])

    def test_empty_summary(self):
        self.assertEqual(summarize([])['confirmed'], 0)
        self.assertIn('insufficient data', render([], 5, 7, 10))


if __name__ == '__main__':
    unittest.main()
