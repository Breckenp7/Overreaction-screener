## November 2026 reliability patch

- Fixed SPY connectivity probe: a valid one-month dataset (typically 20-23 sessions) is no longer rejected for having <=30 rows.
- Yahoo Finance downloads use 10-symbol batches and disable threading. Batch failures and parse errors are logged.
- Wikipedia universe parsing accepts alternate Nasdaq-100 ticker column names, validates HTTP responses, and rejects severely incomplete universes.
- Scans fail rather than silently presenting results when fewer than 80% of requested stock symbols return data.
- GitHub scheduled and manual scans always run in report-only mode: **no phone or email notifications**. Download the HTML/TXT report under the workflow run's Artifacts section.
- The weekly pooled study also uploads downloadable statistics as an artifact.
- Unit tests and simulated-data scan/pool tests pass locally. Live GitHub market-data reliability still needs verification after deployment.

# Market Overreaction Screener

A **research-only** tool. It scans large U.S. stocks twice per trading day, finds sharp
selloffs, checks whether they look like possible overreactions, ranks them 0–100, and sends
the best to your phone. It never connects to a brokerage and never places trades.

## What it does (and honestly doesn't)

| It does | It does not |
|---|---|
| Scan S&P 500 + S&P 400 + Nasdaq-100 + your extra tickers, keep those ≥ $10B | Cover every U.S. stock (add missing ones to `extra_tickers.txt`) |
| Flag ≥ 7% one-day or ≥ 12% five-day drops (changeable) | Know *why* a stock fell |
| Match drops to earnings releases; show EPS actual vs. estimate | See **guidance** or **revenue vs. estimate** (not in free data — the report tells you to read the press release) |
| Show past similar drops for the same stock + pooled stats across stocks (5/10/20-day outcomes, sample sizes, dates) | Prove the strategy works. Pooled stats are **survivorship-biased** (today's index members only) and likely flatter results |
| Rank with a transparent score: every point is explained | Give a probability of a rebound. The score only says "research this first" |

Data: Yahoo Finance via `yfinance` (free, unofficial, sometimes delayed or throttled).

## Setup (about 30–40 minutes, all free)

### Step 1 — Phone alerts with ntfy (no account needed)
1. Install the **ntfy** app (iPhone App Store / Google Play).
2. Tap **+** → *Subscribe to topic*. Invent a long, random topic name, e.g. `overreact-k29x8f-4417-zqm`.
   Anyone who knows the name can read it, so make it unguessable. **Write it down.**

### Step 2 — (Recommended) email for the full report
Push notifications carry the top 3. The email carries the full ranked report.
1. Turn on 2-Step Verification for your Google account (if not already).
2. Go to <https://myaccount.google.com/apppasswords>, create an app password named "screener",
   and copy the 16-character password. (Use this, **not** your normal password.)

### Step 3 — GitHub account and private repository
1. Create a free account at <https://github.com>.
2. Click **+ → New repository**, name it `overreaction-screener`, choose **Private**, click *Create*.
3. On the new repo page click **uploading an existing file**, then drag in **all the files and
   folders from this project** (including `.github`). If your computer hides `.github`:
   click **Add file → Create new file**, type `.github/workflows/scan.yml` as the name, paste in
   the contents of that file, and commit. Repeat for `weekly-pool.yml`.

### Step 4 — Add your secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Name | Value |
|---|---|
| `NTFY_TOPIC` | your topic name from Step 1 |
| `EMAIL_USER` | your Gmail address |
| `EMAIL_APP_PASSWORD` | the 16-character app password |
| `EMAIL_TO` | where to send the report (can be the same Gmail) |

(Skip the three email secrets if you only want push.)

### Step 5 — First test (sends nothing)
Repo → **Actions** tab → **Scan for overreactions** → **Run workflow** → leave defaults
(*close*, dry run ✔) → **Run workflow**. Wait ~5 minutes, open the run, and read the log.
You should see "Downloading prices…", a list of candidates (or "No candidates"), and
"Dry run: nothing sent". The full report is in the run's **reports** artifact.
If it fails, copy the red error text to Claude.

### Step 6 — Test delivery to your phone
Run it again with **Dry run unchecked**. You should get a push and an email.
(If nothing fell enough that day you'll get "no candidates" by email only — that's normal.
To see a sample alert anyway, temporarily set `daily_drop_pct: 3` in `config.yaml`.)

### Step 7 — Build the history statistics (one time, then weekly automatically)
Actions → **Weekly pooled history study** → **Run workflow**. This may take 15–45 minutes.
If it errors from Yahoo rate limits, rerun with *with_earnings* unchecked.

### Step 8 — You're live
Nothing else to do. Scans run automatically at about **10:15 AM ET** (market-open, intraday)
and **4:30 PM ET** (market-close) on weekdays; holidays are skipped automatically.
GitHub's scheduler can run late by up to ~30 minutes at busy times.

## Changing settings
Edit `config.yaml` right on GitHub (pencil icon) → commit. Market-cap floor, drop thresholds,
score weights (must sum to 100), how many candidates to send, minimum score for a push — all there.

## Reading an alert
- **Score 0–100**: research priority, built from drop size, market context, earnings quality,
  financial health, historical rebounds, valuation, technical support. "Uses X% of rubric"
  tells you how much data was available.
- **"Why this might be justified"**: automatic counter-arguments. Take them seriously.
- **Intraday** (open scan): the day isn't finished; the move can change by the close.
- Always read the company's press release/call before deciding anything.

## Cost
- GitHub Actions: free for private repos up to 2,000 minutes/month. Expected use is roughly
  300–500 minutes/month (estimate; check **Settings → Billing** after a week).
- ntfy: free. Gmail: free. Data: free. **Total: $0.**

## Known limitations / risks
1. **Yahoo may throttle GitHub's servers.** If so, the app tells you ("data problem" alert)
   instead of sending bad results. The fix would be a paid/keyed data source (~$0–30/month).
2. Free earnings data is EPS-only and occasionally wrong or missing.
3. Backtest statistics are survivorship-biased and cluster in a few market-crash dates.
4. GitHub pauses scheduled jobs in repos with no activity for 60 days; if that happens, press
   **Run workflow** once to resume.

## Files
```
config.yaml            all settings
extra_tickers.txt      your additions to the universe (SOFI is pre-added)
run_scan.py            the scan (what the cloud runs twice a day)
run_pool.py            weekly historical study
screener/              the engine: data, events, history, scoring, report, notify
tests/                 automated tests (python -m unittest discover -s tests)
.github/workflows/     cloud schedules
```

Try it offline with synthetic data: `python run_scan.py --demo --dry-run`
