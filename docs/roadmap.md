# Roadmap

The gap screener and news bot are the first modules of a growing market
screening platform. Each new screener reuses the same pipeline:
source → cache-first fetch → detection → persistence → report.

## Done

- [x] Pre-market gap scanner with tier ladder (10%+ / 20%+ / 50%+)
- [x] TradingView scanner integration (`tv_gaps.py`) — all US pre-market
      gaps in ONE request, volume + market cap quality filters
- [x] Finnhub fallback scanner (per-symbol, parallel full-market mode)
- [x] Cache-first data layer (quotes 5 min, candles 1 h)
- [x] Scan history persistence (`data/history/`, permanent, in git)
- [x] Web frontend: D1 2/3 + M15 1/3 charts, M1 on demand,
      EMA9 orange / SMA20 blue on all charts and TV links
- [x] Favorites (localStorage) + favorites-only filter + favorites batch
      tab opener ("next 10" / "ALL")
- [x] Pop-up blocker detection with fix instructions
- [x] Market news bot (Google News RSS → Telegram, daily 12:40)
- [x] Monthly ticker list updates (Wikipedia)
- [x] Public repo, sanitized; docs kept in sync

## Next (near term)

- [ ] `gap_stats` builder: aggregate history → per-symbol gap frequency
- [ ] Server-side favorites (`data/favorites.json`) to sync across devices
- [ ] Dedicated Telegram group for news bot (bot API cannot create groups —
      user creates it, then cron delivers there only)
- [ ] Silence "0 packages upgraded" update notifications; report only
      real updates or errors

## Later (platform ideas)

- [ ] European market screening (XETRA/LSE) — TV scanner supports other
      markets via the `markets` parameter; near-free to add
- [ ] Real-time upgrade path: TradingView/Finnhub WebSocket when polling
      is no longer enough
- [ ] Volume-spike screener (unusual pre-market volume)
- [ ] 52-week-high/low breaker screener
- [ ] Earnings-move screener (post-earnings gap analysis from history)
- [ ] Backtesting on stored history
- [ ] Config file (YAML): thresholds, watchlists, per-screener schedules

## Maintenance rules

- Docs in `docs/` are updated in the same commit as code changes.
- Every new data file gets documented in `docs/data-model.md`.
- Every new screener gets an entry here and in the README.
