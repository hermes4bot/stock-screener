# Stock Screener

US pre-market gap screener + market news bot — built to grow into a
multi-purpose market screening platform.

Repo: <https://github.com/hermes4bot/stock-screener>

## Components

| File | What it does |
|---|---|
| `tv_gaps.py` | **Primary gap screener** — one TradingView scanner API call returns ALL US stocks with pre-market gaps (gap %, PM volume, market cap, sector). Quality filter drops illiquid names. |
| `scan_gaps.py` | Fallback gap screener via Finnhub per-symbol quotes (~5,000 symbols, parallel mode). Independent of TV's undocumented endpoint. |
| `webapp.py` | Web frontend: big D1+M15 charts side by side, M1 on demand, favorites, batch TradingView tab openers. |
| `news_bot.py` | Market news digest from Google News RSS (no API key), delivered via Telegram. |
| `update_lists.py` | Monthly refresh of Dow/S&P 500 constituents from Wikipedia. |

## Quick start

```bash
uv venv
uv pip install finnhub-python pandas requests flask
cp .env.example .env        # FINNHUB_API_KEY required; TELEGRAM_* optional

# Gap scan (all US stocks in 1 request, ~1 s)
.venv/bin/python tv_gaps.py 10 --save

# Web frontend
./run_webapp.sh 8080        # http://<host>:8080

# News digest
.venv/bin/python news_bot.py 15

# Finnhub fallback scans
.venv/bin/python scan_gaps.py all        # major indices
.venv/bin/python scan_gaps.py full       # whole US market (~95 min)
```

## Gap tiers

Gaps are recorded from **10 %** up and classified into tiers (`10%+`,
`20%+`, `50%+`). Output is sorted by tier, then size.
Config: `GAP_THRESHOLD` env var; tier list in the scripts.

## Scheduling (Hermes cron)

| Job | Schedule (Berlin) | Purpose |
|---|---|---|
| `stock-gap-screener` | 10:15 Mon–Fri | Daily gap scan → Telegram |
| `monthly-full-market-scan` | 10:15, day 1–7 | Full market scan, saved |
| `update-ticker-lists` | 10:15, day 1–7 | Refresh index constituents |
| `market-news-bot` | 12:40 daily | News digest → Telegram |

US market times in Berlin: pre-market 10:00–15:30, regular 15:30–22:00.

## Data continuity

Everything downloaded is stored under `data/` and reused:

| Path | TTL / retention | Content |
|---|---|---|
| `quotes_cache.json` | 5 min | Finnhub quotes |
| `candles_cache.json` | 1 h | Daily closes (Twelve Data) |
| `history/tv_gaps_*.json`, `gaps_*.json`, `news_*.json` | permanent | Date-stamped results (in git) |
| `dow_jones.txt` etc. | monthly | Ticker lists (in git) |

History accumulates forever — base for future gap-frequency stats and backtests.

## Web frontend features

- D1 chart at 2/3 width + M15 at 1/3; M1 full-width behind a toggle (lazy-loaded)
- **EMA(9) orange, SMA(20) blue** on every chart and every TradingView link
- Chart links open your TV layout with preloaded studies and lookback ranges
  (D1 = 90 d, M15 = 10 d, M1 = 2 d)
- Favorites: star per stock (localStorage), "Favorites only" filter;
  batch bar ("open next 10" / "open ALL") appears only in Favorites view
- Pop-up blocker detection with fix instructions

## Documentation

Living docs in [`docs/`](docs/): [Architecture](docs/architecture.md),
[Data model](docs/data-model.md), [Roadmap](docs/roadmap.md).

## APIs

- **TradingView scanner** (undocumented, free) — primary gap data
- **Finnhub** (free: 60 calls/min) — fallback quotes; candles are premium
- **Twelve Data** (free: 800/day) — optional candle history for indicators
- **Google News RSS** (free) — news digest
