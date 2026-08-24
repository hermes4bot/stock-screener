#!/usr/bin/env python3
"""
TradingView Pre-Market Gap Screener
====================================

Uses TradingView's public scanner API to get ALL US stocks with pre-market
gaps in ONE request (vs ~5000 Finnhub calls). Includes gap %, pre-market
volume, market cap - everything needed for quality filtering.

Usage:
  .venv/bin/python tv_gaps.py [min_gap_pct] [--save]
  .venv/bin/python tv_gaps.py            # default: 10% min gap
  .venv/bin/python tv_gaps.py 20 --save  # only 20%+ gaps, save to history

Environment:
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID - optional delivery
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

import requests

# Telegram delivery: dedicated gap-alert identity if set, else main bot.
GAP_TG_TOKEN = os.environ.get("GAP_TELEGRAM_BOT_TOKEN",
                              os.environ.get("TELEGRAM_BOT_TOKEN", ""))
GAP_TG_CHAT = os.environ.get("GAP_TELEGRAM_CHAT_ID",
                             os.environ.get("TELEGRAM_CHAT_ID", ""))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_GAP_PCT = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 10.0
GAP_TIERS = [10.0, 20.0, 50.0]

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"

TV_SCANNER_URL = "https://scanner.tradingview.com/america/scan"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tv-gaps")

# ---------------------------------------------------------------------------
# TradingView scanner API
# ---------------------------------------------------------------------------

def scan_tv_premarket_gaps(min_gap: float) -> list[dict]:
    """Query TradingView scanner for US stocks with |pre-market gap| >= min_gap.
    Returns list sorted by |gap| descending.
    """
    payload = {
        "filter": [
            {"left": "premarket_gap", "operation": "in_range", "right": [min_gap, 100000]},
        ],
        "options": {"lang": "en"},
        "markets": ["america"],
        "columns": [
            "name",                  # 0 ticker
            "close",                 # 1 regular close
            "premarket_close",       # 2 pre-market price
            "premarket_gap",         # 3 gap % vs prev close
            "premarket_volume",      # 4 pre-market volume
            "volume",                # 5 total volume
            "market_cap_basic",      # 6 market cap
            "description",           # 7 company name
            "sector",                # 8 sector
        ],
        "sort": {"sortBy": "premarket_gap", "sortOrder": "desc"},
        "range": [0, 150],
    }

    resp = requests.post(TV_SCANNER_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for row in data.get("data", []):
        d = row["d"]
        results.append({
            "symbol": d[0],
            "close": d[1],
            "premarket_price": d[2],
            "gap_pct": round(d[3], 2),
            "premarket_volume": d[4],
            "volume": d[5],
            "market_cap": d[6],
            "description": d[7],
            "sector": d[8],
        })

    # Also fetch gap-downs
    payload["filter"][0]["right"] = [-100000, -min_gap]
    payload["sort"]["sortOrder"] = "asc"
    resp = requests.post(TV_SCANNER_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    for row in data.get("data", []):
        d = row["d"]
        results.append({
            "symbol": d[0],
            "close": d[1],
            "premarket_price": d[2],
            "gap_pct": round(d[3], 2),
            "premarket_volume": d[4],
            "like_volume": d[5],
            "volume": d[5],
            "market_cap": d[6],
            "description": d[7],
            "sector": d[8],
        })

    # Dedupe by symbol, sort by |gap|
    seen = set()
    unique = []
    for r in results:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            unique.append(r)
    return sorted(unique, key=lambda x: abs(x["gap_pct"]), reverse=True)


def classify_tier(gap_pct: float) -> str:
    """Return the highest tier label this gap reaches, e.g. '20%+'."""
    tier = f"{GAP_TIERS[0]:.0f}%+"
    for t in GAP_TIERS:
        if abs(gap_pct) >= t:
            tier = f"{t:.0f}%+"
    return tier


# ---------------------------------------------------------------------------
# Filtering & reporting
# ---------------------------------------------------------------------------

def quality_filter(rows: list[dict], min_volume: int = 10_000, min_mcap: float = 0) -> list[dict]:
    """Filter out illiquid junk: no pre-market volume, tiny caps."""
    out = []
    for r in rows:
        if (r.get("premarket_volume") or 0) < min_volume:
            continue
        if min_mcap and (r.get("market_cap") or 0) < min_mcap:
            continue
        out.append(r)
    return out


def fmt_vol(v) -> str:
    if not v:
        return "-"
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return str(v)


def fmt_mcap(v) -> str:
    if not v:
        return "-"
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.0f}M"
    return str(v)


def report(rows: list[dict]) -> str:
    if not rows:
        return f"No US stocks with pre-market gaps >= {MIN_GAP_PCT}% found."

    lines = [
        f"Pre-Market Gaps >= {MIN_GAP_PCT}% - {len(rows)} stocks ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "",
        f"{'TICKER':8s} {'TIER':>5s} {'GAP%':>9s} {'PM PRICE':>9s} {'PREV':>9s} {'PM VOL':>8s} {'MCAP':>7s}  NAME",
        "-" * 80,
    ]
    for r in rows:
        tier = classify_tier(r["gap_pct"])
        arrow = "UP" if r["gap_pct"] > 0 else "DN"
        lines.append(
            f"{r['symbol']:8s} {arrow+'/'+tier if False else tier:>5s} {r['gap_pct']:>+9.2f} "
            f"{r['premarket_price'] or 0:>9.2f} {r['close'] or 0:>9.2f} "
            f"{fmt_vol(r.get('premarket_volume')):>8s} {fmt_mcap(r.get('market_cap')):>7s}  "
            f"{(r.get('description') or '')[:30]}"
        )
    return "\n".join(lines)


def save_history(rows: list[dict]) -> Path:
    HISTORY_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = HISTORY_DIR / f"tv_gaps_{today}.json"

    record = {}
    if filepath.exists():
        try:
            with open(filepath) as f:
                record = json.load(f)
        except (json.JSONDecodeError, IOError):
            record = {}

    record.update({
        "date": today,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "source": "tradingview",
        "min_gap_pct": MIN_GAP_PCT,
        "total_gaps": len(rows),
        "gaps": rows,
    })
    with open(filepath, "w") as f:
        json.dump(record, f, indent=2)
    log.info(f"History saved: {filepath}")
    return filepath


def send_telegram(message: str) -> bool:
    if not GAP_TG_TOKEN or not GAP_TG_CHAT:
        print(message)
        return False
    ok = True
    for i in range(0, len(message), 4000):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{GAP_TG_TOKEN}/sendMessage",
                json={"chat_id": GAP_TG_CHAT, "text": message[i:i + 4000]},
                timeout=30,
            )
            if resp.status_code != 200:
                log.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
                ok = False
        except Exception as e:
            log.error(f"Telegram error: {e}")
            ok = False
    if ok:
        log.info("Telegram message sent")
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 70)
    log.info(f"TradingView Pre-Market Gap Screener - min gap {MIN_GAP_PCT}%")
    log.info("=" * 70)

    try:
        rows = scan_tv_premarket_gaps(MIN_GAP_PCT)
    except requests.RequestException as e:
        log.error(f"TradingView API error: {e}")
        sys.exit(1)

    log.info(f"Raw results: {len(rows)} stocks with gaps >= {MIN_GAP_PCT}%")

    quality = quality_filter(rows)
    log.info(f"After quality filter (PM volume >= 10K): {len(quality)} stocks")

    # Attach tier labels so saved history carries them too
    for r in quality:
        r["tier"] = classify_tier(r["gap_pct"])

    print()
    print(report(quality))

    if "--save" in sys.argv:
        save_history(quality)

    if quality:
        send_telegram(report(quality))


if __name__ == "__main__":
    main()
