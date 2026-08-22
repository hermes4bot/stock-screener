# Stock Screener

Pre-market gap scanner for US stock markets — built to grow into a multi-purpose
market screening platform.

## What it does

Detects **pre-market gaps ≥ 50%** in US stocks. A "gap" is the difference between
a stock's current (pre-market) price and its previous close:

```
gap % = (current price − previous close) / previous close × 100
```

Scans:
- **Dow Jones** (30 stocks)
- **S&P 500** (505 stocks)
- **NASDAQ-100** (298 stocks)
- **Full US market** (~5,000 stocks, parallel mode)

# Quick start

```bash
# Setup
uv venv
uv pip install finnhub-python pandas requests
cp .env.example .env        # add your FINNHUB_API_KEY

# Fast gap scan (TradingView API, all US stocks in 1 request, ~1 s)
.venv/bin/python tv_gaps.py 10 --save

# Web frontend (shows latest gaps + TradingView chart links with EMA9/SMA20)
./run_webapp.sh 8080        # open http://<host>:8080

# Finnhub-based scans (slower, per-symbol)
.venv/bin/python scan_gaps.py all        # major indices (~16 min)
.venv/bin/python scan_gaps.py full --save  # whole US market (~95 min)

# Update ticker lists (first trading day of month)
.venv/bin/python update_lists.py
```

## Data continuity

**Everything downloaded is saved in `data/` and reused.** Nothing is fetched
twice while a cached copy is still fresh:

| File | TTL | Content |
|---|---|---|
| `data/quotes_cache.json` | 5 min | Real-time quotes (Finnhub) |
| `data/candles_cache.json` | 1 h | Daily closes for EMA/SMA (Twelve Data) |
| `data/all_us_stocks.txt` | monthly | Full US symbol universe |
| `data/history/gaps_YYYY-MM-DD.json` | permanent | Every scan result, date-stamped |

Scan history accumulates forever and is the base for future analysis
(gap frequency per stock, volatility rankings, backtesting).

## Documentation

Living docs are in [`docs/`](docs/):

- [Architecture](docs/architecture.md) — components and data flow
- [Data model](docs/data-model.md) — files, formats, retention
- [Roadmap](docs/roadmap.md) — planned screeners and features

Docs are updated with every change to the code.

## Scheduling (Hermes cron)

| Job | Schedule (Berlin) | Purpose |
|---|---|---|
| `stock-gap-screener` | 10:15 Mon–Fri | Daily gap scan (indices), Telegram alert |
| `monthly-full-market-scan` | 10:15, 1st–7th | Full market scan, results saved |
| `update-ticker-lists` | 10:15, 1st–7th | Refresh index constituents |

US market times (Berlin): pre-market 10:00–15:30, regular 15:30–22:00.

## Gap tiers

Gaps are recorded from **10 %** up and classified into tiers
(`10%+`, `20%+`, `50%+`). Each result carries its highest tier; output is
sorted by tier, then size. Configure via:

- `GAP_THRESHOLD` env var — minimum recorded gap (default `0.10`)
- `GAP_TIERS` in `scan_gaps.py` — tier boundaries `[10, 20, 50]`

## API usage

- **Finnhub** (free): quotes + symbol lists — 60 calls/min
- **Twelve Data** (free, optional): daily candles for indicators — 800 calls/day

The scanner never exceeds rate limits: cache-first reads, sliding-window
limiter at ~57 calls/min, automatic 62 s pause on HTTP 429.
