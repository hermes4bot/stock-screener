#!/usr/bin/env python3
"""
send_gaps_zip.py
================
Zips the latest gap-scan CSV and sends it to the News Group via the
dedicated news bot. Called by the daily gap-screener cron after --save.

Environment (from .env):
  NEWS_TELEGRAM_BOT_TOKEN, NEWS_TELEGRAM_CHAT_ID
"""

import io
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
HISTORY_DIR = SCRIPT_DIR / "data" / "history"

TOKEN = os.environ.get("GAP_TELEGRAM_BOT_TOKEN", "") or os.environ.get("NEWS_TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("GAP_TELEGRAM_CHAT_ID", "") or os.environ.get("NEWS_TELEGRAM_CHAT_ID", "")

# Import webapp's render_html for the full-page HTML (same as the live site)
sys.path.insert(0, str(SCRIPT_DIR))
from webapp import render_html


def build_zip() -> tuple[bytes, str, int]:
    today = datetime.now().strftime("%Y-%m-%d")
    path = HISTORY_DIR / f"tv_gaps_{today}.json"
    if not path.exists():
        # fall back to the most recent history file
        files = sorted(HISTORY_DIR.glob("tv_gaps_*.json"))
        if not files:
            sys.exit("No tv_gaps history found")
        path = files[-1]

    record = json.loads(path.read_text())
    date = record.get("date", path.stem.replace("tv_gaps_", ""))

    # Select which rows to include (use same logic as webapp)
    from webapp import flatten, prepare_rows
    enriched = prepare_rows(record)

    # Build CSV from the same enriched data
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["symbol", "gap_pct", "tier", "premarket_price", "prev_close",
                "premarket_volume", "market_cap", "sector", "description"])
    for r in enriched:
        w.writerow([
            r.get("symbol"), r.get("gap_pct"),
            r.get("tier") or "10%+",
            r.get("pre_price"), r.get("prev_close"),
            r.get("premarket_volume"), r.get("market_cap"),
            r.get("sector"), r.get("description"),
        ])

    # Use webapp's full-page render_html with JS included (not static snapshot)
    html = render_html(record, static_snapshot=False)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"gaps_{date}.csv", buf.getvalue())
        z.writestr(f"gaps_{date}.html", html)

    # Caption stats (same enriched rows as CSV/HTML)
    stats = {"count": len(enriched), "tiers": {}, "top_up": None, "top_down": None}
    ups = [r for r in enriched if (r.get("gap_pct") or 0) >= 0]
    downs = [r for r in enriched if (r.get("gap_pct") or 0) < 0]
    for r in enriched:
        t = r.get("tier") or "10%+"
        stats["tiers"][t] = stats["tiers"].get(t, 0) + 1
    if ups:
        u = max(ups, key=lambda r: r.get("gap_pct") or 0)
        stats["top_up"] = (u.get("symbol"), u.get("gap_pct"))
    if downs:
        d = min(downs, key=lambda r: r.get("gap_pct") or 0)
        stats["top_down"] = (d.get("symbol"), d.get("gap_pct"))
    return zbuf.getvalue(), date, stats


def build_caption(date, stats):
    n = stats["count"]
    tiers = " · ".join(f"{t}: {c}×" for t, c in
                       sorted(stats["tiers"].items(),
                              key=lambda kv: float(kv[0].rstrip("%+")),
                              reverse=True)) or "—"
    lines = [
        f"📊 <b>Gap Scan {date}</b>",
        f"📈 {n} stocks",
        f"🏷️ {tiers}",
    ]
    if stats["top_up"]:
        lines.append(f"🚀 Top: {stats['top_up'][0]} +{stats['top_up'][1]:.2f}%")
    if stats["top_down"]:
        lines.append(f"🔻 Flop: {stats['top_down'][0]} {stats['top_down'][1]:.2f}%")
    lines.append(f"-- via system-cron · send_gaps_zip.py")
    return "\n".join(lines)


def main():
    if not TOKEN or not CHAT:
        print("NEWS_TELEGRAM_BOT_TOKEN / NEWS_TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    data, date, stats = build_zip()

    caption = build_caption(date, stats)
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    resp = requests.post(url, data={"chat_id": CHAT, "caption": caption,
                                    "parse_mode": "HTML"},
                         files={"document": ("gaps.zip", data)},
                         timeout=30)
    if resp.status_code == 200:
        print(f"gaps.zip sent ({stats['count']} stocks, {len(data)} bytes)")
    else:
        print(f"Telegram error {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
