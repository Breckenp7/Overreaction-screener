# V6 — all historical drops + 100-point research score

- Scans the configured universe for strictly >7% one-day close-to-close declines, retaining the existing $10B market cap minimum.
- Includes uncategorized selloffs and earnings misses so qualifying stocks are not silently filtered out.
- For each qualifying stock, finds **every** historical >7% one-day drop in the available 10-year history, including consecutive events (cooldown 0).
- Lists each date, daily decline, and actual 3/5/10/20-trading-day net return. Recent events with incomplete forward horizons are marked Pending.
- Ranks current candidates by 100-point research score: historical rebound 30; earnings-based reason proxy 20; financial strength 15; market conditions 15; technical support 15; valuation 5.
- Earnings-based proxy does NOT fully determine why a stock fell. Scoring uses the existing model with missing-input reweighting, category multipliers and penalties; scores are **not calibrated probabilities**.
- The historical return table is the main focus of the Ranked stock research dashboard tab; the original scan HTML also includes all events.
- Note: return statistics are hypothetical and overlapping events are correlated. Historical stock price history may be adjusted, and the source is not point-in-time survivorship-free.

GitHub: upload the contents of `overreaction-screener/` to the repository root, then run the Master dashboard workflow. Download its artifact and open `output/master_dashboard.html`.
