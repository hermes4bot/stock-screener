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
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, abort, render_template_string, jsonify, send_file
from jinja2 import Environment, BaseLoader, select_autoescape

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
NEWS_CACHE_DIR = DATA_DIR / "news_cache"

app = Flask(__name__)

TV_CHART_BASE = "https://www.tradingview.com/chart/"
# Chart-page links: studies as [{"name": ..., "id": ..., "inputs": {...}}, ...]
# This is TradingView's own chart-URL serialization (captured from the chart
# page itself). The old layout-scoped base (/chart/<id>/) is gone: that saved
# layout was deleted and every link returned "Can't open this chart layout".
STUDY_DEFS = (
    ("MAExp@tv-basicstudies", 9),     # EMA(9)
    ("MASimple@tv-basicstudies", 20),  # SMA(20)
)


def _studies_qs() -> str:
    payload = [
        {"name": sid, "id": sid, "inputs": {"length": length}}
        for sid, length in STUDY_DEFS
    ]
    return quote(json.dumps(payload, separators=(",", ":")))


STUDIES = _studies_qs()
# Widget embeds: studies as [{"id": name, "inputs": {...}}, ...]
# Correct IDs: MAExp (exponential MA) / MASimple (simple MA)
WIDGET_STUDIES = "%5B%7B%22id%22%3A%22MAExp%40tv-basicstudies%22%2C%22inputs%22%3A%7B%22length%22%3A9%7D%7D%2C%7B%22id%22%3A%22MASimple%40tv-basicstudies%22%2C%22inputs%22%3A%7B%22length%22%3A20%7D%7D%5D"
INTERVALS = [("D", "D1"), ("15", "M15"), ("1", "M1")]
# Visible history per interval: interval -> lookback in days
LOOKBACK_DAYS = {"D": 90, "15": 10, "1": 2}


def _from_ts(interval: str) -> int:
    import time
    return int(time.time()) - LOOKBACK_DAYS.get(interval, 90) * 86400


# ---------------------------------------------------------------------------
# Per-symbol news summary
# ---------------------------------------------------------------------------

YAHOO_RSS = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
             "?s={sym}&region=US&lang=en-US")
GNEWS_RSS = ("https://news.google.com/rss/search"
             "?q={sym}+stock&hl=en-US&gl=US&ceid=US:en")
NEWS_TTL = 900  # seconds a fetched feed is reused
NEWS_MAX_ITEMS = 12
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _strip_html(text) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def _parse_rss(raw: bytes) -> list[dict]:
    items: list[dict] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return items
    for node in root.iter():
        if node.tag.split("}")[-1] != "item":
            continue
        fields = {}
        for child in node:
            fields[child.tag.split("}")[-1]] = (child.text or "").strip()
        title = _strip_html(fields.get("title"))
        if not title:
            continue
        items.append({
            "title": title,
            "link": fields.get("link", ""),
            "description": _strip_html(fields.get("description")),
            "published": fields.get("pubDate", ""),
        })
    return items


def _rel_time(published: str) -> str:
    if not published:
        return ""
    try:
        dt = parsedate_to_datetime(published)
    except (TypeError, ValueError):
        return published
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    minutes = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    if days < 30:
        return f"{days} d ago"
    return dt.strftime("%Y-%m-%d")


def _fetch_live_news(symbol: str) -> tuple[list[dict], str]:
    """Try the finance feed first, then the general news feed."""
    sym = quote(symbol.upper())
    for source, url in (("Yahoo Finance", YAHOO_RSS.format(sym=sym)),
                        ("Google News", GNEWS_RSS.format(sym=sym))):
        try:
            resp = requests.get(url, timeout=15,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            items = _parse_rss(resp.content)
        except (requests.RequestException, ET.ParseError):
            continue
        if items:
            return items[:NEWS_MAX_ITEMS], source
    return [], ""


def fetch_news(symbol: str) -> tuple[list[dict], str, str]:
    """Return (items, source, fetched_at); disk-cached for NEWS_TTL."""
    cache_file = NEWS_CACHE_DIR / f"{symbol.upper()}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < NEWS_TTL:
        try:
            cached = json.loads(cache_file.read_text())
            return (cached.get("items", []), cached.get("source", ""),
                    cached.get("fetched", ""))
        except (json.JSONDecodeError, OSError):
            pass
    items, source = _fetch_live_news(symbol)
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if items:
        try:
            NEWS_CACHE_DIR.mkdir(exist_ok=True)
            cache_file.write_text(json.dumps({
                "symbol": symbol.upper(), "fetched": fetched,
                "source": source, "items": items,
            }))
        except OSError:
            pass
    return items, source, fetched


def _hermes_env_key(name: str) -> str:
    """Read a secret from the Hermes .env; never hardcoded, never logged."""
    value = os.environ.get(name, "")
    if value:
        return value
    env_file = HERMES_HOME / ".env"
    if not env_file.exists():
        return ""
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _ai_summary(symbol: str, name: str, items: list[dict]) -> str:
    """Short LLM digest of the headlines. Empty string when unavailable."""
    if os.environ.get("NEWS_LLM", "1").strip().lower() in ("0", "false", "no", "off"):
        return ""
    key = _hermes_env_key("OPENROUTER_API_KEY")
    if not key or not items:
        return ""
    model = os.environ.get("NEWS_LLM_MODEL", "openrouter/free")
    lines = []
    for it in items[:6]:
        lede = (it.get("description") or "").strip()
        lines.append(f"- {it['title']}" + (f": {lede[:250]}" if lede else ""))
    prompt = (
        f"You are a market-news editor. Summarize the recent news for the US "
        f"stock {symbol}" + (f" ({name})" if name else "") +
        " in at most 4 plain sentences for a trader. Facts only, no advice, "
        "no hedging.\n\n" + "\n".join(lines)
    )
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 1500},
            timeout=30,
        )
        resp.raise_for_status()
        message = (resp.json().get("choices") or [{}])[0].get("message") or {}
        text = message.get("content")
        # Free models are routed dynamically; some answer with reasoning only
        # and return content=null. Treat that as "no AI summary".
        if not text or not str(text).strip() or text.strip().lower() == "none":
            return ""
        return str(text).strip()
    except (requests.RequestException, ValueError, KeyError, IndexError,
            AttributeError, TypeError):
        return ""


def _ai_summary_cached(symbol: str, name: str, items: list[dict]) -> tuple[str, str]:
    """AI digest, cached next to the feed so repeat clicks are instant."""
    cache_file = NEWS_CACHE_DIR / f"{symbol.upper()}.ai.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < NEWS_TTL:
        try:
            cached = json.loads(cache_file.read_text())
            if cached.get("summary"):
                return cached["summary"], cached.get("model", "")
        except (json.JSONDecodeError, OSError):
            pass
    summary = _ai_summary(symbol, name, items)
    model = os.environ.get("NEWS_LLM_MODEL", "openrouter/free")
    if summary:
        try:
            NEWS_CACHE_DIR.mkdir(exist_ok=True)
            cache_file.write_text(json.dumps({"summary": summary, "model": model}))
        except OSError:
            pass
    return summary, model


def _fallback_summary(items: list[dict]) -> str:
    """Deterministic digest from the items themselves (used if no LLM)."""
    parts = []
    for it in items[:3]:
        lede = (it.get("description") or "").strip()
        text = lede if lede else it.get("title", "")
        if len(text) > 220:
            text = text[:217].rstrip() + "..."
        if text:
            parts.append(text)
    return " ".join(parts)


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
    # Kept for reference; embedded charts now use the official
    # TradingView.widget API (see WIDGET_TEMPLATE) so studies render.
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

  .charts { display:grid; grid-template-columns:2fr 1fr; gap:10px; padding:12px }
  .charts > div, .m1box > div { height:420px; border:1px solid #2a2e39;
                                border-radius:6px; background:#131722 }
  .charts iframe, .m1box iframe { border:none; border-radius:6px }
  .m1wrap { padding:0 12px 12px }
  .m1btn { background:#2a2e39; color:var(--text); border:none;
           padding:8px 16px; border-radius:6px; cursor:pointer;
           font-size:.85rem; font-weight:600 }
  .m1btn:hover { background:#363c4a }
  .m1box iframe { width:100%; height:460px; margin-top:10px;
                  border:1px solid #2a2e39; border-radius:6px; background:#131722 }
  .popupHelp { background:#3d331f; border:1px solid #ff9800; color:#ffd699;
               border-radius:8px; padding:12px 16px; margin-bottom:16px;
               font-size:.88rem }
  .popupHelp button { float:right; background:none; border:none;
                      color:#ffd699; font-size:1rem; cursor:pointer }
  .favbtn { background:none; border:none; color:#787b86; font-size:1.25rem;
            cursor:pointer; padding:0 2px; line-height:1 }
  .favbtn:hover { color:#fdd835 }
  .favbtn.fav-on { color:#fdd835 }
  a.fav-active { color:#fdd835 !important }
  .batchHint { text-align:center; color:var(--muted); font-size:.75rem;
               margin:-10px 0 14px }
</style>
</head>
<body>
<h1>🇺🇸 US Pre-Market Gap Screener{% if static_snapshot %} <span style="color:#787b86;font-size:.8rem">(offline snapshot)</span>{% endif %}</h1>
<div class="meta">
  {{ meta }} · {{ rows|length }} stocks ·
  {% if not static_snapshot %}<a href="/">refresh</a> ·
  <a href="/gaps.zip" title="Latest scan as ZIP-wrapped CSV">⬇ gaps.zip</a> ·
  <a href="#" id="favToggle" data-on="0"
     onclick="const t=this;t.dataset.on=t.dataset.on==='1'?'0':'1';applyFavFilter();return false;">★ Favorites only</a>
  {% else %}open file locally · chart links open TradingView with EMA9+SMA20{% endif %}
</div>

{% if not static_snapshot %}
<div class="popupHelp" id="popupHelp" style="display:none">
  ⚠ <b><span id="blockedCount">0</span> tabs were blocked</b> by your browser.
  Click the pop-up blocker icon in the address bar →
  <b>“Always allow pop-ups from 10.53.164.194”</b> (Chrome: also tick
  “allow multiple pop-ups”) → Done, then click again.
</div>
{% endif %}

{% for r in rows %}
<div class="stock" data-symbol="{{ r.symbol }}">
  <div class="head">
    {% if not static_snapshot %}<button class="favbtn" id="fav-{{ r.symbol }}" onclick="toggleFav('{{ r.symbol }}', this)"
            title="Add to favorites">☆</button>{% endif %}
    <span class="sym"><a href="{{ r.tv_d }}"{% if not static_snapshot %} onclick="openAll('{{ r.symbol }}'); return false;"{% endif %}
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
      <a href="{{ r.news_url if not static_snapshot else r.news_ext }}" target="_blank"
         title="News summary for {{ r.symbol }}">📰 News</a>
    </span>
    <button class="openall" onclick="openAll('{{ r.symbol }}')">open 3× TF + 📰</button>
  </div>

  {% if static_snapshot %}
  <div class="charts" style="grid-template-columns:1fr;gap:4px">
    <span class="tf-links" style="padding:6px 0">
      📈 <a href="{{ r.tv_d }}" target="_blank">D1 chart</a> ·
      <a href="{{ r.tv_15 }}" target="_blank">M15 chart</a> ·
      <a href="{{ r.tv_1 }}" target="_blank">M1 chart</a>
    </span>
  </div>
  {% else %}
  <div style="padding:12px">
  <div class="d15wrap">
    <button class="m1btn" onclick="toggleD15(this, '{{ r.symbol }}')">▲ Hide D1 + M15 charts</button>
    <div class="d15box">
    <div class="charts">
      <div class="chart-d1" id="chart-{{ r.symbol }}-D"></div>
      <div class="chart-m15" id="chart-{{ r.symbol }}-15"></div>
    </div>
    </div>
  </div>
  <div class="m1wrap">
    <button class="m1btn" onclick="toggleM1(this, '{{ r.symbol }}')">▼ Show M1 chart (full width)</button>
    <div class="m1box" style="display:none">
      <div id="chart-{{ r.symbol }}-1"></div>
    </div>
  </div>
  </div>
  {% endif %}
</div>
{% endfor %}

{% if not static_snapshot %}
<script>
// ---- Group openers: each group of 10 stocks has its own button -----------
const allSymbols = JSON.parse('{{ symbols_json|safe }}');
const newsUrls = JSON.parse('{{ news_urls_json|safe }}');

function tfUrls(sym) {
  const base = "https://www.tradingview.com/chart/";
  const studies = "{{ studies|safe }}";
  const now = Math.floor(Date.now() / 1000);
  const day = 86400;
  // interval -> lookback days: D1 = 90d, M15 = 10d, M1 = 2d
  return [["D", 90], ["15", 10], ["1", 2]].map(([iv, lookback]) =>
      base + "?symbol=" + encodeURIComponent(sym) + "&interval=" + iv
      + "&studies=" + studies + "&from=" + (now - lookback * day));
}

// Single stock: open D1+M15+M1 synchronously inside the click gesture,
// plus the news summary tab.
function openAll(sym) {
  let opened = 0, wanted = 0;
  for (const u of tfUrls(sym)) {
    wanted++;
    const w = window.open(u, "_blank");
    if (w) opened++;
  }
  const news = newsUrls[sym];
  if (news) {
    wanted++;
    const w = window.open(news, "_blank");
    if (w) opened++;
  }
  if (opened < wanted) showBlockerHelp(wanted - opened);
}

// Favorites batch openers: operate on favorite stocks in list order.
// The bar is only visible in Favorites view.
function favSymbols() {
  const favs = getFavs();
  return allSymbols.filter(s => favs.includes(s));
}

let favBatchIndex = 0;

function openFavBatch(btn) {
  const syms = favSymbols();
  const start = favBatchIndex;
  if (start >= syms.length) {
    btn.parentElement.querySelector('.info').textContent = '✅ All favorites already opened. Re-enter Favorites view to reset.';
    return;
  }
  const chunk = syms.slice(start, start + 10);
  let opened = 0;
  for (const s of chunk) for (const u of tfUrls(s)) {
    if (window.open(u, "_blank")) opened++;
  }
  favBatchIndex = start + chunk.length;
  const info = btn.parentElement.querySelector('.info');
  const total = opened === chunk.length * 3 ? '✅' : '⚠';
  info.textContent = `${total} Opened ${opened} tabs (favorites ${start + 1}–${favBatchIndex} of ${syms.length}).`;
  info.style.color = opened === chunk.length * 3 ? '#26a69a' : '#ef5350';
}

function openAllFavs(btn) {
  const syms = favSymbols();
  let opened = 0, wanted = syms.length * 3;
  for (const s of syms) for (const u of tfUrls(s)) {
    if (window.open(u, "_blank")) opened++;
  }
  favBatchIndex = syms.length;
  const info = btn.parentElement.querySelector('.info');
  info.textContent = opened === wanted
    ? `✅ Opened all ${wanted} tabs (${syms.length} favorites).`
    : `⚠ Only ${opened} of ${wanted} tabs opened.`;
  info.style.color = opened === wanted ? '#26a69a' : '#ef5350';
}

function showBlockerHelp(blocked) {
  const bar = document.getElementById('popupHelp');
  document.getElementById('blockedCount').textContent = blocked;
  bar.style.display = 'block';
}

// ---- Embedded charts via official TradingView widget API -----------------
// Studies with inputs render reliably only through TradingView.widget.
const LOOKBACK = { D: 90, "15": 10, "1": 2 };

function tvWidget(symbol, interval, containerId) {
  new TradingView.widget({
    container_id: containerId,
    symbol: symbol,   // plain ticker - TV resolves the exchange automatically
    interval: interval,
    timezone: "Etc/UTC",
    theme: "dark",
    style: "1",
    autosize: true,
    hide_side_toolbar: true,
    allow_symbol_change: false,
    save_image: false,
    // EMA(9) orange + SMA(20) blue.
    // Per TV docs: overrides use the indicator DISPLAY name ("moving average"),
    // indexed _1/_2 for the second instance. Lengths come via inputs.
    studies: [
      { id: "MAExp@tv-basicstudies", inputs: { length: 9 } },
      { id: "MASimple@tv-basicstudies", inputs: { length: 20 } },
    ],
    studies_overrides: {
      // Override keys use each study's DISPLAY name, not the instance index:
      //   MAExp  -> "moving average exponential"
      //   MASimple -> "moving average"
      "moving average exponential.ma.color": "#ff9800",
      "moving average exponential.ma.linewidth": 2,
      "moving average.ma.color": "#2962ff",
      "moving average.ma.linewidth": 2,
    },
    time_frames: [],
    from: Math.floor(Date.now() / 1000) - (LOOKBACK[interval] || 90) * 86400,
  });
}

// Build all visible charts (D1 + M15). M1 is built lazily.
function initCharts() {
  document.querySelectorAll('.chart-d1, .chart-m15').forEach(el => {
    const sym = el.id.split('-')[1];          // chart-<SYM>-<IV>
    const iv = el.id.split('-')[2] === 'D' ? 'D' : el.id.split('-')[2];
    if (!el.dataset.built) { tvWidget(sym, iv, el.id); el.dataset.built = '1'; }
  });
}

const m1Built = {};

// M1 chart: lazy-load on first expand, then toggle visibility.
function toggleM1(btn, sym) {
  const box = btn.parentElement.querySelector('.m1box');
  const holder = box.querySelector('div[id^="chart-"]');
  if (box.style.display === 'none') {
    if (!m1Built[sym]) { tvWidget(sym, '1', holder.id); m1Built[sym] = true; }
    box.style.display = 'block';
    btn.textContent = '▲ Hide M1 chart';
  } else {
    box.style.display = 'none';
    btn.textContent = '▼ Show M1 chart (full width)';
  }
}

// D1 + M15 charts: visible by default, collapsible on request (same toggle
// pattern as M1, inverted default). Charts are already built, so this only
// flips visibility; the widgets re-fit via autosize.
function toggleD15(btn, sym) {
  const box = btn.parentElement.querySelector('.d15box');
  const show = box.style.display === 'none';
  box.style.display = show ? 'block' : 'none';
  btn.textContent = show ? '▲ Hide D1 + M15 charts' : '▼ Show D1 + M15 charts';
}
</script>
<script>
// ---- Favorites (persisted in localStorage) -------------------------------
// Defined early so inline onclick handlers can call it.
function getFavs() {
  try { return JSON.parse(localStorage.getItem('gapFavs') || '[]'); } catch { return []; }
}
function saveFavs(f) { localStorage.setItem('gapFavs', JSON.stringify(f)); }

function toggleFav(sym, btn) {
  let f = getFavs();
  if (f.includes(sym)) { f = f.filter(s => s !== sym); } else { f.push(sym); }
  saveFavs(f);
  btn.textContent = f.includes(sym) ? '★' : '☆';
  btn.classList.toggle('fav-on', f.includes(sym));
  applyFavFilter();
}

function applyFavFilter() {
  const t = document.getElementById('favToggle');
  const only = t.dataset.on === '1';
  const favs = getFavs();
  document.querySelectorAll('.stock').forEach(el => {
    const sym = el.dataset.symbol;
    el.style.display = (!only || favs.includes(sym)) ? '' : 'none';
  });
  // Single favorites batch bar: only visible in Favorites view
  const bar = document.getElementById('favBatch');
  if (bar) {
    bar.style.display = only ? '' : 'none';
    if (only) favBatchIndex = 0;   // reset progress on re-entering Favorites
  }
  t.textContent = only ? `★ Favorites (${favs.length}) — showing` : `★ Favorites only`;
  t.classList.toggle('fav-active', only);
}
</script>
<script src="https://s3.tradingview.com/tv.js" onload="window.initCharts && window.initCharts()"></script>
<script>
// Mark saved favorites on page load
window.addEventListener('DOMContentLoaded', () => {
  const favs = getFavs();
  favs.forEach(sym => {
    const b = document.getElementById('fav-' + sym);
    if (b) { b.textContent = '★'; b.classList.add('fav-on'); }
  });
});
window.addEventListener('load', () => window.initCharts && window.initCharts());
</script>
{% endif %}
</body>
</html>
"""


NEWS_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ symbol }} news{% if name %} — {{ name }}{% endif %} · Gap Screener</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#131722; --panel:#1e222d; --text:#d1d4dc; --muted:#787b86;
          --accent:#2962ff; --up:#26a69a; }
  * { box-sizing:border-box }
  body { margin:0; font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
         background:var(--bg); color:var(--text); padding:20px;
         max-width:1000px }
  h1 { font-size:1.4rem; margin:0 0 4px }
  h1 .name { color:var(--muted); font-weight:500; font-size:1rem; margin-left:8px }
  .meta { color:var(--muted); font-size:.85rem; margin-bottom:14px }
  .back { margin-bottom:14px; font-size:.85rem }
  .back a { color:var(--accent); text-decoration:none }
  .summary { background:var(--panel); border:1px solid #2a2e39;
             border-radius:10px; padding:14px 18px; margin-bottom:18px }
  .summary .label { color:var(--up); font-size:.75rem; font-weight:700;
                    letter-spacing:.08em; text-transform:uppercase;
                    margin-bottom:6px }
  .summary p { margin:0; line-height:1.55; font-size:.95rem }
  .summary .tag { color:var(--muted); font-size:.72rem; margin-top:8px }
  h2 { font-size:1rem; color:var(--muted); margin:0 0 10px;
       text-transform:uppercase; letter-spacing:.06em }
  .item { background:var(--panel); border:1px solid #2a2e39;
          border-radius:10px; padding:12px 16px; margin-bottom:10px }
  .item a.t { color:var(--text); font-weight:700; font-size:.95rem;
              text-decoration:none; line-height:1.35 }
  .item a.t:hover { color:var(--accent) }
  .item .src { color:var(--muted); font-size:.78rem; margin:4px 0 6px }
  .item .lede { color:#a9adb8; font-size:.87rem; line-height:1.5 }
  .empty { color:var(--muted); background:var(--panel); border:1px solid #2a2e39;
           border-radius:10px; padding:24px; text-align:center }
  .refresh { float:right; background:#2a2e39; color:var(--text); border:none;
             padding:7px 14px; border-radius:6px; cursor:pointer;
             font-size:.8rem; font-weight:600 }
  .refresh:hover { background:#363c4a }
</style>
</head>
<body>
<h1>📰 {{ symbol }}<span class="name">{{ name or '' }}</span></h1>
<div class="meta">
  {{ meta }} · {{ items|length }} stor{{ 'y' if items|length == 1 else 'ies' }}
  {% if not static_snapshot %}<button class="refresh" onclick="location.reload()">↻ refresh</button>{% endif %}
</div>

{% if summary %}
<div class="summary">
  <div class="label">Summary</div>
  <p>{{ summary }}</p>
  {% if summary_kind == 'ai' %}
  <div class="tag">AI-generated digest · model {{ summary_model }}</div>
  {% else %}
  <div class="tag">Compiled from the latest headlines (no AI provider configured)</div>
  {% endif %}
</div>
{% endif %}

{% if items %}
<h2>Latest stories</h2>
{% for it in items %}
<div class="item">
  <a class="t" href="{{ it.link }}" target="_blank" rel="noopener">{{ it.title }}</a>
  <div class="src">{% if it.source %}{{ it.source }} · {% endif %}{{ it.when }}</div>
  {% if it.lede %}<div class="lede">{{ it.lede }}</div>{% endif %}
</div>
{% endfor %}
{% else %}
<div class="empty">
  No recent news found for {{ symbol }}.<br>
  <span style="font-size:.82rem">The feed may be rate-limited or the symbol may be delisted.</span>
</div>
{% endif %}
</body>
</html>
"""


def fmt_vol(v):
    if not v:
        return "-"
    for div, suf in [(1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if v >= div:
            return f"{v/div:.1f}{suf}"
    return str(v)


def prepare_rows(record):
    """Shared row enrichment for web page and static HTML export."""
    enriched = []
    for r in flatten(record):
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
        # News summary: local route when served, external link in the
        # offline ZIP snapshot (which may be opened without the webapp).
        r["news_url"] = f"/news/{quote(sym)}.html"
        r["news_ext"] = f"https://finance.yahoo.com/quote/{quote(sym)}/news/"
        enriched.append(r)
    enriched.sort(key=lambda x: (int(x["tier_num"]), abs(x["gap_pct"])), reverse=True)
    return enriched


def render_html(record, static_snapshot=False):
    """Render the gap scan page as HTML using the same template as the website."""
    enriched = prepare_rows(record)
    scanned = record.get("scanned_at", "?")
    src_name = record.get("source", "finnhub")
    meta = f"Scanned {scanned} UTC · source: {src_name}"
    if static_snapshot:
        meta += " · offline snapshot"

    env = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(["html", "xml"])
    )
    template = env.from_string(PAGE)
    return template.render(
        rows=enriched,
        meta=meta,
        symbols_json=json.dumps([r["symbol"] for r in enriched]),
        news_urls_json=json.dumps({r["symbol"]: r["news_url"] for r in enriched}),
        studies=STUDIES,
        static_snapshot=static_snapshot,
    )


@app.route("/<date_str>.html")
def history_page(date_str):
    """Render historical scan report from the gaps history folder."""
    # Ensure it's safe and exists
    f = HISTORY_DIR / f"tv_gaps_{date_str}.json"
    if not f.exists():
        abort(404, f"No report found for {date_str}")
    
    data = json.loads(f.read_text())
    return render_html(data, static_snapshot=False)


@app.route("/news/<symbol>.html")
@app.route("/news/<symbol>")
def news_page(symbol: str):
    """News summary for one symbol: feed digest + optional AI summary."""
    sym = re.sub(r"[^A-Za-z0-9._=-]", "", symbol).upper()[:20]
    if not sym:
        abort(404, "Invalid symbol")

    name = ""
    record = load_latest()
    if record:
        for r in flatten(record):
            if str(r.get("symbol", "")).upper() == sym:
                name = r.get("description") or ""
                break

    items, source, fetched = fetch_news(sym)
    rows = []
    for it in items:
        lede = (it.get("description") or "").strip()
        if len(lede) > 400:
            lede = lede[:397].rstrip() + "..."
        rows.append({
            "title": it.get("title", ""),
            "link": it.get("link", ""),
            "lede": lede,
            "source": source,
            "when": _rel_time(it.get("published", "")),
        })

    ai, model = "", ""
    if items:
        ai, model = _ai_summary_cached(sym, name, items)
    if ai:
        summary, kind = ai, "ai"
    else:
        summary, kind = _fallback_summary(items), "compiled"

    meta = f"Source: {source or 'n/a'} · fetched {fetched} UTC"
    env = Environment(loader=BaseLoader(),
                      autoescape=select_autoescape(["html", "xml"]))
    return env.from_string(NEWS_PAGE).render(
        symbol=sym, name=name, meta=meta, items=rows,
        summary=summary, summary_kind=kind, summary_model=model,
        static_snapshot=False,
    )

@app.route("/")
def index():
    record = load_latest()
    if not record:
        abort(503, "No scan history yet. Run: .venv/bin/python tv_gaps.py 10 --save")

    enriched = prepare_rows(record)
    scanned = record.get("scanned_at", "?")
    src = record.get("source", "finnhub")
    meta = f"Scanned {scanned} UTC · source: {src}"

    return render_html(record, static_snapshot=False)


@app.route("/gaps.zip")
def gaps_zip():
    """ZIP with CSV + full HTML report (same style as the website)."""
    import csv
    import io
    import zipfile

    record = load_latest()
    if not record:
        abort(503, "No scan history yet")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["symbol", "gap_pct", "tier", "premarket_price", "prev_close",
                "premarket_volume", "market_cap", "sector", "description"])
    enriched = prepare_rows(record)
    for r in enriched:
        w.writerow([
            r.get("symbol"), r.get("gap_pct"),
            r.get("tier") or "10%+",
            r.get("premarket_price"), r.get("close") or r.get("prev_close"),
            r.get("premarket_volume"), r.get("market_cap"),
            r.get("sector"), r.get("description"),
        ])

    html = render_html(record, static_snapshot=True)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"gaps_{record.get('date', 'latest')}.csv", buf.getvalue())
        z.writestr(f"gaps_{record.get('date', 'latest')}.html", html)
    zbuf.seek(0)

    resp = send_file(zbuf, mimetype="application/zip",
                     as_attachment=True, download_name="gaps.zip")
    return resp


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
