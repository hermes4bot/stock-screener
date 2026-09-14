#!/usr/bin/env python3
"""
Create Notion Summary page as child of the Gap Screener database
with statistics about today's scan.
"""
import json
import subprocess
import os
import urllib.parse
from pathlib import Path

def classify_tier(gp):
    if gp >= 50: return "50%+"
    elif gp >= 20: return "20%+"
    else: return "10%+"

API_KEY = os.environ.get("NOTION_API_KEY") or (
    lambda: None or open("/home/hermes/.hermes/.env").read().split("NOTION_API_KEY=")[1].split("\n")[0].strip()
)()

DB_ID = "3c65af7e-2466-81d4-b59a-c20d4e19e7e1"
DATE = "2026-08-24"

# Build summary content
def summary_markdown(gaps, date):
    by_tier = {}
    for g in gaps:
        t = classify_tier(g["gap_pct"])
        by_tier[t] = by_tier.get(t, 0) + 1
    total = len(gaps)
    pos_gaps = [g for g in gaps if g["gap_pct"] > 0]
    neg_gaps = [g for g in gaps if g["gap_pct"] < 0]
    sorted_gaps = sorted(gaps, key=lambda g: g["gap_pct"])
    top_loser = sorted_gaps[0] if sorted_gaps else None
    top_winner = sorted_gaps[-1] if sorted_gaps else None
    
    sector_counts = {}
    for g in gaps:
        s = g.get("sector", "Other")
        sector_counts[s] = sector_counts.get(s, 0) + 1
    sector_table = "".join(f"\n||{s}||{c}||" for s, c in sorted(sector_counts.items(), key=lambda x: -x[1]))
    
    lines = [
        f"## 📊 US Pre-Market Gap Scan — {date}",
        "",
        f"**Scanned at:** 2026-08-24 10:15 UTC | **Source:** TradingView Scanner",
        "",
        f"### Summary Statistics",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total gaps detected | {total} |",
        f"| Positive gaps (up) | {len(pos_gaps)} |",
        f"| Negative gaps (down) | {len(neg_gaps)} |",
        f"| Strongest gap (winner) | {top_winner['symbol']} {top_winner['gap_pct']:+.2f}% |" if top_winner else f"| Strongest gap (winner) | — |",
        f"| Largest gap (loser) | {top_loser['symbol']} {top_loser['gap_pct']:+.2f}% |" if top_loser else f"| Largest gap (loser) | — |",
        f"| 10%+ tier count | {by_tier.get('10%+', 0)} |",
        f"| 20%+ tier count | {by_tier.get('20%+', 0)} |",
        f"| 50%+ tier count | {by_tier.get('50%+', 0)} |",
        "",
        f"### Sector Distribution",
        "",
        f"| Sector | Count |",
        f"|--------|-------|{sector_table}",
        "",
        f"### Data Freshness",
        "",
        f"Daten wurden täglich um 10:15 Uhr (Berlin) aktualisiert. Letzter Scan: {date}.",
        "",
        f"### TradingView Links",
        "",
        f"Alle Charts enthalten **EMA(9) orange** und **SMA(20) blau**. Klicke auf den D1- oder M15-Link, um den Chart in TradingView zu öffnen.",
        "",
        f"📎 [Gap screener Web-App](http://10.53.164.28:8080) (für interaktive Charts)",
        "",
        f"📦 [Gaps ZIP herunterladen](https://github.com/hermes4bot/stock-screener/releases/latest) für vollständige Daten inkl. alle Symbole.",
        "",
        f"---",
        f"",
        f"🕒 **Nächster geplanter Scan:** 2026-08-25 10:15 UTC (Berliner Zeit)",
    ]
    return "\n".join(lines)

# Load data and create summary
hist_dir = Path("/home/hermes/dev/stock-screener/data/history")
latest = sorted(hist_dir.glob("tv_gaps_*.json"))[-1]
with open(latest) as f:
    data = json.load(f)
gaps = data.get("gaps", [])
date = data.get("date", "2026-08-24")

summary_content = summary_markdown(gaps, date)

# Create Notion page with summary content
import requests

page_payload = {
    "parent": {"database_id": DB_ID},
    "properties": {
        "Symbol": {"title": [{"text": {"content": "📊 Summary"}}]}
    },
    "children": []
}

# Add bullet points as content blocks...[truncated]