---
name: stock-screener
description: Detects pre-market stock gaps >=50% via Finnhub + cron.
category: mlops
version: 1.0.0
author: hermes-agent
license: MIT
tags: [stock, screener, gap-detection, finnhub, cron, telegram]
metadata:
  hermes:
    tags: [finance, gap-scanner, market-data]
    related_skills: []
---

# Stock Screener - Pre-Market Gap Detection for US Markets

## When to Use

- When you need a daily pre-market stock screener that detects gaps >= 50% on US markets
- When you want scheduled (cron) gap screening at 10:15 Berlin time (= 4:15 AM ET, start of US pre-market)
- When you need to identify significant pre-market price moves before the US market open

## Overview

This skill provides a Python-based stock gap screener that:
- Fetches real-time US stock quotes from Finnhub API
- Detects pre-market gaps >= 50% (configurable threshold)
- Caches all fetched data to JSON to avoid redundant API calls
- Supports incremental scanning: Dow, S&P 500, NASDAQ-100, or full US market

## Time Zone Reference (Berlin / CEST)

| Session | US Eastern Time | Berlin Time |
|---|---|---|
| Pre-market start | 4:00 AM ET | 10:00 AM CEST |
| **Scan time (cron)** | 4:15 AM ET | **10:15 AM CEST** |
| Market open | 9:30 AM ET | 3:30 PM CEST |
| Market close | 4:00 PM ET | 10:00 PM CEST |

## Prerequisites

1. **Finnhub API Key** (free tier): https://finnhub.io/dashboard
   - Free tier: real-time US stock quotes, 60 calls/min
2. Python 3.11+ with uv

## Setup

```bash
cd /home/hermes/dev/stock-screener
uv venv
uv pip install finnhub-python pandas requests
cp .env.example .env
# Edit .env and set FINNHUB_API_KEY
```

## Usage

```bash
export FINNHUB_API_KEY="your_key_here"

# Single index scan (fast)
.venv/bin/python scan_gaps.py dow       # 30 symbols, ~30s
.venv/bin/python scan_gaps.py sp500     # 505 symbols, ~10 min
.venv/bin/python scan_gaps.py nasdaq    # 298 symbols, ~6 min
.venv/bin/python scan_gaps.py all       # All three, ~16 min

# Full US market scan (4974 symbols, parallel, ~90 min)
.venv/bin/python scan_gaps.py full      # Use --save to persist results
```

## Cron Setup

Three cron jobs are pre-configured:

| Job | Schedule | Purpose |
|---|---|---|
| `stock-gap-screener` | `15 10 * * 1-5` | Daily gap scan at 10:15 Berlin (4:15 AM ET) |
| `monthly-full-market-scan` | `15 10 1-7 * *` | Monthly full US market scan with results saved |
| `update-ticker-lists` | `15 10 1-7 * *` | Monthly ticker list update from Wikipedia |

## Data Files (in data/)

| File | Description | Update |
|---|---|---|
| `dow_jones.txt` | 30 Dow Jones tickers | Monthly |
| `sp500_tickers.txt` | 505 S&P 500 tickers | Monthly |
| `nasdaq_100.txt` | 298 NASDAQ-100 tickers (curated) | Quarterly |
| `all_us_stocks.txt` | 4974 US stock symbols | Cached at first full scan |
| `quotes_cache.json` | Cached Finnhub quotes (5-min TTL) | Auto-updated |
| `candles_cache.json` | Cached daily closes (1-hour TTL) | Auto-updated |

## Caching Strategy

All fetched data is cached to stay within API limits:
- **Quotes**: 5-min TTL (pre-market prices change frequently)
- **Candles**: 1-hour TTL (daily closes don't change intraday)
- Cache is checked before every API call — re-running the scan reuses recent data

## Scan Priority (for "full" mode)

When scanning the full US market, stocks are prioritized by gap likelihood:
1. **Other US Stocks** (not in major indices) - micro/small-cap, most volatile
2. **NASDAQ-100** - growth stocks, moderate volatility
3. **S&P 500** - large-cap, less volatile
4. **Dow Jones** - blue-chip, least likely to gap 50%+

Gaps found in each group trigger real-time Telegram alerts.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FINNHUB_API_KEY` | *(empty)* | Finnhub API key (required) |
| `GAP_THRESHOLD` | `0.50` | Gap threshold (0.50 = 50%) |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Telegram bot token |
| `TELEGRAM_CHAT_ID` | *(empty)* | Telegram chat ID |
| `TWELVEDATA_API_KEY` | `demo` | Twelve Data key for EMA/SMA |
| `ENRICH_WITH_INDICATORS` | `0` | Set to 1 to enable EMA/SMA |

## Rate Limiting

- Finnhub free tier: 60 calls/min
- "full" scan uses parallel threads (5 workers) with shared rate limiter
- Expected: ~57 calls/min, ~90 min for 4974 symbols

## EMA/SMA Indicators (Optional)

Enable with `--indicators` flag. Uses Twelve Data for daily closes:
- Only needs last 200 closes for SMA(200)
- Only fetched for stocks with gaps (not all symbols)

## Files

| File | Purpose |
|---|---|
| `scan_gaps.py` | Main gap scanner |
| `update_lists.py` | Monthly ticker list updater (Wikipedia) |
| `run_screener.sh` | Shell wrapper for cron |
| `.env.example` | Environment variable template |
