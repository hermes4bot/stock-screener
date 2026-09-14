#!/usr/bin/env python3
"""
Daily gap screener cron job:
1. Run the TradingView gap scan
2. Save results to data/history/tv_gaps_YYYY-MM-DD.json
3. Send summary to News Group via Telegram
4. Insert gaps into Notion database
5. Update/create summary page in Notion
"""
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
HISTORY_DIR = SCRIPT_DIR / "data" / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# Config
DB_ID = "3c65af7e-2466-81d4-b59a-c20d4e19e7e1"
TV_BASE = "https://www.tradingview.com/chart/0ZTktGqI/"
STUDIES = "%5B%5B%22MAExp%40tv-basicstudies%22%2C%7B%22length%22%3A9%7D%5D%2C%5B%22MASimple%40tv-basicstudies%22%2C%7B%22length%22%3A20%7D%5D"
M1_FROM = 1756013400  # 2026-08-24 09:30 UTC
M1_TO = 1756100000    # ~24h later
NEWS_BOT_TOKEN = os.environ.get("NEWS_TELEGRAM_BOT_TOKEN", "")
NEWS_CHAT_ID = os.environ.get("NEWS_TELEGRAM_CHAT_ID", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")

def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}")

def run(cmd, **kwargs):
    log(f"Running: {cmd}")
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)

def classify_tier(gp):
    if gp >= 50: return "50%+"
    elif gp >= 20: return "20%+"
    else: return "10%+"

def make_tv_url(sym, iv, frm=None, to=None):
    p = {"symbol": f"NASDAQ:{sym}", "interval": iv, "studies": STUDIES, "theme": "dark"}
    if frm: p["from"] = frm
    if to: p["to"] = to
    return TV_BASE + "?" + urllib.parse.urlencode(p)

def send_telegram(text):
    if not NEWS_BOT_TOKEN or not NEWS_CHAT_ID:
        log("Telegram: no credentials configured, printing to stdout")
        print(text)
        return False
    import requests
    url = f"https://api.telegram.org/bot{NEWS_BOT_TOKEN}/sendMessage"
    ok = True
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        try:
            r = requests.post(url, json={
                "chat_id": NEWS_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }, timeout=30)
            if r.status_code != 200:
                log(f"Telegram error: {r.status_code}")
                ok = False
                break
        except Exception as e:
            log(f"Telegram exception: {e}")
            ok = False
            break
    return ok

def insert_gaps_to_notion(gaps, date_str):
    """Insert all gap records into Notion database."""
    if not NOTION_API_KEY:
        log("Notion: no API key, skipping")
        return
    
    import requests
    
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    inserted = 0
    errors = []
    
    with open("/tmp/notion_gaps_payload.jsonl", "w") as f:
        for g in gaps:
            sym = g["symbol"].strip()
            item = {
                "parent": {"database_id": DB_ID},
                "properties": {
                    "Symbol": {"title": [{"text": {"content": sym}}]},
                    "Gap_%": {"number": round(g["gap_pct"], 4)},
                    "Tier": {"select": {"name": classify_tier(g["gap_pct"])}},
                    "Pre-Market_Price": {"number": g.get("premarket_price")},
                    "Previous_Close": {"number": g.get("close")},
                    "Volume": {"number": int(g.get("volume", 0) or 0)},
                    "Market_Cap": {"number": int(g.get("market_cap", 0) or 0)},
                    "Sector": {"select": {"name": (g.get("sector", "") or "").strip() or "Other"}},
                    "Description": {"rich_text": [{"text": {"content": g.get("description", "") or ""}}]},
                    "TV_D1": {"url": make_tv_url(sym, "D")},
                    "TV_M15": {"url": make_tv_url(sym, "15")},
                    "TV_M1": {"url": make_tv_url(sym, "1", M1_FROM, M1_TO)},
                    "Date": {"date": {"start": date_str}}
                }
            }
            f.write(json.dumps(item) + "\n")
    
    with open("/tmp/notion_gaps_payload.jsonl") as f:
        for line in f:
            resp = requests.post("https://api.notion.com/v1/pages", headers=headers,
                data=line, timeout=30)
            if resp.status_code == 200:
                inserted += 1
            else:
                err = resp.json().get("message", "unknown error")
                errors.append(f"{err[:60]}")
                log(f"Notion insert error: {err[:80]}")
    
    log(f"Notion: inserted {inserted}/{len(gaps)} pages")
    if errors:
        log(f"Notion: {len(errors)} errors - first: {errors[0]}")
    return inserted

def update_summary_page(gaps, date_str):
    """Create or update the summary page in Notion database."""
    if not NOTION_API_KEY:
        return
    
    import requests
    
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # First, search for existing summary page
    resp = requests.post("https://api.notion.com/v1/search", headers=headers,
        json={"query": "📊 Summary", "filter": {"value": "page", "property": "object"},
              "page_size": 5})
    
    results = resp.json().get("results", [])
    summary_page = None
    for r in results:
        p = r.get("properties", {})
        sym = p.get("Symbol", {}).get("title", [{}])[0].get("plain_text", "")
        if "Summary" in sym:
            summary_page = r
            break
    
    # Build summary content
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
    
    # Content blocks
    blocks = []
    
    # Header
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": f"📊 US Pre-Market Gap Scan — {date_str}"}}]
        }
    })
    
    # Stats table
    stats_text = (
        f"**Scanned at:** {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC | "
        f"**Source:** TradingView Scanner\n\n"
        f"### Summary Statistics\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Total gaps | {len(gaps)} |\n"
        f"| Positive (up) | {len(pos)} |\n"
        f"| Negative (down) | {len(neg)} |\n"
    )
    if top_winner:
        stats_text += f"| Best gain | {top_winner['symbol']} {top_winner['gap_pct']:+.2f}% |\n"
    if top_loser:
        stats_text += f"| Worst drop | {top_loser['symbol']} {top_loser['gap_pct']:+.2f}% |\n"
    stats_text += (
        f"| **10%+** tier | {by_tier.get('10%+', 0)} |\n"
        f"| **20%+** tier | {by_tier.get('20%+', 0)} |\n"
        f"| **50%+** tier | {by_tier.get('50%+', 0)} |\n"
    )
    
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": stats_text}}]
        }
    })
    
    # Sector distribution
    sector_text = "### Sector Distribution\n\n| Sector | Count |\n|--------|-------|\n"
    for s, c in sorted(sector_counts.items(), key=lambda x: -x[1]):
        sector_text += f"| {s} | {c} |\n"
    
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": sector_text}}]
        }
    })
    
    # Date updated
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": f"🕒 **Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} Berlin | Next scan: daily 10:15 UTC"}}]
        }
    })
    
    if summary_page:
        # Update existing page
        page_id = summary_page["id"]
        log(f"Updating existing summary page {page_id[:20]}...")
        
        # Clear existing content blocks
        existing = requests.post(f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers, json={"page_size": 100}).json()
        for blk in existing.get("results", []):
            requests.patch(f"https://api.notion.com/v1/blocks/{blk['id']}",
                headers=headers, json={"archived": True})
        
        # Add new blocks
        for block in blocks:
            requests.post(f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers=headers, json={"children": [block]}, timeout=15)
        
        log(f"Summary page updated: {page_id[:20]}")
    else:
        # Create new page
        log("Creating new summary page...")
        page_payload = {
            "parent": {"database_id": DB_ID},
            "properties": {
                "Symbol": {"title": [{"text": {"content": "📊 Summary"}}]}
            },
            "children": blocks
        }
        resp = requests.post("https://api.notion.com/v1/pages", headers=headers,
            json=page_payload, timeout=30)
        
        if resp.status_code == 200:
            new_page = resp.json()
            log(f"Summary page created: {new_page.get('id', '?')[:20]}")
        else:
            log(f"Failed to create summary: {resp.status_code} {resp.text[:200]}")

def main():
    today_str = datetime.now().strftime("%Y-%m-%d")
    log(f"=== Daily gap screener cron ({today_str}) ===")
    
    # Step 1: Run the scan (if tv_gaps.py exists)
    tv_gaps = SCRIPT_DIR / "tv_gaps.py"
    if tv_gaps.exists():
        log("Step 1: Running TradingView gap scan...")
        result = run([sys.executable, str(tv_gaps), "10", "--save"], timeout=300)
        if result.returncode != 0:
            log(f"tv_gaps.py failed: {result.stderr[:500]}")
            # Try to continue with existing data
    else:
        log("tv_gaps.py not found, skipping scan step")
    
    # Step 2: Load the latest results
    history_files = sorted(HISTORY_DIR.glob("tv_gaps_*.json"), reverse=True)
    if not history_files:
        log("No history files found, exiting")
        return
    
    latest_file = history_files[0]
    log(f"Loading: {latest_file.name}")
    with open(latest_file) as f:
        data = json.load(f)
    
    gaps = data.get("gaps", [])
    date = data.get("date", today_str)
    log(f"Found {len(gaps)} gaps from {date}")
    
    # Step 3: Send Telegram summary
    log("Step 3: Sending summary to News Group...")
    summary_lines = [
        f"<b>📊 US Pre-Market Gap Scan — {date}</b>",
        "",
        f"<b>Scanned at:</b> {data.get('scanned_at', 'N/A')} UTC",
        f"<b>Source:</b> TradingView Scanner",
        f"<b>Min threshold:</b> {data.get('min_gap_pct', 10)}%",
        "",
        f"<b>Total gaps:</b> {len(gaps)}",
        ""
    ]
    
    # By tier
    by_tier = {}
    for g in gaps:
        t = classify_tier(g["gap_pct"])
        by_tier[t] = by_tier.get(t, 0) + 1
    
    for tier_name in ["50%+", "20%+", "10%+"]:
        count = by_tier.get(tier_name, 0)
        summary_lines.append(f"   {tier_name}: {count}")
    
    summary_lines.append("")
    summary_lines.append("<b>Top movers:</b>")
    
    sorted_gaps = sorted(gaps, key=lambda g: g["gap_pct"])
    if sorted_gaps:
        summary_lines.append(f"   🔻 Worst: {sorted_gaps[0]['symbol']} {sorted_gaps[0]['gap_pct']:+.2f}%")
        summary_lines.append(f"   🔺 Best:  {sorted_gaps[-1]['symbol']} {sorted_gaps[-1]['gap_pct']:+.2f}%")
    
    summary_lines.append("")
    summary_lines.append(f"<b>Web-App:</b> http://10.53.164.28:8080")
    summary_lines.append(f"<b>ZIP download:</b> /gaps.zip")
    summary_lines.append(f"<b>Notion DB:</b> https://app.notion.com/p/{DB_ID}")
    
    summary_text = "\n".join(summary_lines)
    send_telegram(summary_text)
    
    # Step 4: Insert into Notion
    log("Step 4: Inserting gaps into Notion...")
    insert_gaps_to_notion(gaps, date)
    
    # Step 5: Update summary page
    log("Step 5: Updating summary page...")
    update_summary_page(gaps, date)
    
    log("=== Done ===")

if __name__ == "__main__":
    main()
