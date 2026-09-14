# Archive (retired 2026-09-14)

Retired pieces of the stock pipeline. Kept for reference, nothing here is
scheduled or imported by the live chain (`tv_gaps.py` → `send_gaps_zip.py`).

| File | Why retired |
|---|---|
| `daily_gap_cron.py` | Hermes job `daily-gap-cron` deleted; Notion leg dropped. System cron owns the daily scan. |
| `build_summary.py`, `create_summary.py` | Notion helpers, only used by `daily_gap_cron.py`. |
| `scan_gaps.py` | Legacy Finnhub per-symbol scanner. Reference fallback if the TV endpoint dies. |
| `news_bot.py` | Standalone RSS→Telegram digest. No scheduler ever referenced it. |
| `gaps_report.html`, `gaps.zip` | Stale one-off artifacts (Aug 2026). |
| `run_screener.sh` | Retired manual wrapper; pointed at `scan_gaps.py` with a stale path. |
