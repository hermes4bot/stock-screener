#!/usr/bin/env python3
"""
Gap Screener Web Frontend
=========================
Shows the latest gap scan results with BIG always-visible charts (D1/M15/M1).
Batch buttons open TradingView tabs in steps of 10 stocks x 3 timeframes.
Clicking a ticker opens all 3 timeframes for that stock.

Usage:
  .venv/bin/python webapp.py [port]     # default 8080
"""

import json
import sys
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, render_template_string, jsonify

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"

app = Flask(__name__)

TV_CHART_BASE = "https://www.tradingview.com/chart/0ZTktGqI/"
STUDIES = (
    "%5B%5B%22EMA%40tv-basicstudies%22%2C%7B%22length%22%3A9%7D%5D"
    "%2C%5B%22SMA%40tv-basicstudies%22%2C%7B%22length%22%3A20%7D%5D%5D"
)
INTERVALS = [("D", "D1"), ("15", "M15"), ("1", "M1")]
# Visible history per interval: interval -> lookback in days
LOOKBACK_DAYS = {"D": 90, "15": 10, "1": 2}


def _from_ts(interval: str) -> int:
    import time
    return int(time.time()) - LOOKBACK_DAYS.get(interval, 90) * 86400


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def latest_history_file() -> Path | None:
    tv = sorted(HISTORY_DIR.glob("tv_gaps_*.json"), reverse=True)
    fh = sorted(HISTORY_DIR.glob("gaps_*.json"), reverse=True)
    return (tv + fh)[0] if (tv + fh) else None


def load_latest() -> dict | None:
    f = latest_history_file()
    if not f:
        return None
    try:
        data = json.loads(f.read_text())
        data["_file"] = f.name
        return data
    except Exception:
        return None


def flatten(record: dict) -> list[dict]:
    rows = record.get("gaps")
    if rows is not None:
        return rows
    out = []
    for group, items in (record.get("groups") or {}).items():
        for g in items:
            g["group"] = group
            out.append(g)
    return out


def chart_url(symbol: str, interval: str) -> str:
    return (
        f"{TV_CHART_BASE}?symbol={quote(symbol)}&interval={interval}&studies={STUDIES}"
        f"&from={_from_ts(interval)}"
    )


def widget_url(symbol: str, interval: str, w=640, h=360) -> str:
    return (
        f"https://s.tradingview.com/widgetembed/?symbol={quote(symbol)}"
        f"&interval={interval}&hidesidetoolbar=1&saveimage=0&theme=dark&style=1"
        f"&studies={STUDIES}&hideideas=1&withdateranges=0&timezone=Etc/UTC"
        f"&from={_from_ts(interval)}&to={int(__import__('time').time()) + 3600}"
        f"&width={w}&height={h}"
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>US Pre-Market Gap Screener</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#131722; --panel:#1e222d; --text:#d1d4dc; --muted:#787b86;
          --up:#26a69a; --dn:#ef5350; --accent:#2962ff;
          --btn:#2962ff; --btn-hover:#1e53e5; }
  * { box-sizing:border-box }
  body { margin:0; font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
         background:var(--bg); color:var(--text); padding:20px }
  h1 { font-size:1.4rem; margin:0 0 4px }
  .meta { color:var(--muted); font-size:.85rem; margin-bottom:14px }

  .batch { position:sticky; top:0; z-index:10; background:var(--panel);
           border:1px solid #2a2e39; border-radius:8px; padding:10px 14px;
           margin-bottom:16px; display:flex; gap:10px; flex-wrap:wrap;
           align-items:center }
  .batch button { background:var(--btn); color:#fff; border:none;
                  padding:9px 18px; border-radius:6px; font-weight:700;
                  font-size:.88rem; cursor:pointer }
  .batch button:hover { background:var(--btn-hover) }
  .batch button:disabled { background:#3a3f4b; cursor:not-allowed }
  .batch .info { color:var(--muted); font-size:.82rem }

  .stock { background:var(--panel); border:1px solid #2a2e39;
           border-radius:10px; margin-bottom:22px; overflow:hidden }
  .head { display:flex; align-items:center; gap:14px; flex-wrap:wrap;
          padding:12px 16px; border-bottom:1px solid #2a2e39 }
  .sym a { font-size:1.15rem; font-weight:800; letter-spacing:.03em }
  .name { color:var(--muted); font-size:.85rem; flex:1 }
  .tier { padding:2px 10px; border-radius:10px; font-size:.75rem; font-weight:700 }
  .t50 { background:#3d1f24; color:var(--dn) }
  .t20 { background:#3d331f; color:#ff9800 }
  .t10 { background:#1f2c3d; color:#42a5f5 }
  .gap { font-size:1.05rem; font-weight:800 }
  .up { color:var(--up) } .dn { color:var(--dn) }
  .stat { color:var(--muted); font-size:.83rem }
  .tf-links a { margin-left:8px; font-size:.82rem }
  .openall { background:#2a2e39; color:var(--text); border:none;
             padding:6px 12px; border-radius:6px; cursor:pointer;
             font-size:.8rem; font-weight:600 }
  .openall:hover { background:#363c4a }

  .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(430px,1fr));
            gap:10px; padding:12px }
  iframe { width:100%; height:380px; border:1px solid #2a2e39; border-radius:6px;
           background:#131722 }
</style>
</head>
<body>
<h1>🇺🇸 US Pre-Market Gap Screener</h1>
<div class="meta">{{ meta }} · {{ rows|length }} stocks · <a href="/">refresh</a></div>

{% for r in rows %}
{% if loop.index0 % 10 == 0 %}
{% set group_end = [loop.index0 + 9, rows|length - 1]|min %}
<div class="batch">
  <button class="groupBtn" onclick="openGroup({{ loop.index0 }}, {{ group_end }})">▶
    Open stocks {{ loop.index0 + 1 }}–{{ group_end + 1 }} (D1+M15+M1)</button>
  <span class="info">{{ group_end - loop.index0 + 1 }} stocks · {{ (group_end - loop.index0 + 1) * 3 }} tabs — allow pop-ups for this site!</span>
</div>
{% endif %}
<div class="stock" data-symbol="{{ r.symbol }}">
  <div class="head">
    <span class="sym"><a href="{{ r.tv_d }}" target="_blank"
        onclick="openAll('{{ r.symbol }}'); return false;"
        title="Open D1+M15+M1 in TradingView">{{ r.symbol }}</a></span>
    <span class="name">{{ r.description or '' }}</span>
    <span class="tier t{{ r.tier_num }}">{{ r.tier }}</span>
    <span class="gap {{ 'up' if r.gap_pct > 0 else 'dn' }}">{{ '%+.2f'|format(r.gap_pct) }}%</span>
    <span class="stat">PM {{ r.pre_price or '-' }} · prev {{ r.prev_close or '-' }}
      · vol {{ r.pm_vol }} · mcap {{ r.mcap }}</span>
    <span class="tf-links">
      <a href="{{ r.tv_d }}" target="_blank">D1</a>
      <a href="{{ r.tv_15 }}" target="_blank">M15</a>
      <a href="{{ r.tv_1 }}" target="_blank">M1</a>
    </span>
    <button class="openall" onclick="openAll('{{ r.symbol }}')">open 3× TF</button>
  </div>

  <div class="charts">
    <iframe loading="lazy" src="{{ r.mini_d }}"></iframe>
    <iframe loading="lazy" src="{{ r.mini_15 }}"></iframe>
    <iframe loading="lazy" src="{{ r.mini_1 }}"></iframe>
  </div>
</div>
{% endfor %}

<script>
// ---- Group openers: each group of 10 stocks has its own button -----------
const allSymbols = JSON.parse('{{ symbols_json|safe }}');

function tfUrls(sym) {
  const base = "https://www.tradingview.com/chart/0ZTktGqI/";
  const studies = "{{ studies|safe }}";
  const now = Math.floor(Date.now() / 1000);
  const day = 86400;
  // interval -> lookback days: D1 = 90d, M15 = 10d, M1 = 2d
  return [["D", 90], ["15", 10], ["1", 2]].map(([iv, lookback]) =>
      base + "?symbol=" + encodeURIComponent(sym) + "&interval=" + iv
      + "&studies=" + studies + "&from=" + (now - lookback * day));
}

// Single stock: open D1+M15+M1 synchronously inside the click gesture.
function openAll(sym) {
  for (const u of tfUrls(sym)) window.open(u, "_blank");
}

// Group opener: called directly from the group button click -> same gesture.
// All window.open calls happen synchronously; browsers that cap the number
// of tabs will ask the user once ("allow multiple pop-ups").
function openGroup(startIdx, endIdx) {
  let opened = 0;
  for (let i = startIdx; i <= endIdx && i < allSymbols.length; i++) {
    for (const u of tfUrls(allSymbols[i])) {
      window.open(u, "_blank");
      opened++;
    }
  }
  // Feedback without replacing the button (so it can be clicked again)
  const btn = event.currentTarget || window.event?.target;
  if (btn) {
    const info = btn.parentElement.querySelector('.info');
    if (info) info.textContent = `Opened ${opened} tabs (stocks ${startIdx + 1}–${endIdx + 1}). Blocked? Allow pop-ups & retry.`;
  }
}
</script>
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
        sym = r["symbol"]
        r["tv_d"] = chart_url(sym, "D")
        r["tv_15"] = chart_url(sym, "15")
        r["tv_1"] = chart_url(sym, "1")
        r["mini_d"] = widget_url(sym, "D")
        r["mini_15"] = widget_url(sym, "15")
        r["mini_1"] = widget_url(sym, "1")
        enriched.append(r)

    enriched.sort(key=lambda x: (int(x["tier_num"]), abs(x["gap_pct"])), reverse=True)

    scanned = record.get("scanned_at", "?")
    src = record.get("source", "finnhub")
    meta = f"Scanned {scanned} UTC · source: {src}"

    return render_template_string(
        PAGE,
        rows=enriched,
        meta=meta,
        symbols_json=json.dumps([r["symbol"] for r in enriched]),
        studies=STUDIES,
    )


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
