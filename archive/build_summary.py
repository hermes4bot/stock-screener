#!/usr/bin/env python3
"""
Build and write the Notion summary page for today's gap scan.
Creates the page WITH children inline (the only way to add blocks to a page).
"""
import json
import os
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests

API_KEY = os.environ.get("NOTION_API_KEY") or (
    lambda: None or open("/home/hermes/.hermes/.env").read().split("NOTION_API_KEY=")[1].split("\n")[0].strip()
)()

DB_ID = "3c65af7e-2466-81d4-b59a-c20d4e19e7e1"
DATE = datetime.now().strftime("%Y-%m-%d")

def classify_tier(gp):
    if gp >= 50: return "50%+"
    elif gp >= 20: return "20%+"
    else: return "10%+"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def notion_post(url, data):
    r = requests.post(url, headers=HEADERS, json=data, timeout=30)
    try:
        return r.json()
    except:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}

def notion_get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    try:
        return r.json()
    except:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}

# Load latest gap data
hist_dir = Path("/home/hermes/dev/stock-screener/data/history")
latest = sorted(hist_dir.glob("tv_gaps_*.json"), reverse=True)[0]
with open(latest) as f:
    data = json.load(f)

gaps = data.get("gaps", [])
date_str = data.get("date", DATE)
scanned_at = data.get("scanned_at", "N/A")

# Stats
by_tier = {}
for g in gaps:
    t = classify_tier(g["gap_pct"])
    by_tier[t] = by_tier.get(t, 0) + 1

sorted_gaps = sorted(gaps, key=lambda g: g["gap_pct"])
top_loser = sorted_gaps[0] if sorted_gaps else None
top_winner = sorted_gaps[-1] if sorted_gaps else None

pos = [g for g in gaps if g["gap_pct"] > 0]
neg = [g for g in gaps if g["gap_pct"] < 0]

sector_counts = {}
for g in gaps:
    s = g.get("sector", "Other")
    sector_counts[s] = sector_counts.get(s, 0) + 1

now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

# Build content blocks
blocks = []

# Header H1
blocks.append({
    "object": "block",
    "type": "heading_1",
    "heading_1": {
        "rich_text": [{"type": "text", "text": {"content": f"📊 US Pre-Market Gap Scan — {date_str}"}}]
    }
})

# Stats paragraph
stats_md = (
    f"**Scanned at:** {scanned_at} UTC | "
    f"**Source:** TradingView Scanner\n\n"
    f"### Summary Statistics\n\n"
    f"| Metric | Value |\n"
    f"|--------|-------|\n"
    f"| Total gaps detected | {len(gaps)} |\n"
    f"| Positive gaps (up) | {len(pos)} |\n"
    f"| Negative gaps (down) | {len(neg)} |\n"
)
if top_winner:
    stats_md += f"| Best gain | {top_winner['symbol']} {top_winner['gap_pct']:+.2f}% |\n"
if top_loser:
    stats_md += f"| Worst drop | {top_loser['symbol']} {top_loser['gap_pct']:+.2f}% |\n"
if by_tier.get("10%+"):
    stats_md += f"| **10%+** tier | {by_tier['10%+']} |\n"
if by_tier.get("20%+"):
    stats_md += f"| **20%+** tier | {by_tier['20%+']} |\n"
if by_tier.get("50%+"):
    stats_md += f"| **50%+** tier | {by_tier['50%+']} |\n"

blocks.append({
    "object": "block",
    "type": "paragraph",
    "paragraph": {
        "rich_text": [{"type": "text", "text": {"content": stats_md}}]
    }
})

# Sector distribution
sector_md = "### Sector Distribution\n\n| Sector | Count |\n|--------|-------|\n"
for s, c in sorted(sector_counts.items(), key=lambda x: -x[1])[:10]:
    sector_md += f"| {s} | {c} |\n"

blocks.append({
    "object": "block",
    "type": "paragraph",
    "paragraph": {
        "rich_text": [{"type": "text", "text": {"content": sector_md}}]
    }
})

# Footer with links
footer_md = (
    f"🕒 **Last updated:** {now_str} Berlin | "
    f"**Next scan:** daily 10:15 UTC\n\n"
    f"📎 [Gap screener Web-App](http://10.53.164.28:8080) (interaktive Charts) | "
    f"📦 [Gaps ZIP](http://10.53.164.28:8080/gaps.zip) | "
    f"🔗 [Notion Datenbank](https://app.notion.com/p/{DB_ID})"
)

blocks.append({
    "object": "block",
    "type": "paragraph",
    "paragraph": {
        "rich_text": [{"type": "text", "text": {"content": footer_md}}]
    }
})

print(f"📊 Building Notion summary page for {date_str}")
print(f"   Gaps: {len(gaps)} | Tiers: 10%+: {by_tier.get('10%+')}, 20%+: {by_tier.get('20%+')}, 50%+: {by_tier.get('50%+')}")

# Create page WITH children inline
print("\nCreating summary page with blocks inline...")
page_data = {
    "parent": {"database_id": DB_ID},
    "properties": {
        "Symbol": [{"text": {"content": "📊 Summary"}}]
    },
    "children": blocks
}

resp = notion_post("https://api.notion.com/v1/pages", page_data)
if "id" in resp:
    page_id = resp["id"]
    url = resp.get("url", "?")
    print(f"\n✅ Created summary page: {page_id[:20]}...")
    print(f"   URL: {url}")
    print(f"   Blocks: {len(blocks)} added inline")
    print(f"\n   📊 {date_str} | {len(gaps)} gaps | updated {now_str}")
    print(f"   🔗 https://app.notion.com{page_id and '/p/' + page_id}")
else:
    print(f"\n❌ Error: {resp}")
    raise SystemExit(1)
