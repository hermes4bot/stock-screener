# Architecture (actual state as of 2026-09-14)

One live pipeline. Everything else is archived (see `archive/README.md`).

## Workflow

```
MONTHLY (Hermes job `update-ticker-lists`, 15 10 1-7 * *)
  update_lists.py --Wikipedia--> data/dow_jones.txt, data/sp500_tickers.txt
                                    (nasdaq_100.txt is curated, quarterly)

WEEKDAYS 14:45 Berlin (system cron `run_stock_gaps.sh`, flock-guarded)
  1. uv sync --frozen            # venv always matches uv.lock, warn-and-continue
  2. tv_gaps.py 10 --save        # ONE TradingView scanner call (3x retry, 60s)
     quality filter PM vol >= 10K, tiers 10/20/50%
     --> data/history/tv_gaps_YYYY-MM-DD.json
  3. send_gaps_zip.py            # CSV + full HTML (via webapp.render_html)
     --> News Group: ONE message (gaps.zip + caption + source footer)
  Failures (scan x3, missing dir, ZIP fail) --> ONE ❌ message each, exit 1

ON DEMAND
  webapp.py (:8080, run_webapp.sh) reads newest history JSON, serves charts.
```

## Schedules (all times Berlin)

| What | When | Executor | Telegram |
|---|---|---|---|
| Gap scan + ZIP | Mon–Fri 14:45 | system cron `run_stock_gaps.sh` | 1 ZIP msg; 1 ❌ msg only on failure |
| Ticker refresh | day 1–7 monthly, 10:15 | Hermes job `update-ticker-lists` | none (`deliver: local`) |
| Dashboard | manual | `./run_webapp.sh [port]` | none |

## Components (live)

### `tv_gaps.py` — the only scanner
POST to `scanner.tradingview.com/america/scan` (gap-ups + gap-downs),
columns include PM volume, market cap, sector. No API key, no ticker list
needed — the scanner returns everything. Quality filter: pre-market volume
≥ 10,000. Tier = highest boundary from `[10, 20, 50]`.
Sends its own Telegram summary ONLY without `--save`; under `--save` the
ZIP step owns delivery (one-message rule).

### `send_gaps_zip.py` — the only reporter
Reads today's history JSON (falls back to newest file — the caption date is
the witness: a stale date means the scan failed or the market was closed).
Builds `gaps_<date>.csv` + `gaps_<date>.html` (same enriched rows and full
`render_html` as the dashboard) and sends one `sendDocument` with caption
`Gap scan <date> - <N> stocks` + `-- via system-cron · send_gaps_zip.py`.

### `update_lists.py` — ticker upkeep
Scrapes Wikipedia (S&P 500 table, Dow list) with `requests`. No key.
Writes `dow_jones.txt` / `sp500_tickers.txt`. Runs inside the Hermes
`update-ticker-lists` job; the job script also runs `uv sync` first.

### `webapp.py` — dashboard + render library
Reads newest `tv_gaps_*` history file. Charts via official
`TradingView.widget` API:
- studies `MAExp@tv-basicstudies` / `MASimple@tv-basicstudies`
- colors ONLY through display-name overrides
  (`"moving average exponential.ma.color"` = EMA orange,
  `"moving average.ma.color"` = SMA blue; object-form styles fail silently)
- lookback via from/to: D1 90 d, M15 10 d, M1 2 d
Layout: D1 2fr + M15 1fr grid; M1 full-width behind lazy toggle.
Favorites in localStorage; batch bar visible only in Favorites view;
all `window.open` calls synchronous inside click handlers.
Also imported by `send_gaps_zip.py` (`flatten`, `prepare_rows`,
`render_html`) — keep these APIs stable.

## Environment

Python via `uv` (`pyproject.toml` → `uv.lock` → `.venv`, 8.6 MB).
Declares exactly: `requests`, `flask`, `jinja2`.
`uv run` is unusable on uv 0.12 for this flat layout (tries a src build),
so callers run `uv sync --frozen --no-install-project` then
`.venv/bin/python`. `[tool.uv] package = false` is set for future uv.

Secrets (all from `/home/hermes/.hermes/.env`, never hardcoded):
`NEWS_TELEGRAM_BOT_TOKEN` / `NEWS_TELEGRAM_CHAT_ID` (News Group delivery;
scripts re-export as `GAP_*` for the Python children).

## Data (see `data-model.md` for formats)

- Reference (git): `dow_jones.txt`, `sp500_tickers.txt` (monthly),
  `nasdaq_100.txt` (curated), `all_us_stocks.txt` (legacy, unused by TV path).
- History (git, forever): `data/history/tv_gaps_YYYY-MM-DD.json`.
- Runtime (gitignored): `.venv/`, `__pycache__/`.

## Accepted risks

1. **Single data source.** The TradingView endpoint is undocumented and
   keyless. The Finnhub fallback is doubly dead (archived code, no
   `FINNHUB_API_KEY`, deps removed). Revival recipe: add the key to `.env`,
   re-add `finnhub-python` + `pandas` to `pyproject.toml`, `uv lock && uv sync`.
2. **Silent ticker staleness.** A failed monthly refresh (e.g. HTTP 429)
   only logs inside the Hermes job; scans keep running on old lists.
3. **Ambiguous history gaps.** Missing day = market closed OR scan failed;
   only the ZIP caption date tells them apart.

## Design rules

1. **One message per event** — success = the ZIP itself; any failure = one ❌.
2. **Every message carries its source** (`-- via system-cron · <script>`).
3. **Deterministic work lives in system cron**; the one Hermes job left
   (`update-ticker-lists`) is judgment-free fetching.
4. **Never lose downloaded data** — scans go to permanent history.
5. **Docs change with code** — README, SKILL.md, `docs/` in the same step.
