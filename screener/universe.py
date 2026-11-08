"""Builds the list of tickers to scan.

Starting universe = S&P 500 + S&P 400 + Nasdaq-100 (free lists from Wikipedia)
plus anything in extra_tickers.txt. Market cap is checked later, only for stocks
that actually fell, so we don't need 1,000 slow lookups every scan.

Limitation: companies outside those indexes (recent IPOs, some foreign listings)
are missed unless you add them to extra_tickers.txt.
"""
import json
from io import StringIO
from pathlib import Path
import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (overreaction-screener research tool)"}
SOURCES = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    "sp400": ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol"),
    "nasdaq100": ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
}


def _clean(t):
    return str(t).strip().upper().replace(".", "-")  # Yahoo uses BRK-B, not BRK.B


def _fetch(name):
    url, col = SOURCES[name]
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    html = response.text
    for table in pd.read_html(StringIO(html)):
        # Wikipedia occasionally changes table header shape and capitalization.
        columns = [str(c[-1] if isinstance(c, tuple) else c).strip() for c in table.columns]
        aliases = {"Ticker", "Ticker symbol", "Symbol"} if name == "nasdaq100" else {col}
        matches = [j for j, c in enumerate(columns) if c in aliases]
        if matches:
            values = [_clean(x) for x in table.iloc[:, matches[0]].dropna()]
            if len(values) >= 50:
                return values
    raise ValueError(f"No '{col}' column found for {name}")


def read_extra(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.append(_clean(line))
    return out


def build_universe(cfg, root, log=print):
    cache = Path(root) / "data" / "universe_cache.json"
    try:
        cached = json.loads(cache.read_text()) if cache.exists() else {}
    except (ValueError, OSError):
        cached = {}
    tickers, warnings = [], []
    for name in cfg["universe"]["sources"]:
        try:
            got = _fetch(name)
            if len(got) < 50:
                raise ValueError("suspiciously short list")
            cached[name] = got
        except Exception as e:
            got = cached.get(name, [])
            warnings.append(f"Could not refresh {name} list ({type(e).__name__}); "
                            f"using saved copy of {len(got)} tickers.")
        tickers += got
    try:
        cache.write_text(json.dumps(cached))
    except Exception:
        pass
    tickers += read_extra(Path(root) / cfg["universe"]["extra_tickers_file"])
    tickers = sorted(set(tickers))
    if len(tickers) < 50:
        raise RuntimeError(f"Stock universe contains only {len(tickers)} tickers; index sources unavailable. Refusing an incomplete scan.")
    for w in warnings:
        log("WARNING: " + w)
    return tickers, warnings
