---
name: stock-screener
description: Detects pre-market stock gaps via TradingView scanner + system cron.
category: mlops
version: 2.1.0
author: hermes-agent
license: MIT
tags: [stock, screener, gap-detection, tradingview, cron, telegram]
metadata:
  hermes:
    tags: [finance, gap-scanner, market-data]
    related_skills: []
---

# Stock Screener - Pre-Market Gap Detection for US Markets

## When to Use

- When you need a daily pre-market stock screener that detects gaps >= 10% on US markets
- When you want scheduled gap screening weekdays 14:45 Berlin time, delivered as ZIP to Telegram
- When you need to identify significant pre-market price moves before the US market open

## Overview

This skill provides a Python-based stock gap screener that:
- Fetches ALL US pre-market gaps in ONE TradingView scanner call (no key)
- Quality-filters (PM volume >= 10K) and tiers (10/20/50%+)
- Persists every scan to `data/history/tv_gaps_YYYY-MM-DD.json`
- Delivers one ZIP (CSV + HTML) per trading day via `send_gaps_zip.py`

## Time Zone Reference (Berlin / CEST)

| Session | US Eastern Time | Berlin Time |
|---|---|---|
| Pre-market start | 4:00 AM ET | 10:00 AM CEST |
| **Scan time (system cron)** | 8:45 AM ET | **14:45 CEST** |
| Market open | 9:30 AM ET | 3:30 PM CEST |
| Market close | 4:00 PM ET | 10:00 PM CEST |

## Prerequisites

1. **No API key needed** — TradingView scanner endpoint is keyless.
   Telegram delivery uses `NEWS_TELEGRAM_BOT_TOKEN` / `NEWS_TELEGRAM_CHAT_ID`
   from `/home/hermes/.hermes/.env`.
   - Free tier: real-time US stock quotes, 60 calls/min
2. Python 3.11+ with uv

## Setup

```bash
cd /home/hermes/dev/stock-screener
uv sync --frozen --no-install-project   # deps from uv.lock (requests/flask/jinja2)
cp .env.example .env
```

## Usage (live chain)

```bash
# Daily gap scan + ZIP delivery (also what system cron 14:45 runs)
/home/hermes/.hermes/bin/uv sync --project /home/hermes/dev/stock-screener --frozen --no-install-project
.venv/bin/python tv_gaps.py 10 --save
.venv/bin/python send_gaps_zip.py

# Retired: archive/scan_gaps.py (Finnhub fallback, needs finnhub+pandas re-added),
# archive/news_bot.py, archive/daily_gap_cron.py (Notion leg dropped 2026-09-14)
```

## Cron Setup

Three cron jobs are pre-configured:

| Job | Schedule | Purpose |
|---|---|---|
| system cron `run_stock_gaps.sh` | `45 14 * * 1-5` | Daily gap scan + ZIP to News Group (1 msg; ❌ only on failure) |
| Hermes `update-ticker-lists` | `15 10 1-7 * *` | Monthly ticker list update from Wikipedia (deliver: local) |

## Data Files (in data/)

| File | Description | Update |
|---|---|---|
| `dow_jones.txt` | 30 Dow Jones tickers | Monthly |
| `sp500_tickers.txt` | 505 S&P 500 tickers | Monthly |
| `nasdaq_100.txt` | 298 NASDAQ-100 tickers (curated) | Quarterly |
| `history/tv_gaps_YYYY-MM-DD.json` | Daily scan results (permanent, in git) | Daily (trading days) |
| `all_us_stocks.txt`, `quotes_cache.json`, `candles_cache.json` | Legacy Finnhub artifacts (unused by TV path) | Frozen |

## Caching Strategy

The TV path is stateless (one scanner call, no cache). Permanent history in
`data/history/` doubles as the analysis base. Finnhub-era caches
(`quotes_cache.json` 5-min TTL, `candles_cache.json` 1-h TTL) are legacy and
unused — see `archive/`.

## Scan Priority

Not applicable to the TV path (single call returns everything, filtered by
PM volume ≥ 10K and tiers 10/20/50). The group-priority scheme below applied
only to the retired Finnhub scanner and is kept for reference:

When scanning the full US market, stocks are prioritized by gap likelihood:
1. **Other US Stocks** (not in major indices) - micro/small-cap, most volatile
2. **NASDAQ-100** - growth stocks, moderate volatility
3. **S&P 500** - large-cap, less volatile
4. **Dow Jones** - blue-chip, least likely to gap 50%+

Gaps found in each group trigger real-time Telegram alerts.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEWS_TELEGRAM_BOT_TOKEN` | *(empty)* | News Group bot token (delivery) |
| `NEWS_TELEGRAM_CHAT_ID` | *(empty)* | News Group chat ID (delivery) |
| `GAP_TELEGRAM_BOT_TOKEN` / `GAP_TELEGRAM_CHAT_ID` | *(fallback to NEWS_*)* | Dedicated gap-alert identity (optional) |

## Rate Limiting

- TradingView scanner: keyless, occasional HTTP 429 — the cron wrapper
  retries 3× with 60 s delay; persistent failure sends one ❌ message.
- Wikipedia (monthly ticker refresh): low frequency; a 429 only logs inside
  the Hermes job — watch for stale `dow_jones.txt` / `sp500_tickers.txt`.

## EMA/SMA Indicators

Retired with the Finnhub path (`--indicators` / Twelve Data belonged to
`archive/scan_gaps.py`). The dashboard draws EMA9/SMA20 via TradingView
chart studies instead — no data fetching needed.

## Files

| File | Purpose |
|---|---|
| `tv_gaps.py` | Main gap scanner (TradingView API) |
| `archive/scan_gaps.py` | Retired Finnhub fallback (archived 2026-09-14) |
| `update_lists.py` | Monthly ticker list updater (Wikipedia) |
| `run_webapp.sh` | Manual dashboard launcher (:8080) |
| `archive/run_screener.sh` | Retired manual wrapper (pointed at archived scanner) |
| `.env.example` | Environment variable template |
