# Architecture

## Overview

Two independent pipelines share one data home (`data/`):

```
GAP PIPELINE
┌────────────────────┐   ┌──────────────┐   ┌───────────────────┐
│ tv_gaps.py         │   │ scan_gaps.py │   │ webapp.py (:8080) │
│ TradingView scanner│   │ Finnhub     ──▶│ reads history/,   │
│ (primary, 1 call)  │   │ (fallback)   │   │ renders charts    │
└─────────┬──────────┘   └──────┬───────┘   └─────────▲─────────┘
          ▼                     ▼                     │
   quotes_cache.json     candles_cache.json            │
          ▼                                           │
   data/history/tv_gaps_YYYY-MM-DD.json ──────────────┘
   data/history/gaps_YYYY-MM-DD.json

NEWS PIPELINE
┌────────────────────┐        ┌───────────────────────────────┐
│ news_bot.py        │───────▶│ data/history/news_*.json      │
│ Google News RSS    │        └───────────────────────────────┘
└─────────┬──────────┘
          ▼
   Telegram digest (12:40 daily)
```

## Gap pipeline components

### Ticker sources (`data/*.txt`)
Static symbol lists for the Finnhub path; refreshed monthly by
`update_lists.py` (Wikipedia) or cached on first use (`all_us_stocks.txt`).
The TradingView path needs no ticker list — the scanner returns everything.

### Primary fetcher (`tv_gaps.py`)
POST to `scanner.tradingview.com/america/scan`, filter `premarket_gap`
in ±[min, 100000], columns include PM volume, market cap, sector.
Two requests total (gap-ups + gap-downs). Quality filter: pre-market
volume ≥ 10,000. Undocumented endpoint — `scan_gaps.py` is the fallback.

### Fallback fetcher (`scan_gaps.py`)
Finnhub `/quote` per symbol, cache-first (5-min TTL), sliding-window rate
limiter ~57 calls/min, auto-pause on HTTP 429. Parallel mode (5 threads +
shared limiter) for full-market scans.

### Gap detection + tiers
`gap % = (current − prev_close) / prev_close`. Recorded if |gap| ≥
`GAP_THRESHOLD` (default 0.10). Tier label = highest boundary reached from
`GAP_TIERS = [10, 20, 50]`.

### Persistence
- Runtime caches: gitignored, auto-regenerate (quotes 5 min, candles 1 h)
- History: `data/history/` date-stamped JSON, merges per day, **never cleaned**,
  committed to git — analysis base for future features

## News pipeline (`news_bot.py`)

Google News RSS feeds (`FEEDS` list): a search feed (`NEWS_QUERY`) plus the
Business topic feed. Dedupe by URL, sort by publish time, top-N message via
Telegram (4000-char chunks), full result archived to history. No API key.

## Webapp (`webapp.py`, Flask)

- Reads newest history file (`tv_gaps_*` preferred over `gaps_*`)
- Charts via official `TradingView.widget` API:
  - studies `MAExp@tv-basicstudies` / `MASimple@tv-basicstudies`
  - colors ONLY through display-name overrides:
    `"moving average exponential.ma.color"` = EMA orange,
    `"moving average.ma.color"` = SMA blue
    (object-form study styles fail silently)
  - lookback via from/to: D1 90 d, M15 10 d, M1 2 d
- Layout: D1 2fr + M15 1fr grid; M1 full-width behind lazy toggle
- Favorites in localStorage; "Favorites only" filter; batch bar
  ("next 10 favorites" / "ALL favorites") visible only in Favorites view;
  all `window.open` calls synchronous inside click handlers

## Design rules

1. **Cache before network** — every fetch checks local data first.
2. **Never lose downloaded data** — results go to permanent history.
3. **Rate limits are hard constraints** — limiter before requests, auto 429 pause.
4. **One platform, many screeners** — gap scanner and news bot are modules
   sharing the cache/persist/report conventions; new screeners plug in the same way.
