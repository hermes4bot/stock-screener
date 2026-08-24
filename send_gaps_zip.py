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

TOKEN = os.environ.get("NEWS_TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("NEWS_TELEGRAM_CHAT_ID", "")


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
    rows = record.get("gaps", record.get("results", []))

    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["symbol", "gap_pct", "tier", "premarket_price", "prev_close",
                "premarket_volume", "market_cap", "sector", "description"])
    for r in rows:
        w.writerow([
            r.get("symbol"), r.get("gap_pct"), r.get("tier") or "10%+",
            r.get("premarket_price"), r.get("close") or r.get("prev_close"),
            r.get("premarket_volume"), r.get("market_cap"),
            r.get("sector"), r.get("description"),
        ])

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"gaps_{date}.csv", buf.getvalue())
    return zbuf.getvalue(), date, len(rows)


def main():
    if not TOKEN or not CHAT:
        print("NEWS_TELEGRAM_BOT_TOKEN / NEWS_TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    data, date, count = build_zip()

    caption = (f"📦 Gap scan {date} - {count} stocks >= threshold\n"
               f"ZIP contains CSV: symbol, gap%, tier, prices, volume, mcap")
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    resp = requests.post(url, data={"chat_id": CHAT, "caption": caption},
                         files={"document": ("gaps.zip", data)},
                         timeout=30)
    if resp.status_code == 200:
        print(f"gaps.zip sent ({count} stocks, {len(data)} bytes)")
    else:
        print(f"Telegram error {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
