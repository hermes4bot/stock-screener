#!/usr/bin/env python3
"""
Monthly Ticker List Updater
=============================
Updates the ticker lists for Dow Jones, S&P 500.
NASDAQ-100 uses a curated list (updated quarterly).
Run on the first trading day of each month via cron.

Usage:
  .venv/bin/python update_lists.py
"""

import re
import sys
import time
import logging
import requests
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("update-lists")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "StockScreener/1.0 (contact@example.com)"}
TIMEOUT = 30


def fetch_wikipedia_sp500():
    """Fetch S&P 500 constituents from Wikipedia."""
    log.info("Fetching S&P 500 constituents from Wikipedia...")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    tickers = []
    seen = set()

    # Wikipedia S&P 500 table: tickers appear as <a href="/wiki/...">TICKER</a>
    matches = re.findall(r'>([A-Z]{1,5}\.?[A-Z]*)\s*</a>', html)
    for t in matches:
        t = t.strip()
        if (
            t
            and re.match(r'^[A-Z]{1,5}\.?[A-Z]*$', t)
            and 1 <= len(t.replace(".", "")) <= 6
            and t not in seen
            and t not in ("NYSE", "NASDAQ", "GICS", "SECTOR", "INDX")
        ):
            seen.add(t)
            tickers.append(t.replace(".", "-"))  # BRK.B -> BRK-B

    log.info(f"  Found {len(tickers)} S&P 500 tickers")
    return tickers


def fetch_wikipedia_dow():
    """Fetch Dow Jones constituents from Wikipedia."""
    log.info("Fetching Dow Jones constituents from Wikipedia...")
    url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    tickers = []
    seen = set()

    # DJIA Wikipedia: tickers appear in table cells or span elements
    matches = re.findall(r'>([A-Z]{1,5})\s*</a>', html)
    for t in matches:
        t = t.strip()
        if t and t not in seen and len(t) <= 5 and t not in ("DJIA", "NYSE", "NASDAQ", "INDEX"):
            seen.add(t)
            tickers.append(t)

    # If too few, try span pattern
    if len(tickers) < 25:
        span_matches = re.findall(r'<span[^>]*>([A-Z]{1,5})\s*</span>', html)
        for t in span_matches:
            t = t.strip()
            if t and t not in seen and len(t) <= 5:
                seen.add(t)
                tickers.append(t)

    tickers = tickers[:40]  # DJIA has 30
    log.info(f"  Found {len(tickers)} Dow Jones tickers")
    return tickers


def save_tickers(filename, tickers):
    """Save tickers to a data file with header."""
    filepath = DATA_DIR / filename
    header = f"# {filename.replace('.txt', '').replace('_', ' ').title()}\n# Updated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    with open(filepath, "w") as f:
        f.write(header)
        for t in tickers:
            f.write(f"{t}\n")
    log.info(f"  Saved {len(tickers)} tickers to {filepath}")


def main():
    log.info("=" * 60)
    log.info("Monthly Ticker List Updater")
    log.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # Update Dow Jones
    try:
        dow = fetch_wikipedia_dow()
        if dow:
            save_tickers("dow_jones.txt", dow)
        else:
            log.warning("Could not fetch Dow Jones; keeping existing file")
    except Exception as e:
        log.error(f"Dow Jones update failed: {e}; keeping existing file")

    time.sleep(2)

    # Update S&P 500
    try:
        sp500 = fetch_wikipedia_sp500()
        if sp500:
            save_tickers("sp500_tickers.txt", sp500)
        else:
            log.warning("Could not fetch S&P 500; keeping existing file")
    except Exception as e:
        log.error(f"S&P 500 update failed: {e}; keeping existing file")

    # Check NASDAQ-100
    log.info("NASDAQ-100: using curated list (update quarterly if needed)")
    nasdaq_path = DATA_DIR / "nasdaq_100.txt"
    if nasdaq_path.exists():
        with open(nasdaq_path) as f:
            count = sum(1 for line in f if line.strip() and not line.startswith("#"))
        log.info(f"  Existing nasdaq_100.txt has {count} tickers")
    else:
        log.warning(f"  {nasdaq_path} not found")

    log.info("Done.")


if __name__ == "__main__":
    main()
