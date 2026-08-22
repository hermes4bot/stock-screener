#!/usr/bin/env python3
"""
Gap Screener Web Frontend
=========================
Serves the latest gap scan results as a website.
Each stock links to TradingView with EMA9 + SMA20 preloaded,
plus embedded D1 and M15 mini charts.

Usage:
  .venv/bin/python webapp.py [port]     # default 8080
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, render_template_string

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def latest_history_files() -> list[Path]:
    """Newest first: tv_gaps_*.json preferred, then gaps_*.json."""
    tv = sorted(HISTORY_DIR.glob("tv_gaps_*.json"), reverse=True)
    fh = sorted(HISTORY_DIR.glob("gaps_*.json"), reverse=True)
    return tv + fh


def load_latest() -> dict | None:
    for f in latest_history_files():
        try:
            data = json.loads(f.read_text())
            if data.get("total_gaps") is not None and (data.get("gaps") or data.get("groups")):
                data["_file"] = f.name
                return data
        except Exception:
            continue
    return None


def flatten(record: dict) -> list[dict]:
    """Normalize both history formats into a flat row list."""
    rows = record.get("gaps")
    if rows is not None:  # tv_gaps format
        return rows
    out = []
    for group, items in (record.get("groups") or {}).items():
        for g in items:
            g["group"] = group
            out.append(g)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tv_chart_url(row: dict, interval: str) -> str:
    """TradingView chart link with EMA9 + SMA20 studies preloaded.
    interval: 'D' or '15'
    """
    sym = row.get("symbol", "")
    exch = row.get("exchange", "NASDAQ")  # fallback; TV redirects anyway
    # Try OTC/NASDAQ/NYSE agnostic: pass plain symbol, TV picks exchange
    return (
        f"https://www.tradingview.com/chart/0ZTktGqI/"
        f"?symbol={quote(sym)}&interval={interval}"
        f"&studies=%5B%5B%22EMA%40tv-basicstudies%22%2C%7B%22length%22%3A9%7D%5D"
        f"%2C%5B%22SMA%40tv-basicstudies%22%2C%7B%22length%22%3A20%7D%5D%5D"
    )


def mini_chart_url(row: dict, interval: str, width=360, height=200) -> str:
    """TradingView mini-symbol chart widget image URL (static embed)."""
    sym = row.get("symbol", "")
    # TV mini chart embed via widget page
    return (
        f"https://s.tradingview.com/widgetembed/?symbol={quote(sym)}"
        f"&interval={interval}&hidesidetoolbar=1&symboledit=1&saveimage=0"
        f"&toolbarbg=rgba(19,23,34,1)&theme=dark&style=1"
        f"&studies=%5B%5B%22EMA%40tv-basicstudies%22%2C%7B%22length%22%3A9%7D%5D"
        f"%2C%5B%22SMA%40tv-basicstudies%22%2C%7B%22length%22%3A20%7D%5D%5D"
        f"&hideideas=1&withdateranges=0&details=0"
        f"&width={width}&height={height}"
    )


PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>US Pre-Market Gap Screener</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#131722; --panel:#1e222d; --text:#d1d4dc; --muted:#787b86;
          --up:#26a69a; --dn:#ef5350; --accent:#2962ff; }
  * { box-sizing:border-box }
  body { margin:0; font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
         background:var(--bg); color:var(--text); padding:24px }
  h1 { font-size:1.5rem; margin:0 0 4px }
  .meta { color:var(--muted); font-size:.85rem; margin-bottom:20px }
  table { border-collapse:collapse; width:100%; background:var(--panel);
          border-radius:8px; overflow:hidden }
  th,td { padding:10px 12px; text-align:left; font-size:.88rem;
          border-bottom:1px solid #2a2e39 }
  th { color:var(--muted); font-weight:600; text-transform:uppercase;
       font-size:.72rem; letter-spacing:.05em }
  tr:hover td { background:#252a36 }
  a { color:var(--accent); text-decoration:none; font-weight:600 }
  a:hover { text-decoration:underline }
  .up { color:var(--up) } .dn { color:var(--dn) }
  .tier { display:inline-block; padding:2px 8px; border-radius:10px;
          font-size:.75rem; font-weight:700 }
  .t50 { background:#3d1f24; color:var(--dn) }
  .t20 { background:#3d331f; color:#ff9800 }
  .t10 { background:#1f2c3d; color:#42a5f5 }
  details { margin-top:6px }
  summary { cursor:pointer; color:var(--accent); font-size:.8rem }
  .charts { display:flex; gap:12px; flex-wrap:wrap; padding:8px 0 }
  iframe { border:1px solid #2a2e39; border-radius:6px }
</style>
</head>
<body>
<h1>🇺🇸 US Pre-Market Gap Screener</h1>
<div class="meta">
  {{ meta }} · {{ rows|length }} stocks ·
  <a href="/">refresh</a>
</div>

<table>
<tr>
  <th>Ticker</th><th>Name</th><th>Tier</th><th>Gap %</th>
  <th>PM Price</th><th>Prev Close</th><th>PM Volume</th><th>Mkt Cap</th><th>Charts</th>
</tr>
{% for r in rows %}
<tr>
  <td><a href="{{ r.tv_d }}" target="_blank" title="Open in TradingView (EMA9+SMA20)"><b>{{ r.symbol }}</b></a></td>
  <td>{{ r.description or '' }}</td>
  <td><span class="tier t{{ r.tier_num }}">{{ r.tier }}</span></td>
  <td class="{{ 'up' if r.gap_pct > 0 else 'dn' }}"><b>{{ '%+.2f'|format(r.gap_pct) }}%</b></td>
  <td>{{ r.pre_price or '-' }}</td>
  <td>{{ r.prev_close or '-' }}</td>
  <td>{{ r.pm_vol }}</td>
  <td>{{ r.mcap }}</td>
  <td>
    <a href="{{ r.tv_d }}" target="_blank">D1</a> ·
    <a href="{{ r.tv_15 }}" target="_blank">M15</a>
    <details>
      <summary>charts</summary>
      <div class="charts">
        <iframe src="{{ r.mini_d }}" width="380" height="210"></iframe>
        <iframe src="{{ r.mini_15 }}" width="380" height="210"></iframe>
      </div>
    </details>
  </td>
</tr>
{% endfor %}
</table>

<p class="meta">
  Chart links open TradingView with <b>EMA(9)</b> + <b>SMA(20)</b> activated.<br>
  Sources: TradingView scanner · history files in <code>data/history/</code>
</p>
</body>
</html>
"""


@app.route("/")
def index():
    record = load_latest()
    if not record:
        abort(503, "No scan history yet. Run: .venv/bin/python tv_gaps.py 10 --save")

    rows = flatten(record)
    enriched = []
    for r in rows:
        tier = r.get("tier", "10%+")
        r = dict(r)
        r["tier"] = tier
        r["tier_num"] = tier.replace("%+", "")
        r["prev_close"] = r.get("close") or r.get("prev_close")
        r["pre_price"] = r.get("premarket_price")
        r["pm_vol"] = fmt_vol(r.get("premarket_volume"))
        r["mcap"] = fmt_mcap(r.get("market_cap"))
        r["gap_pct"] = r.get("gap_pct", 0)
        r["tv_d"] = tv_chart_url(r, "D")
        r["tv_15"] = tv_chart_url(r, "15")
        r["mini_d"] = mini_chart_url(r, "D")
        r["mini_15"] = mini_chart_url(r, "15")
        enriched.append(r)

    # Sort: tier desc, then |gap|
    enriched.sort(key=lambda x: (int(x["tier_num"]), abs(x["gap_pct"])), reverse=True)

    scanned = record.get("scanned_at", "?")
    src = record.get("source", "finnhub")
    meta = f"Scanned {scanned} UTC · source: {src}"
    return render_template_string(PAGE, rows=enriched, meta=meta)


def fmt_vol(v):
    if not v:
        return "-"
    for div, suf in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if v >= div:
            return f"{v/div:.1f}{suf}"
    return str(v)


def fmt_mcap(v):
    if not v:
        return "-"
    for div, suf in [(1e9, "B"), (1e6, "M")]:
        if v >= div:
            return f"{v/div:.1f}{suf}"
    return str(v)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"Serving on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
