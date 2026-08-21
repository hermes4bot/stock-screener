# Architecture

## Overview

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  Ticker      │     │  Quote Fetcher  │     │  Gap Detector    │
│  Sources     │────▶│  (Finnhub)      │────▶│  ≥ threshold %   │
│  data/*.txt  │     │  cache-first    │     └────────┬─────────┘
└──────────────┘     └────────┬────────┘              │
                              ▼                       ▼
                     ┌─────────────────┐     ┌──────────────────┐
                     │  quotes_cache   │     │  history/gaps_   │
                     │  .json (5 min)  │     │  YYYY-MM-DD.json │
                     └─────────────────┘     └────────┬─────────┘
                                                       ▼
                                              ┌──────────────────┐
                                              │  Reporter        │
                                              │  stdout/Telegram │
                                              └──────────────────┘
```

## Components

### 1. Ticker sources (`data/*.txt`)
Static symbol lists, refreshed monthly by `update_lists.py` (Wikipedia)
or cached on first use (`all_us_stocks.txt` from Finnhub).

- `dow_jones.txt` — 30 DJIA constituents
- `sp500_tickers.txt` — S&P 500
- `nasdaq_100.txt` — NASDAQ-100
- `all_us_stocks.txt` — full US Common Stock universe (NYSE/NASDAQ/AMEX/ARCA)

### 2. Quote fetcher (`scan_gaps.py: fetch_quote`)
Finnhub `/quote` per symbol. Cache-first: checks `quotes_cache.json`
(5-min TTL) before any API call. Sliding-window rate limiter (~57 calls/min),
auto-pause 62 s on HTTP 429.

### 3. Gap detector (`detect_gap`)
Pure function: `(c − pc) / pc`. Flags |gap| ≥ `GAP_THRESHOLD` (default 0.50).
Direction UP/DOWN.

### 4. Indicator enrichment (optional, `enrich_gaps`)
For gap stocks only: last 210 daily closes via Twelve Data →
EMA(9), SMA(20), SMA(200), above/below flags. Cached 1 h.

### 5. Scanner core (`scan_index`, `scan_index_parallel`)
Sequential mode for small lists; parallel mode (5 threads + shared rate
limiter) for the full market. Priority order in `full` mode:
non-index stocks → NASDAQ-100 → S&P 500 → Dow.

### 6. Persistence
- `data/quotes_cache.json` — quote cache (gitignored, regenerates)
- `data/candles_cache.json` — candle cache (gitignored)
- `data/history/gaps_YYYY-MM-DD.json` — permanent scan results (`--save`)
- `data/history/` accumulates; never cleaned automatically

### 7. Reporting
Per-group results to stdout; Telegram alerts when gaps are found
(`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`).

## Design rules

1. **Cache before network** — every fetch checks local data first.
2. **Never lose downloaded data** — raw results go to `data/history/`,
   caches only expire, they are not deleted.
3. **Rate limits are hard constraints** — limiter runs before requests,
   429 handling is automatic.
4. **One scanner, many screens** — gap detection is the first screener;
   future screeners plug into the same fetch/cache/report pipeline.
