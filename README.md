# Stock Screener

US pre-market gap screener: one TradingView call → history → ZIP to Telegram.
Full workflow in `docs/architecture.md`.

Repo: <https://github.com/hermes4bot/stock-screener>

## Automated workflow (all times Berlin)

| When | What | Result |
|---|---|---|
| Mon–Fri 14:45 | system cron `run_stock_gaps.sh`: uv-sync → `tv_gaps.py 10 --save` (3× retry) → `send_gaps_zip.py` | 1 ZIP message; 1 ❌ only on failure |
| Day 1–7 monthly 10:15 | Hermes job `update-ticker-lists`: `update_lists.py` refreshes Dow/S&P from Wikipedia | silent (`deliver: local`) |
| Manual | `./run_webapp.sh [port]` dashboard on :8080 | — |

## Components

| File | What it does |
|---|---|
| `tv_gaps.py` | **Primary gap screener** — one TradingView scanner API call returns ALL US stocks with pre-market gaps (gap %, PM volume, market cap, sector). Quality filter drops illiquid names. |
| `archive/scan_gaps.py` | Retired Finnhub fallback (archived 2026-09-14; kept for reference if the TV endpoint dies). |
| `webapp.py` | Web frontend: big D1+M15 charts side by side, M1 on demand, favorites, batch TradingView tab openers. |
| `archive/news_bot.py` | Retired market news digest (archived 2026-09-14; no scheduler references it). |
| `update_lists.py` | Monthly refresh of Dow/S&P 500 constituents from Wikipedia. |

> **Single-source risk (accepted 2026-09-14):** the daily scan depends on TradingView's
> undocumented scanner endpoint. The Finnhub fallback (`archive/scan_gaps.py`) is
> doubly dead — no `FINNHUB_API_KEY` in `.env` and `finnhub`/`pandas` removed from
> the venv. To revive it: add the key to `.env`, re-add both packages to
> `pyproject.toml`, `uv lock && uv sync`.

## Quick start

```bash
uv sync --frozen --no-install-project   # install deps from uv.lock into .venv
cp .env.example .env        # TELEGRAM_* / NEWS_* optional; no API key needed for TV scan

# Gap scan (all US stocks in 1 request, ~1 s)
.venv/bin/python tv_gaps.py 10 --save   # after `uv sync` above; uv run unsupported on uv 0.12 for flat projects

# Web frontend
./run_webapp.sh 8080        # http://<host>:8080

# Retired (see archive/): news_bot.py, scan_gaps.py (needs finnhub+pandas re-added)
```

## Gap tiers

Gaps are recorded from **10 %** up and classified into tiers (`10%+`,
`20%+`, `50%+`). Output is sorted by tier, then size.
Config: `GAP_THRESHOLD` env var; tier list in the scripts.

## Scheduling (actual automation)

| Job | Schedule (Berlin) | Purpose |
|---|---|---|
| system cron `run_stock_gaps.sh` | 14:45 Mon–Fri | Daily gap scan + ZIP → News Group |
| Hermes `update-ticker-lists` | 10:15, day 1–7 | Refresh index constituents (Wikipedia) |

US market times in Berlin: pre-market 10:00–15:30, regular 15:30–22:00.

## Data continuity

Everything downloaded is stored under `data/` and reused:

| Path | TTL / retention | Content |
|---|---|---|
| `history/tv_gaps_*.json` | permanent | Date-stamped scan results (in git) |
| `dow_jones.txt` etc. | monthly | Ticker lists (in git) |
| `quotes_cache.json`, `candles_cache.json`, `history/gaps_*.json`, `history/news_*.json` | legacy | Finnhub/Notion-era artifacts, unused by the TV path |

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

- **TradingView scanner** (undocumented, free) — sole gap data source
- **Wikipedia** (free) — monthly Dow/S&P constituent refresh
- **Telegram Bot API** (free) — ZIP + alert delivery to the News Group

## Notion Integration (retired 2026-09-14)

Früher wurde jeder Scan in einer Notion-Datenbank gespiegelt. Mit dem
gelöschten Hermes-Job `daily-gap-cron` ist die Anbindung raus;
Skripte liegen unter `archive/`.

**Täglicher Cron** (Mo–Fr 14:45 Berlin, System-Cron `run_stock_gaps.sh`):
1. TradingView-Scan ausführen → `data/history/tv_gaps_YYYY-MM-DD.json`
2. ZIP (CSV + HTML) als eine Nachricht an News Group senden
3. Fehlerfall → genau eine ❌-Nachricht

(Notion-Anbindung retired 2026-09-14, siehe `archive/README.md`.)
