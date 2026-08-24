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


def build_html(record: dict, rows: list[dict]) -> str:
    date = record.get("date", "?")
    scanned = record.get("scanned_at", "?")
    parts = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Gap scan {date}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background:#131722; color:#d1d4dc;
         margin:0; padding:20px }}
  h1 {{ font-size:1.3rem }}
  .meta {{ color:#787b86; margin-bottom:16px }}
  table {{ border-collapse:collapse; width:100%; font-size:.9rem }}
  th, td {{ padding:6px 10px; border-bottom:1px solid #2a2e39; text-align:left }}
  th {{ color:#787b86; font-weight:600 }}
  tr:hover td {{ background:#1e222d }}
  a {{ color:#2962ff; text-decoration:none; margin-right:8px }}
  a.d1 {{ color:#ff9800 }}
</style></head><body>
<h1>US Pre-Market Gap Scan - {date}</h1>
<div class="meta">Scanned {scanned} UTC · {len(rows)} stocks ·
TradingView chart links open with EMA(9) orange + SMA(20) blue</div>
<table>
<tr><th>#</th><th>Symbol</th><th>Gap %</th><th>Tier</th><th>PM Price</th>
<th>Prev Close</th><th>PM Vol</th><th>Mkt Cap</th><th>Sector</th>
<th>Name</th><th>Charts</th></tr>
"""]
    for i, r in enumerate(rows, 1):
        sym = r.get("symbol", "")
        gap = r.get("gap_pct", 0)
        color = "#26a69a" if gap > 0 else "#ef5350"
        base = f"https://www.tradingview.com/chart/0ZTktGqI/?symbol={sym}"
        links = (f'<a class="d1" href="{base}&interval=D" target="_blank">D1</a>'
                 f'<a href="{base}&interval=15" target="_blank">M15</a>'
                 f'<a href="{base}&interval=1" target="_blank">M1</a>')
        mcap = r.get("market_cap")
        mcap_s = f"{mcap/1e6:.0f}M" if mcap and mcap < 1e9 else (
                 f"{mcap/1e9:.1f}B" if mcap else "-")
        pmv = r.get("premarket_volume")
        pmv_s = f"{pmv/1e6:.1f}M" if pmv and pmv >= 1e6 else (
                f"{pmv/1e3:.0f}K" if pmv else "-")
        parts.append(
            f"<tr><td>{i}</td><td><b>{sym}</b></td>"
            f"<td style='color:{color}'>{gap:+.2f}%</td>"
            f"<td>{r.get('tier') or '10%+'}</td>"
            f"<td>{r.get('premarket_price') or '-'}</td>"
            f"<td>{r.get('close') or r.get('prev_close') or '-'}</td>"
            f"<td>{pmv_s}</td><td>{mcap_s}</td>"
            f"<td>{r.get('sector') or '-'}</td>"
            f"<td>{(r.get('description') or '')[:40]}</td>"
            f"<td>{links}</td></tr>")
    parts.append("</table></body></html>")
    return "\n".join(parts)


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
        z.writestr(f"gaps_{date}.html",
                   build_html(record, rows))
    return zbuf.getvalue(), date, len(rows)


def main():
    if not TOKEN or not CHAT:
        print("NEWS_TELEGRAM_BOT_TOKEN / NEWS_TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    data, date, count = build_zip()

    caption = (f"📦 Gap scan {date} - {count} stocks >= threshold\n"
               f"ZIP contains CSV + HTML (with D1/M15/M1 chart links)")
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
