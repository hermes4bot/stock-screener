#!/usr/bin/env python3
"""
Stock Gap Scanner - Pre-Market Gap Detection for US Markets
============================================================

Scans major US indices and the full US stock market for pre-market
price gaps >= 50% using Finnhub's real-time US stock quotes.

Features:
  - Detects gap-up and gap-down moves >= 50%
  - Caches quote results to JSON for reuse within a 5-minute window
  - Scans Dow, S&P 500, NASDAQ-100, or full US market (all symbols)
  - Optional EMA(9)/SMA(20)/SMA(200) via Twelve Data (--indicators)
  - Saves monthly scan results for gap-frequency analysis

Usage:
  .venv/bin/python scan_gaps.py [dow|sp500|nasdaq|all|full] [--save] [--indicators]

  Default: scans "dow" if no argument given.
  --save: saves results to data/gap_results_YYYY-MM-DD.json

Environment:
  FINNHUB_API_KEY   - your Finnhub API key (required)
  GAP_THRESHOLD     - gap percentage threshold (default: 0.50 = 50%)
  TWELVEDATA_API_KEY - Twelve Data key for EMA/SMA (optional, demo works)
"""


import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path

import finnhub
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("FINNHUB_API_KEY", "")
GAP_THRESHOLD = float(os.environ.get("GAP_THRESHOLD", "0.50"))  # 50%
# Twelve Data API key for EMA/SMA candles (free tier: 800 calls/day)
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "demo")  # demo works for testing

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
CACHE_FILE = DATA_DIR / "quotes_cache.json"
DATA_DIR.mkdir(exist_ok=True)

# Cache validity - 5 minutes
CACHE_TTL = 300

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("gap-scanner")

# ---------------------------------------------------------------------------
# Ticker list loading (from cached files in data/ or Finnhub API)
# ---------------------------------------------------------------------------

def load_ticker_file(filename: str) -> list[str]:
    """Load tickers from a text file (one per line, skip comments/blanks)."""
    filepath = DATA_DIR / filename
    if filepath.exists():
        with open(filepath) as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
    return []


def get_all_us_stocks(client: finnhub.Client) -> list[str]:
    """Fetch ALL US stock symbols from Finnhub.
    Filters to Common Stock on major US exchanges (NYSE, NASDAQ, AMEX, ARCA).
    Results are cached in data/all_us_stocks.txt for reuse.
    """
    # Check if we have a cached list
    filepath = DATA_DIR / "all_us_stocks.txt"
    if filepath.exists():
        with open(filepath) as f:
            tickers = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        if tickers:
            log.info(f"Loaded {len(tickers)} US stocks from cache: {filepath}")
            return tickers

    # Fetch from Finnhub
    log.info("Fetching all US stock symbols from Finnhub...")
    try:
        symbols = client.stock_symbols("US")
    except Exception as e:
        log.error(f"Failed to fetch stock symbols: {e}")
        return []

    # Filter: Common Stock, USD currency, major exchanges
    valid_mics = {"XNYS", "XNAS", "XASE", "ARCA"}  # NYSE, NASDAQ, AMEX, ARCA
    tickers = [
        s["symbol"]
        for s in symbols
        if s.get("type") == "Common Stock"
        and s.get("currency") == "USD"
        and s.get("mic") in valid_mics
    ]

    # Save to cache
    with open(filepath, "w") as f:
        f.write(f"# All US Common Stock symbols (cached: {datetime.now().isoformat()})\n")
        for t in tickers:
            f.write(f"{t}\n")

    log.info(f"Fetched {len(tickers)} US stock symbols, saved to {filepath}")
    return tickers


def get_dow_jones() -> list[str]:
    """Dow Jones Industrial Average constituents (30 tickers)."""
    tickers = load_ticker_file("dow_jones.txt")
    if tickers:
        return tickers
    # Fallback: actual DJIA 30 (as of 2024-2025)
    return [
        "AAPL", "AMGN", "AMZN", "AXP", "BA", "BAC", "BK", "BMY", "C", "CAT",
        "CHTR", "CRM", "CVX", "DAL", "DD", "DOW", "GS", "HON", "INTC", "JNJ",
        "JPM", "JWN", "KO", "MCD", "MRK", "MSFT", "NKE", "PG", "RTX", "TRV",
        "UNH", "UPS", "V", "VZ", "WBA", "WMT",
    ]


def get_sp500() -> list[str]:
    """S&P 500 constituents (fetched from Wikipedia, cached in data/)."""
    return load_ticker_file("sp500_tickers.txt")


def get_nasdaq_100() -> list[str]:
    """NASDAQ-100 constituents (fetched from NASDAQ, cached in data/)."""
    return load_ticker_file("nasdaq_100.txt")


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def load_cache() -> dict:
    """Load cached quote data from JSON file."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cache(cache: dict) -> None:
    """Save quote cache to JSON file."""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)
    log.info(f"Cache saved: {len(cache)} entries -> {CACHE_FILE}")


def get_cached_quote(symbol: str, cache: dict) -> dict | None:
    """Return cached quote if fresh, else None."""
    if symbol in cache:
        entry = cache[symbol]
        now = time.time()
        if now - entry.get("cached_at", 0) < CACHE_TTL:
            return entry["quote"]
    return None


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def fetch_quote(symbol: str, client: finnhub.Client) -> dict | None:
    """Fetch real-time quote from Finnhub."""
    try:
        q = client.quote(symbol)
        if not q or q.get("s") == "no_data":
            return None
        return q
    except finnhub.exceptions.FinnhubAPIException as e:
        msg = str(e)
        if "429" in msg or "rate" in msg.lower():
            log.warning(f"Rate limited at {symbol}, sleeping 62s")
            time.sleep(62)
            return None
        return None
    except Exception:
        return None


def detect_gap(symbol: str, quote: dict) -> dict | None:
    """
    Detect pre-market gap >= GAP_THRESHOLD.
    Finnhub /quote returns:
      c  - current price (includes pre-market)
      pc - previous close
    Gap = (current - previous_close) / previous_close
    """
    prev_close = quote.get("pc")
    current = quote.get("c")

    if not prev_close or not current or prev_close <= 0:
        return None

    gap_pct = (current - prev_close) / prev_close

    if abs(gap_pct) < GAP_THRESHOLD:
        return None

    direction = "UP" if gap_pct > 0 else "DOWN"
    return {
        "symbol": symbol,
        "prev_close": round(prev_close, 2),
        "current": round(current, 2),
        "gap_pct": round(gap_pct * 100, 2),
        "direction": direction,
    }


def check_symbol(symbol: str, client: finnhub.Client, cache: dict) -> dict | None:
    """Check a single symbol for gaps, using cache when fresh."""
    # Try cache first
    q = get_cached_quote(symbol, cache)
    if q is None:
        q = fetch_quote(symbol, client)
        if q:
            cache[symbol] = {"quote": q, "cached_at": time.time()}

    if not q:
        return None

    gap = detect_gap(symbol, q)
    if gap:
        log.info(f"  GAP: {symbol} {gap['direction']} {gap['gap_pct']:.1f}% "
                 f"(${gap['prev_close']:.2f} -> ${gap['current']:.2f})")
    return gap


# ---------------------------------------------------------------------------
# EMA/SMA enrichment via Twelve Data
# ---------------------------------------------------------------------------

CANDLE_CACHE_FILE = DATA_DIR / "candles_cache.json"
CANDLE_CACHE_TTL = 3600  # 1 hour for candle data (prices don't change intraday)


def fetch_daily_closes(symbol: str, num_days: int = 210) -> list[float]:
    """Fetch daily close prices from Twelve Data.
    Free tier supports 20 years of daily data - we only need the last ~200 closes.
    Results are cached for 1 hour to avoid redundant API calls and stay under limits.
    """
    # Try cache first
    cache = load_cache_from_file(CANDLE_CACHE_FILE)
    if symbol in cache:
        entry = cache[symbol]
        if time.time() - entry.get("cached_at", 0) < CANDLE_CACHE_TTL:
            log.debug(f"  [cache] Candle data for {symbol}")
            return entry["closes"]

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": str(num_days),
        "apikey": TWELVEDATA_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if "values" not in data:
            log.debug(f"  No candle data for {symbol}: {data.get('message', 'unknown error')}")
            return []
        closes = [float(v["close"]) for v in reversed(data["values"])]

        # Cache the result
        cache[symbol] = {"closes": closes, "cached_at": time.time()}
        save_cache_to_file(cache, CANDLE_CACHE_FILE)

        log.debug(f"  Fetched {len(closes)} closes for {symbol}")
        return closes
    except Exception as e:
        log.debug(f"  Candle fetch error for {symbol}: {e}")
        return []


def load_cache_from_file(filepath: Path) -> dict:
    """Load a cache file."""
    if filepath.exists():
        try:
            with open(filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cache_to_file(cache: dict, filepath: Path) -> None:
    """Save cache to a file."""
    with open(filepath, "w") as f:
        json.dump(cache, f, indent=2)


def compute_indicators(closes: list[float]) -> dict | None:
    """Compute EMA(9), SMA(20), SMA(200) from daily close prices.
    Only needs as many closes as the longest window (200).
    """
    if len(closes) < 200:
        log.debug(f"  Only {len(closes)} closes - need 200 for SMA(200)")
        return None

    series = pd.Series(closes)
    ema9 = series.ewm(span=9, adjust=False).mean().iloc[-1]
    sma20 = series.rolling(window=20).mean().iloc[-1]
    sma200 = series.rolling(window=200).mean().iloc[-1]
    current = series.iloc[-1]

    return {
        "ema9": round(ema9, 2),
        "sma20": round(sma20, 2),
        "sma200": round(sma200, 2),
        "current": round(current, 2),
        "above_ema9": current > ema9,
        "above_sma20": current > sma20,
        "above_sma200": current > sma200,
    }


def enrich_gaps(gaps: list[dict]) -> list[dict]:
    """Enrich gap results with EMA/SMA indicators from Twelve Data."""
    if not gaps:
        return gaps

    log.info(f"\nEnriching {len(gaps)} gap stocks with EMA(9)/SMA(20)/SMA(200)...")

    for i, gap in enumerate(gaps):
        symbol = gap["symbol"]
        closes = fetch_daily_closes(symbol, num_days=210)
        if closes:
            ind = compute_indicators(closes)
            if ind:
                gap["indicators"] = ind
                log.info(f"  {symbol}: EMA9={ind['ema9']} SMA20={ind['sma20']} SMA200={ind['sma200']}")
            else:
                gap["indicators"] = None
        else:
            gap["indicators"] = None
        time.sleep(0.5)  # Small delay between candle requests

    return gaps


# ---------------------------------------------------------------------------
# Index scanning
# ---------------------------------------------------------------------------

def scan_index(name: str, symbols: list[str], client: finnhub.Client, cache: dict, parallel: bool = False) -> list[dict]:
    """Scan one index for gaps. Returns list of gap results.
    
    When parallel=True, uses multiple threads with a rate limiter to stay
    under Finnhub's 60 calls/min limit. Best for large symbol lists.
    """
    log.info(f"\n{'=' * 60}")
    log.info(f"Scanning {name}: {len(symbols)} symbols")
    log.info(f"{'=' * 60}")

    if parallel:
        gaps = scan_index_parallel(name, symbols, cache)
    else:
        gaps = []
        last_call_time = 0
        calls_this_minute = 0
        minute_start = time.time()

        for i, symbol in enumerate(symbols):
            result = check_symbol(symbol, client, cache)
            if result:
                gaps.append(result)

            if (i + 1) % 50 == 0:
                log.info(f"  Progress: {i + 1}/{len(symbols)} | gaps: {len(gaps)}")

            # Rate limit: Finnhub free tier = 60 calls/min
            now = time.time()
            if calls_this_minute >= 58:
                sleep_time = 60 - (now - minute_start)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                calls_this_minute = 0
                minute_start = time.time()
            else:
                elapsed = now - last_call_time
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                calls_this_minute += 1
                last_call_time = time.time()

    # Persist cache
    save_cache(cache)
    return gaps


def scan_index_parallel(name: str, symbols: list[str], cache: dict) -> list[dict]:
    """Scan symbols in parallel using threads + rate limiter.
    Stays under 58 calls/min via a shared rate limiter.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    # Rate limiter: ensure at least 1.05s between calls (57/min)
    rate_lock = threading.Lock()
    last_call = [0.0]

    def rate_limited_check(symbol: str) -> dict | None:
        with rate_lock:
            now = time.time()
            elapsed = now - last_call[0]
            if elapsed < 1.05:
                time.sleep(1.05 - elapsed)
            last_call[0] = time.time()
        return check_symbol(symbol, None, cache)

    gaps = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(rate_limited_check, s): s for s in symbols}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result:
                gaps.append(result)
            if (i + 1) % 50 == 0:
                log.info(f"  Progress: {i + 1}/{len(symbols)} | gaps: {len(gaps)}")

    return gaps


def format_results(name: str, gaps: list[dict]) -> str:
    """Format gap results as a readable string."""
    if not gaps:
        return f"=== {name} - No gaps >= {GAP_THRESHOLD*100:.0f}% found ===\n"

    lines = [
        f"=== {name} - {len(gaps)} stock(s) with gaps >= {GAP_THRESHOLD*100:.0f}% ===",
        "",
    ]
    for g in sorted(gaps, key=lambda x: abs(x["gap_pct"]), reverse=True):
        arrow = "🔼" if g["direction"] == "UP" else "🔽"
        lines.append(
            f"  {arrow} {g['symbol']:10s} {g['gap_pct']:>8.2f}%  | "
            f"${g['prev_close']:>8.2f} -> ${g['current']:>8.2f}  ({g['direction']})"
        )
        # Show indicators if available
        if g.get("indicators"):
            ind = g["indicators"]
            lines.append(
                f"         EMA(9)={ind['ema9']:>8.2f}  SMA(20)={ind['sma20']:>8.2f}  SMA(200)={ind['sma200']:>8.2f}"
            )
            lines.append(
                f"         Price vs EMA(9): {'✅ Above' if ind['above_ema9'] else '❌ Below'} | "
                f"SMA(20): {'✅ Above' if ind['above_sma20'] else '❌ Below'} | "
                f"SMA(200): {'✅ Above' if ind['above_sma200'] else '❌ Below'}"
            )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    """Send a message to Telegram via Bot API."""
    if not bot_token or not chat_id:
        log.warning("Telegram credentials not set; printing to stdout only")
        print(message)
        return False

    import requests as req

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = req.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            log.info("✅ Telegram message sent")
            return True
        log.error(f"Telegram failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        log.error(f"Telegram delivery error: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 60)
    log.info("Stock Gap Scanner - Pre-Market Gaps")
    log.info("=" * 60)

    if not API_KEY:
        log.error("FINNHUB_API_KEY environment variable is not set.")
        log.error("Get a free key at https://finnhub.io/dashboard")
        sys.exit(1)

    # Determine which index to scan (parse args for flags vs index name)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0].lower() if args else "dow"
    log.info(f"Target: {target}")

    client = finnhub.Client(api_key=API_KEY)
    cache = load_cache()
    log.info(f"Loaded {len(cache)} cached quotes")

    # Check market status
    try:
        status = client.market_status(exchange="US")
        log.info(f"Market: isOpen={status.get('isOpen')}, session={status.get('session')}")
    except Exception as e:
        log.warning(f"Could not get market status: {e}")

    # Define scan plan based on target
    all_us_stocks = get_all_us_stocks(client) if target == "full" else []

    # For "full" mode: prioritize by gap likelihood
    # 1. Stocks NOT in major indices (smallest/micro-cap, most volatile)
    # 2. NASDAQ-100 (growth stocks, moderate volatility)
    # 3. S&P 500 (large-cap, less volatile)
    # 4. Dow Jones (blue-chip, least likely to gap 50%+)
    if target == "full" and all_us_stocks:
        major_indices = set(get_dow_jones() + get_sp500() + get_nasdaq_100())
        # Filter out symbols already in major indices
        other_stocks = [s for s in all_us_stocks if s not in major_indices]
        scan_plan = [
            ("Other US Stocks (not in indices)", other_stocks, True),  # parallel
            ("NASDAQ-100", get_nasdaq_100(), False),                   # sequential
            ("S&P 500", get_sp500(), False),
            ("Dow Jones", get_dow_jones(), False),
        ]
    else:
        scan_plan = {
            "dow": [("Dow Jones", get_dow_jones())],
            "sp500": [("S&P 500", get_sp500())],
            "nasdaq": [("NASDAQ-100", get_nasdaq_100())],
            "all": [
                ("Dow Jones", get_dow_jones()),
                ("S&P 500", get_sp500()),
                ("NASDAQ-100", get_nasdaq_100()),
            ],
            "full": [("US Market", all_us_stocks)],
        }

    if isinstance(scan_plan, dict) and target not in scan_plan:
        log.error(f"Unknown target: {target}. Use: dow, sp500, nasdaq, all, or full")
        sys.exit(1)

    all_results = {}
    enrich = "--indicators" in sys.argv or os.environ.get("ENRICH_WITH_INDICATORS", "").lower() in ("1", "true")
    save_results = "--save" in sys.argv
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Handle both dict (indices) and list (full priority scan)
    if isinstance(scan_plan, dict):
        plan_items = [(n, s, False) for n, s in scan_plan[target]]
    else:
        plan_items = scan_plan

    for name, symbols, parallel in plan_items:
        if not symbols:
            log.warning(f"No tickers found for {name}")
            symbols = []
        mode = "parallel" if parallel else "sequential"
        log.info(f"  Scanning {name} in {mode} mode ({len(symbols)} symbols)")
        gaps = scan_index(name, symbols, client, cache, parallel=parallel)
        if enrich and gaps:
            gaps = enrich_gaps(gaps)
        all_results[name] = gaps
        print(format_results(name, gaps))

        # Notify on gaps found (real-time update per group)
        if gaps and bot_token and chat_id:
            gap_lines = []
            for g in gaps:
                arrow = "🔼" if g["direction"] == "UP" else "🔽"
                gap_lines.append(
                    f"{arrow} {g['symbol']}: {g['gap_pct']:+.2f}% "
                    f"(${g['prev_close']} -> ${g['current']})"
                )
            notify_msg = f"🚨 **Gap Alert — {name}**\n" + "\n".join(gap_lines)
            send_telegram(notify_msg, bot_token, chat_id)
        elif gaps:
            log.info(f"  *** {len(gaps)} gaps found in {name}! ***")

    # Summary
    log.info(f"\n{'=' * 60}")
    log.info("SCAN COMPLETE - SUMMARY")
    log.info(f"{'=' * 60}")
    total = 0
    for name, gaps in all_results.items():
        log.info(f"  {name}: {len(gaps)} gaps >= {GAP_THRESHOLD*100:.0f}%")
        total += len(gaps)
    log.info(f"  TOTAL: {total} gaps")
    log.info(f"Cache: {len(cache)} quotes at {CACHE_FILE}")

    # Optional: deliver summary via Telegram
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if bot_token and chat_id:
        lines = [
            f"📊 **Gap Scan Complete - {datetime.now().strftime('%Y-%m-%d')}**",
            "",
        ]
        for name, gaps in all_results.items():
            if gaps:
                for g in gaps:
                    arrow = "🔼" if g["direction"] == "UP" else "🔽"
                    lines.append(
                        f"{arrow} {g['symbol']}: {g['gap_pct']:+.2f}% "
                        f"(${g['prev_close']} -> ${g['current']})"
                    )
                    if g.get("indicators"):
                        ind = g["indicators"]
                        lines.append(
                            f"  EMA9={ind['ema9']} SMA20={ind['sma20']} SMA200={ind['sma200']} | "
                            f"Price vs SMA200: {'📈 Above' if ind['above_sma200'] else '📉 Below'}"
                        )
            else:
                lines.append(f"- {name}: no gaps >= 50%")
        send_telegram("\n".join(lines), bot_token, chat_id)


if __name__ == "__main__":
    main()
