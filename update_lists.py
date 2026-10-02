#!/usr/bin/env python3
"""
Monthly Ticker List Updater
=============================
Updates the ticker lists for Dow Jones and S&P 500 from Wikipedia.
NASDAQ-100 uses a curated list (updated quarterly).
Run on the first trading day of each month via cron.

Usage:
  .venv/bin/python update_lists.py

Dependencies: requests, lxml  (the venv created by uv venv + manual pip install)
"""

import re
import time
import logging
import requests
from pathlib import Path
from datetime import datetime
from lxml import html as lxml_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("update-lists")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "StockScreener/1.0 (contact@nicks-technik.de)"}
TIMEOUT = 30
MAX_RETRIES = 4


def fetch_url(url):
    """GET with retries on 429/5xx (honors Retry-After, exponential backoff)."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = resp.headers.get("Retry-After")
                delay = int(wait) if (wait or "").isdigit() else 30 * attempt
                log.warning(f"HTTP {resp.status_code} (attempt {attempt}/{MAX_RETRIES}), waiting {delay}s...")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            log.warning(f"Request failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            time.sleep(15 * attempt)
    raise last_exc


def fetch_sp500_table():
    """
    Fetch the S&P 500 constituents table from Wikipedia.
    Parses the wikitable with lxml to extract tickers from the
    'Symbol' column only — avoids scraping index names, GICS text, etc.
    Returns: list of ticker strings (e.g. ['MMM', 'AOS', 'ABT', ...])
    """
    log.info("Fetching S&P 500 constituents from Wikipedia...")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = fetch_url(url)
    tree = lxml_html.fromstring(resp.text)

    # The current constituents table is the first wikitable on the page
    tables = tree.xpath('//table[contains(@class, "wikitable")]')
    if not tables:
        raise RuntimeError("No wikitable found on S&P 500 page")

    table = tables[0]
    rows = table.xpath(".//tr")

    # Identify the Symbol column by header text
    headers = [th.text_content().strip() for th in rows[0].xpath(".//th")]
    symbol_col = None
    company_col = None
    for i, h in enumerate(headers):
        if h.lower() in ("symbol", "ticker"):
            symbol_col = i
        if h.lower() == "security":
            company_col = i
    if symbol_col is None:
        symbol_col = 0
    if company_col is None:
        company_col = 1

    tickers = []
    name_to_ticker = {}
    for row in rows[1:]:
        cells = row.xpath(".//td")
        if not cells:
            continue
        ticker = cells[symbol_col].text_content().strip()
        company = cells[company_col].text_content().strip() if len(cells) > company_col else ticker
        if not ticker:
            continue
        # Wikipedia uses periods for dual-class shares (BRK.B, BF.B).
        # The rest of this project uses hyphens (BRK-B, BF-B).
        ticker = ticker.replace(".", "-")
        if ticker not in tickers:
            tickers.append(ticker)
            name_to_ticker[company] = ticker

    log.info(f"  Found {len(tickers)} S&P 500 tickers")
    return tickers, name_to_ticker


def fetch_dow_jones():
    """
    Fetch the 30 Dow Jones Industrial Average constituents from Wikipedia.
    The DJIA page lists company names in a bulleted list (no tickers).
    We cross-reference each company name against the S&P 500 table to
    recover ticker symbols, with a hardcoded fallback for any unmapped names.
    Returns: list of ticker strings
    """
    log.info("Fetching Dow Jones constituents from Wikipedia...")
    url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
    resp = fetch_url(url)
    tree = lxml_html.fromstring(resp.text)

    # The DJIA page includes a template that renders a bulleted list (<ul>)
    # of the 30 current constituent company names (not tickers).
    dow_names = _extract_dow_names(tree)

    # Cross-reference with the S&P 500 table to get tickers
    sp500_tickers, name_to_ticker = fetch_sp500_table()

    # Hardcoded fallback mapping for well-known DJIA constituents
    # that may not fuzzy-match the S&P 500 Security column.
    fallback = {
        "3M": "MMM",
        "Alphabet": "GOOGL",
        "Amazon": "AMZN",
        "American Express": "AXP",
        "Amgen": "AMGN",
        "Apple": "AAPL",
        "Boeing": "BA",
        "Caterpillar": "CAT",
        "Chevron": "CVX",
        "Cisco": "CSCO",
        "Coca-Cola": "KO",
        "Disney": "DIS",
        "Goldman Sachs": "GS",
        "Home Depot": "HD",
        "Honeywell Technologies": "HON",
        "IBM": "IBM",
        "Johnson & Johnson": "JNJ",
        "JPMorgan Chase": "JPM",
        "McDonald's": "MCD",
        "Merck": "MRK",
        "Microsoft": "MSFT",
        "Nike": "NKE",
        "Nvidia": "NVDA",
        "Procter & Gamble": "PG",
        "Salesforce": "CRM",
        "Sherwin-Williams": "SHW",
        "Travelers": "TRV",
        "UnitedHealth": "UNH",
        "Visa": "V",
        "Walmart": "WMT",
    }

    tickers = []
    unmapped = []
    for name in dow_names:
        ticker = _lookup_ticker(name, name_to_ticker, fallback)
        if ticker:
            tickers.append(ticker)
        else:
            unmapped.append(name)

    if unmapped:
        log.warning(f"  Could not map {len(unmapped)} DJIA names to tickers: {unmapped}")

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    log.info(f"  Found {len(deduped)} Dow Jones tickers")
    return deduped


def _extract_dow_names(tree):
    """
    Extract the 30 current DJIA constituent company names from the Wikipedia
    page. The names appear as a bulleted list inside <ul>/<ol> elements.
    We identify the list by checking it has ~30 entries and contains known
    DJIA companies.
    """
    lists = tree.xpath("//ul | //ol")
    known_companies = ["Apple", "Microsoft", "Goldman", "IBM", "JPMorgan"]

    for lst in lists:
        items = lst.xpath(".//a")
        item_texts = [a.text_content().strip() for a in items if a.text_content().strip()]
        if len(item_texts) >= 25 and len(item_texts) <= 35:
            matches = sum(1 for k in known_companies if any(k.lower() in t.lower() for t in item_texts))
            if matches >= 3:
                return item_texts

    # Fallback: parse from the raw HTML text
    return []


def _lookup_ticker(name, name_to_ticker, fallback):
    """
    Look up a DJIA company name's ticker:
    1. Exact match in the S&P 500 Security column
    2. Fuzzy match (name contained in or containing a Security name)
    3. Hardcoded fallback mapping
    """
    # 1. Exact match
    if name in name_to_ticker:
        return name_to_ticker[name]

    # 2. Fuzzy match
    name_lower = name.lower()
    best_match = None
    best_distance = float("inf")
    for sp_name, ticker in name_to_ticker.items():
        sp_lower = sp_name.lower()
        if name_lower in sp_lower or sp_lower in name_lower:
            # Prefer shorter (more precise) matches
            distance = abs(len(sp_name) - len(name))
            if distance < best_distance:
                best_match = ticker
                best_distance = distance
    if best_match:
        return best_match

    # 3. Hardcoded fallback
    return fallback.get(name)


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

    # Fetch S&P 500 (also builds the name->ticker lookup used by Dow)
    sp500_tickers = []
    try:
        sp500_tickers, name_to_ticker = fetch_sp500_table()
        if sp500_tickers:
            save_tickers("sp500_tickers.txt", sp500_tickers)
        else:
            log.warning("Could not fetch S&P 500; keeping existing file")
    except Exception as e:
        log.error(f"S&P 500 update failed: {e}; keeping existing file")
        # Still try Dow with fallback mapping
        name_to_ticker = {}

    time.sleep(2)

    # Update Dow Jones (cross-references S&P 500 table + fallback)
    try:
        # If S&P 500 fetch failed above, fetch it again for the name lookup
        if not name_to_ticker:
            _, name_to_ticker = fetch_sp500_table()
        dow = _fetch_dow_with_lookup(name_to_ticker)
        if dow:
            save_tickers("dow_jones.txt", dow)
        else:
            log.warning("Could not fetch Dow Jones; keeping existing file")
    except Exception as e:
        log.error(f"Dow Jones update failed: {e}; keeping existing file")

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


def _fetch_dow_with_lookup(name_to_ticker):
    """Fetch DJIA constituents using the S&P 500 name->ticker lookup + fallback."""
    url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
    resp = fetch_url(url)
    tree = lxml_html.fromstring(resp.text)
    dow_names = _extract_dow_names(tree)

    fallback = {
        "3M": "MMM",
        "Alphabet": "GOOGL",
        "Amazon": "AMZN",
        "American Express": "AXP",
        "Amgen": "AMGN",
        "Apple": "AAPL",
        "Boeing": "BA",
        "Caterpillar": "CAT",
        "Chevron": "CVX",
        "Cisco": "CSCO",
        "Coca-Cola": "KO",
        "Disney": "DIS",
        "Goldman Sachs": "GS",
        "Home Depot": "HD",
        "Honeywell Technologies": "HON",
        "IBM": "IBM",
        "Johnson & Johnson": "JNJ",
        "JPMorgan Chase": "JPM",
        "McDonald's": "MCD",
        "Merck": "MRK",
        "Microsoft": "MSFT",
        "Nike": "NKE",
        "Nvidia": "NVDA",
        "Procter & Gamble": "PG",
        "Salesforce": "CRM",
        "Sherwin-Williams": "SHW",
        "Travelers": "TRV",
        "UnitedHealth": "UNH",
        "Visa": "V",
        "Walmart": "WMT",
    }

    tickers = []
    unmapped = []
    for name in dow_names:
        ticker = _lookup_ticker(name, name_to_ticker, fallback)
        if ticker:
            tickers.append(ticker)
        else:
            unmapped.append(name)

    if unmapped:
        log.warning(f"  Could not map {len(unmapped)} DJIA names to tickers: {unmapped}")

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    return deduped


if __name__ == "__main__":
    main()
