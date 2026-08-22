#!/usr/bin/env python3
"""
Market News Bot (RSS)
=====================
Fetches current market news from Google News RSS (plus optional extra feeds)
and delivers a formatted list via Telegram (or stdout).

Usage:
  .venv/bin/python news_bot.py [count]     # default 15

Environment:
  TELEGRAM_BOT_TOKEN   - optional, enables Telegram delivery
  TELEGRAM_CHAT_ID     - optional
  NEWS_QUERY           - Google News search query
                         (default: "stock market OR finance OR earnings")
"""

import os
import sys
import json
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 15
NEWS_QUERY = os.environ.get(
    "NEWS_QUERY", "stock market OR finance OR earnings"
)

# Dedicated Telegram bot for news delivery (falls back to the main bot).
# Set NEWS_TELEGRAM_BOT_TOKEN / NEWS_TELEGRAM_CHAT_ID in .env to split
# news traffic onto its own bot+group, away from the programming chat.
TELEGRAM_TOKEN = os.environ.get("NEWS_TELEGRAM_BOT_TOKEN",
                                os.environ.get("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT = os.environ.get("NEWS_TELEGRAM_CHAT_ID",
                               os.environ.get("TELEGRAM_CHAT_ID", ""))

DATA_DIR = Path(__file__).parent / "data"
HISTORY_DIR = DATA_DIR / "history"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("news-bot")

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Google News RSS topic/search feeds - all free, no API key.
# Add or remove feeds here.
FEEDS = [
    {
        "name": "Google News: Markets",
        "url": f"https://news.google.com/rss/search?q={quote(NEWS_QUERY)}&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "Google News: Business",
        "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
    },
]


def parse_feed(url: str) -> list[dict]:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for it in root.findall(".//item"):
        title_el = it.find("title")
        pub_el = it.find("pubDate")
        src_el = it.find("source")
        link_el = it.find("link")
        ts = 0
        if pub_el is not None and pub_el.text:
            try:
                ts = int(parsedate_to_datetime(pub_el.text).timestamp())
            except Exception:
                pass
        items.append({
            "headline": (title_el.text or "").strip() if title_el is not None else "",
            "source": (src_el.text or "").strip() if src_el is not None else "?",
            "url": (link_el.text or "").strip() if link_el is not None else "",
            "datetime": ts,
        })
    return items


def fetch_all() -> list[dict]:
    seen_urls = set()
    all_items = []
    for feed in FEEDS:
        try:
            items = parse_feed(feed["url"])
            log.info(f"  {feed['name']}: {len(items)} articles")
            for a in items:
                if a["url"] and a["url"] not in seen_urls:
                    seen_urls.add(a["url"])
                    all_items.append(a)
        except Exception as e:
            log.warning(f"  {feed['name']} failed: {e}")
    return all_items


def fmt_age(ts: int) -> str:
    if not ts:
        return "?"
    mins = max(0, int(time.time() - ts) // 60)
    if mins < 60:
        return f"{mins}m"
    h = mins // 60
    if h < 24:
        return f"{h}h{mins % 60:02d}"
    return f"{h // 24}d"


def build_message(articles: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📰 Market News - top {len(articles)} ({now})", ""]
    for i, a in enumerate(articles, 1):
        head = a["headline"].replace("\xa0", " ")
        if len(head) > 110:
            head = head[:107] + "..."
        lines.append(f"{i:2d}. [{fmt_age(a['datetime'])}] {head}")
        lines.append(f"      {a['source']}")
    return "\n".join(lines)


def save_history(articles: list[dict]) -> None:
    HISTORY_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = HISTORY_DIR / f"news_{today}.json"
    record = {}
    if path.exists():
        try:
            record = json.loads(path.read_text())
        except Exception:
            record = {}
    record.update({
        "date": today,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feeds": [f["name"] for f in FEEDS],
        "count": len(articles),
        "articles": articles,
    })
    path.write_text(json.dumps(record, indent=2))
    log.info(f"History saved: {path}")


def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print(text)
        return False
    ok = True
    for i in range(0, len(text), 4000):  # Telegram limit: 4096 chars
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text[i:i + 4000]},
            timeout=30,
        )
        if resp.status_code != 200:
            log.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
            ok = False
    if ok:
        log.info("Telegram message sent")
    return ok


def main():
    log.info("Fetching news from RSS feeds...")
    articles = fetch_all()
    if not articles:
        log.error("No articles fetched")
        sys.exit(1)

    articles.sort(key=lambda a: a["datetime"], reverse=True)
    top = articles[:COUNT]
    log.info(f"{len(articles)} unique articles, sending top {len(top)}")

    save_history(top)
    send_telegram(build_message(top))


if __name__ == "__main__":
    main()
