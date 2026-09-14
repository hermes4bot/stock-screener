# Data Model

All data lives in `data/`. Two categories: **reference data** (committed to
git, changes monthly) and **runtime data** (gitignored or historical).

## Reference data (in git)

| File | Format | Refresh | Source |
|---|---|---|---|
| `data/dow_jones.txt` | one ticker/line, `#` comments | monthly | Wikipedia |
| `data/sp500_tickers.txt` | one ticker/line | monthly | Wikipedia |
| `data/nasdaq_100.txt` | one ticker/line | quarterly | curated |
| `data/all_us_stocks.txt` | one ticker/line + header comment | frozen (legacy Finnhub artifact, unused by TV path) | — |

Filter for the US universe: `type == "Common Stock"`, `currency == "USD"`,
MIC in {XNYS, XNAS, XASE, ARCA}.

## Runtime caches (retired with the Finnhub path — documented for reference)

### `quotes_cache.json` (legacy)
```json
{
  "AAPL": {
    "quote": {"c": 311.3, "d": -5.53, "dp": -1.75, "pc": 316.83},
    "cached_at": 1787321441.0
  }
}
```
- TTL was 300 s · Source was Finnhub `/quote`

### `candles_cache.json` (legacy)
```json
{
  "AAPL": {
    "closes": [270.04, "...210 floats oldest→newest"],
    "cached_at": 1787321441.0
  }
}
```
- TTL was 3600 s · Source was Twelve Data `/time_series`, interval=1day

## Historical results (permanent, in git)

### `history/tv_gaps_YYYY-MM-DD.json` (primary gap screener)
Written by `tv_gaps.py --save`. Multiple scans per day merge.
```json
{
  "date": "2026-08-22",
  "scanned_at": "2026-08-22T02:19:17",
  "source": "tradingview",
  "min_gap_pct": 10.0,
  "total_gaps": 52,
  "gaps": [
    {
      "symbol": "HOWL",
      "close": 0.87,
      "premarket_price": 0.98,
      "gap_pct": 69.99,
      "premarket_volume": 98200000,
      "volume": 123456789,
      "market_cap": 21000000,
      "description": "Werewolf Therapeutics, Inc.",
      "sector": "Health Technology",
      "tier": "50%+"
    }
  ]
}
```
`tier` = highest boundary reached from `GAP_TIERS` (10/20/50). Minimum
recorded gap: `GAP_THRESHOLD` (default 0.10).

### `history/gaps_YYYY-MM-DD.json` (retired Finnhub scanner)
Same merge behavior; groups keyed by scan target:
```json
{
  "date": "2026-08-22",
  "scanned_at": "...",
  "gap_threshold": 0.1,
  "groups": {"Dow Jones": [], "S&P 500": []},
  "total_gaps": 0
}
```
Gap entries carry `tier` too.

### `history/news_YYYY-MM-DD.json` (retired news bot)
```json
{
  "date": "2026-08-22",
  "fetched_at": "2026-08-22T12:41:37+00:00",
  "feeds": ["Google News: Markets", "Google News: Business"],
  "count": 15,
  "articles": [
    {"headline": "...", "source": "CNN", "url": "...", "datetime": 1787388104}
  ]
}
```

Retention: **forever** — analysis base for gap-frequency stats, volatility
rankings, backtests.

## Webapp state (browser-local)

Favorites are stored per-browser in `localStorage["gapFavs"]` as a JSON
array of symbols. Not synced server-side.

## Environment

`~/.hermes/.env` (gitignored) — live keys for the TV path:
- `NEWS_TELEGRAM_BOT_TOKEN`, `NEWS_TELEGRAM_CHAT_ID` (delivery)
- `GAP_TELEGRAM_BOT_TOKEN`, `GAP_TELEGRAM_CHAT_ID` (optional dedicated identity)

Retired keys (Finnhub era, no longer required): `FINNHUB_API_KEY`,
`TWELVEDATA_API_KEY`, `GAP_THRESHOLD`, `NEWS_QUERY`, `NEWS_CATEGORY`.
