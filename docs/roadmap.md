# Roadmap

The gap screener is the first module of a growing market screening platform.
Each new screener reuses the same pipeline: ticker sources → cache-first
fetch → detection → persistence → report.

## Done

- [x] Pre-market gap scanner with tier ladder — Dow, S&P 500, NASDAQ-100
- [x] Gap tiers: recorded from 10 %, classified 10%+ / 20%+ / 50%+
- [x] Full US market scan (parallel, ~5,000 symbols)
- [x] Cache-first data layer (quotes 5 min, candles 1 h)
- [x] Monthly ticker list updates (Wikipedia)
- [x] Telegram alerts per scan group
- [x] Public repo, sanitized (no secrets)

## In progress

- [x] Scan history persistence (`data/history/gaps_YYYY-MM-DD.json`)

## Next (near term)

- [x] Web frontend (`webapp.py`) — gap table with TradingView chart links
      (EMA9+SMA20 preloaded) and embedded D1/M15 mini charts
- [ ] `gap_stats` builder: aggregate history → per-symbol gap frequency
- [ ] European market screening (XETRA/LSE) — needs a source with EU
      pre-market quotes; candidate: Twelve Data or EODHD
- [ ] Real-time upgrade path: Finnhub WebSocket when 15-min delay
      or polling is no longer enough

## Later (platform ideas)

- [ ] Volume-spike screener (unusual pre-market volume)
- [ ] 52-week-high/low breaker screener
- [ ] Earnings-move screener (post-earnings gap analysis from history)
- [ ] Backtesting on stored history (would a gap strategy have paid off?)
- [ ] Web dashboard over `data/history/`
- [ ] Config file (YAML) for thresholds, watchlists, per-screener schedules

## Maintenance rules

- Docs in `docs/` are updated in the same commit as code changes.
- Every new data file gets documented in `docs/data-model.md`.
- Every new screener gets an entry here and in the README.
