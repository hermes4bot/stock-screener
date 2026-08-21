# Data Model

All data lives in `data/`. Two categories: **reference data** (committed to
git, changes monthly) and **runtime data** (gitignored or historical).

## Reference data (in git)

| File | Format | Refresh | Source |
|---|---|---|---|
| `data/dow_jones.txt` | one ticker/line, `#` comments | monthly | Wikipedia |
| `data/sp500_tickers.txt` | one ticker/line | monthly | Wikipedia |
| `data/nasdaq_100.txt` | one ticker/line | quarterly | curated |
| `data/all_us_stocks.txt` | one ticker/line + header comment | cached at first use / manual re-fetch | Finnhub `/stock/symbol?exchange=US` |

Filter for the US universe: `type == "Common Stock"`, `currency == "USD"`,
MIC in {XNYS, XNAS, XASE, ARCA}.

## Runtime caches (gitignored — regenerate automatically)

### `quotes_cache.json`
```json
{
  "AAPL": {
    "quote": {"c": 311.3, "d": -5.53, "dp": -1.75, "pc": 316.83, "...": "..."},
    "cached_at": 1787321441.0
  }
}
```
- TTL: 300 s (5 min)
- Key: ticker symbol

### `candles_cache.json`
```json
{
  "AAPL": {
    "closes": [270.04, "...210 floats oldest→ newest"],
    "cached_at": 1787321441.0
  }
}
```
- TTL: 3600 s (1 h)
- Source: Twelve Data `/time_series`, interval=1day, outputsize=210

## Historical results (permanent, in git via `--save`)

### `history/gaps_YYYY-MM-DD.json`
Written on every run with `--save` (daily cron uses it for indices,
monthly cron for full market). One file per day; multiple scans per day merge.

```json
{
  "date": "2026-08-21",
  "scanned_at": "2026-08-21T16:10:50+02:00",
  "gap_threshold": 0.50,
  "groups": {
    "Dow Jones": [],
    "S&P 500": [],
    "NASDAQ-100": []
  },
  "total_gaps": 0
}
```

Gap entry:
```json
{
  "symbol": "XYZ",
  "prev_close": 4.10,
  "current": 7.25,
  "gap_pct": 76.83,
  "direction": "UP",
  "tier": "50%+",
  "indicators": null
}
```

`tier` is the highest boundary the |gap| reaches (from `GAP_TIERS`:
10/20/50). The minimum recorded gap is `GAP_THRESHOLD` (default 0.10 = 10 %);
larger tiers are labels, not filters.

Retention: **forever**. This is the analysis base for future features
(gap-frequency per stock, volatility rankings, backtests).

## Derived data (planned)

| File | Purpose |
|---|---|
| `history/gap_stats.json` | aggregated gap frequency per symbol, built from history |

## Environment

`.env` (gitignored) — see `.env.example`:
`FINNHUB_API_KEY` (required), `TWELVEDATA_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GAP_THRESHOLD`.
