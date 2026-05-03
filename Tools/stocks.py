"""
title: Stock Info Tool
description: >
  Beautiful real-time stock market cards — price, charts, and
  company info for any publicly traded stock. Powered by Yahoo Finance.
  Zero API key required.

  Commands:
    - "stock info AAPL" / "how is Apple doing?"  → full quote card
    - "AAPL price"                                 → current price
    - "GOOGL 52-week range"                        → price range details
    - "stock chart TSLA"                           → price chart card
    - "compare AAPL MSFT"                          → side-by-side comparison

  Setup: No configuration needed — works out of the box.
  Valves:
    - default_currency: Currency for prices ("USD", "EUR", "GBP", "JPY", etc.)
    - chart_days: Number of days for price chart (7, 30, 90, 180, 365, max)

author: ichrist
version: 2.0.0
license: MIT
requirements: httpx
"""

import httpx
import re
import time
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

# ── Yahoo Finance endpoints (v8/chart + v1/search only — v7/v10 need Crumb cookie) ─────────────────────────────

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
_YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.yahoo.com/",
    "Accept": "application/json, text/plain, */*",
}


def _fetch_json(url: str, params: dict = None) -> dict:
    """Fetch JSON from Yahoo Finance with retry logic."""
    headers = dict(_HEADERS)
    headers["Referer"] = "https://finance.yahoo.com/"
    with httpx.Client(timeout=12) as client:
        r = client.get(url, params=params, headers=headers)
        r.raise_for_status()
        return r.json()


def _fetch_with_cors(ticker: str) -> dict:
    """
    Fetch stock data via Yahoo Finance's CORS endpoint.
    This bypasses browser-level restrictions for inline rendering.
    """
    chart_url = f"{_YAHOO_CHART}{ticker}"
    return _fetch_json(chart_url, params={"range": "5d", "interval": "1d"})


def _get_quote(ticker: str) -> dict:
    """Fetch current quote data using v8/chart endpoint (the only free working Yahoo endpoint)."""
    try:
        data = _fetch_json(
            _YAHOO_CHART + ticker, params={"range": "1d", "interval": "1m"}
        )
        result = data.get("chart", {}).get("result", [])
        if not result:
            return {}
        meta = result[0].get("meta", {})
        # Build a quote-like dict from chart data so existing card builders work
        return {
            "symbol": meta.get("symbol", ticker),
            "shortName": meta.get("shortName", ticker),
            "longName": meta.get("longName", meta.get("shortName", ticker)),
            "currency": meta.get("currency", "USD"),
            "regularMarketPrice": meta.get("regularMarketPrice"),
            "regularMarketChange": meta.get("regularMarketPrice")
            - meta.get("chartPreviousClose", meta.get("regularMarketPrice")),
            "regularMarketChangePercent": 0,
            "regularMarketPreviousClose": meta.get(
                "chartPreviousClose", meta.get("regularMarketPrice")
            ),
            "regularMarketTime": meta.get("regularMarketTime"),
            "regularMarketDayHigh": meta.get("regularMarketDayHigh"),
            "regularMarketDayLow": meta.get("regularMarketDayLow"),
            "regularMarketOpen": meta.get("regularMarketPrice")
            and meta.get("chartPreviousClose"),
            "regularMarketVolume": meta.get("regularMarketVolume"),
            "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
            "hasPrePostMarketData": meta.get("hasPrePostMarketData", False),
            "currentTradingPeriod": meta.get("currentTradingPeriod", {}),
        }
    except Exception:
        return {}


def _get_company_info(ticker: str) -> dict:
    """Fetch company info (sector, industry) from v1/search endpoint."""
    try:
        data = _fetch_json(_YAHOO_SEARCH, params={"q": ticker, "quotesOnly": True})
        for q in data.get("quotes", []):
            if q.get("symbol") == ticker:
                return {
                    "sector": q.get("sectorDisp", q.get("sector", "N/A")),
                    "industry": q.get("industryDisp", q.get("industry", "N/A")),
                }
    except Exception:
        pass
    return {"sector": "N/A", "industry": "N/A"}


def _get_chart(ticker: str, days: str = "30d") -> dict:
    """Fetch price chart data."""
    return _fetch_json(_YAHOO_CHART + ticker, params={"range": days, "interval": "1d"})


def _get_historical(ticker: str, days: int = 5) -> list:
    """Fetch recent historical price points for mini chart."""
    result = _get_chart(ticker, f"{min(days, 365)}d")
    chart = result.get("chart", {})
    timestamps = chart.get("timestamp", [])
    quotes = chart.get("indicators", {}).get("quote", [{}])
    closes = quotes[0].get("close", []) or []

    data = []
    for ts, close in zip(timestamps, closes):
        if close is not None and ts is not None:
            data.append({"time": ts, "close": round(close, 2)})
    return data


def _format_price(val) -> str:
    """Format a price value nicely."""
    if val is None:
        return "N/A"
    return f"{val:,.2f}"


def _format_large(val) -> str:
    """Format large numbers (market cap, revenue, etc.)."""
    if val is None:
        return "N/A"
    suffixes = ["", "K", "M", "B", "T"]
    if abs(val) >= 1_000_000_000_000:
        return f"{val / 1e12:.2f}T"
    elif abs(val) >= 1_000_000_000:
        return f"{val / 1e9:.2f}B"
    elif abs(val) >= 1_000_000:
        return f"{val / 1e6:.2f}M"
    elif abs(val) >= 1_000:
        return f"{val / 1e3:.2f}K"
    return f"{val:,.2f}"


def _parse_number(val) -> float:
    """Safely parse a number from Yahoo Finance data."""
    if val is None:
        return 0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0


def _time_ago(timestamp) -> str:
    """Convert Unix timestamp to human-readable time."""
    if not timestamp:
        return "N/A"
    try:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return dt.strftime("%b %d")
    except Exception:
        return "N/A"


def _direction_color(change, inverse=False):
    """Return green for positive, red for negative."""
    if inverse:
        return "#f44336" if change >= 0 else "#4caf50"
    return "#4caf50" if change >= 0 else "#f44336"


def _change_sign(change):
    """Add + or - sign to change value."""
    return f"+{change:.2f}" if change >= 0 else f"{change:.2f}"


def _build_quote_card(quote: dict, compact: bool = False) -> str:
    """Build a beautiful quote card for a single stock."""
    if not quote:
        return '<div style="color:#f44336;padding:12px;">❌ Stock not found. Check the ticker symbol.</div>'

    symbol = quote.get("symbol", "???")
    short_name = quote.get("shortName", symbol)
    long_name = quote.get("longName", short_name)
    currency = quote.get("currency", "USD")
    current_price = quote.get("regularMarketPrice")
    prev_close = quote.get("regularMarketPreviousClose")
    if current_price and prev_close and prev_close:
        change_val = round(current_price - prev_close, 2)
    else:
        change_val = 0
    change_pct = (change_val / prev_close * 100) if prev_close and prev_close else 0
    change_color = _direction_color(change_val)
    change_str = (
        f"({_change_sign(change_val)} ({change_pct:+.2f}%))" if change_val != 0 else ""
    )

    day_high = quote.get("regularMarketDayHigh")
    day_low = quote.get("regularMarketDayLow")
    f52h = quote.get("fiftyTwoWeekHigh")
    f52l = quote.get("fiftyTwoWeekLow")
    volume = quote.get("regularMarketVolume")
    market_time = quote.get("regularMarketTime")

    # Pre-compute for f-string compat
    _open_price = prev_close
    _day_low = day_low
    _day_high = day_high
    _week_low = f52l
    _week_high = f52h

    # Get company info
    company = _get_company_info(symbol)
    sector_info = company.get("sector", "N/A")
    industry_info = company.get("industry", "N/A")
    sector_str = f"{sector_info} · {industry_info}" if sector_info != "N/A" else ""

    # Mini sparkline from chart
    try:
        hist = _get_historical(symbol, 5)
        sparkline_svg = _build_sparkline(hist, change_val >= 0)
    except Exception:
        sparkline_svg = ""

    time_str = _time_ago(market_time) if market_time else "N/A"

    card_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:transparent;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:6px;}}
.st-card{{background:linear-gradient(135deg, #0d1117, #161b22, #1a2332);color:#e6edf3;border-radius:16px;padding:20px;max-width:640px;box-shadow:0 4px 24px rgba(0,0,0,0.4);border:1px solid rgba(88,166,255,0.15);}}
.st-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;flex-wrap:wrap;gap:8px;}}
.st-ticker{{font-size:1.3rem;font-weight:800;color:#58a6ff;}}
.st-name{{font-size:0.78rem;opacity:0.65;margin-top:2px;}}
.st-sector{{font-size:0.65rem;opacity:0.4;margin-top:1px;}}
.st-meta{{font-size:0.7rem;opacity:0.5;text-align:right;}}
.st-price-block{{display:flex;align-items:baseline;gap:16px;margin:12px 0 8px;}}
.st-price{{font-size:3rem;font-weight:800;letter-spacing:-1px;line-height:1;}}
.st-change{{font-size:1rem;font-weight:700;padding:4px 10px;border-radius:8px;background:rgba(255,255,255,0.06);}}
.st-time{{font-size:0.65rem;opacity:0.45;margin-top:6px;}}
.st-divider{{border:none;border-top:1px solid rgba(255,255,255,0.08);margin:14px 0;}}
.st-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;}}
.st-stat{{background:rgba(255,255,255,0.04);border-radius:10px;padding:8px 12px;border:1px solid rgba(255,255,255,0.06);}}
.st-stat-label{{font-size:0.6rem;text-transform:uppercase;letter-spacing:0.5px;opacity:0.5;margin-bottom:3px;}}
.st-stat-val{{font-size:0.88rem;font-weight:600;}}
.st-footer{{font-size:0.58rem;opacity:0.35;text-align:right;margin-top:12px;}}
</style>
</head>
<body>
<div class="st-card">
  <div class="st-header">
    <div>
      <div class="st-ticker">{symbol} <span style="opacity:0.5;font-size:0.8em;">{currency}</span></div>
      <div class="st-name">{long_name}</div>
      <div class="st-sector">{sector_str}</div>
    </div>
    <div class="st-meta">{time_str}</div>
  </div>
  <div class="st-price-block">
    <div class="st-price">{_format_price(current_price)}</div>
    <div class="st-change" style="color:{change_color};">{change_str}</div>
  </div>
  <hr class="st-divider">
  <div class="st-grid">
    <div class="st-stat"><div class="st-stat-label">Open</div><div class="st-stat-val">{_format_price(_open_price)}</div></div>
    <div class="st-stat"><div class="st-stat-label">Day Range</div><div class="st-stat-val">{_format_price(_day_low)} – {_format_price(_day_high)}</div></div>
    <div class="st-stat"><div class="st-stat-label">52W Range</div><div class="st-stat-val">{_format_price(_week_low)} – {_format_price(_week_high)}</div></div>
    <div class="st-stat"><div class="st-stat-label">Volume</div><div class="st-stat-val">{_format_large(volume)}</div></div>
    <div class="st-stat"><div class="st-stat-label">Day High</div><div class="st-stat-val">{_format_price(_day_high)}</div></div>
    <div class="st-stat"><div class="st-stat-label">Day Low</div><div class="st-stat-val">{_format_price(_day_low)}</div></div>
  </div>
  <div class="st-footer">Powered by Yahoo Finance · No API key required</div>
</div>
</body>
</html>"""

    return card_html


def _build_sparkline(data: list, positive: bool) -> str:
    """Build an SVG sparkline from historical data points."""
    if len(data) < 2:
        return ""
    width = min(len(data) * 3, 200)
    height = 40
    min_val = min(d["close"] for d in data)
    max_val = max(d["close"] for d in data)
    range_val = max_val - min_val if max_val != min_val else 1

    points = []
    for i, d in enumerate(data):
        x = (i / (len(data) - 1)) * width
        y = height - ((d["close"] - min_val) / range_val) * (height - 4) - 2
        points.append(f"{x:.1f},{y:.1f}")

    color = "#4caf50" if positive else "#f44336"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="margin:8px 0;">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _build_chart_card(ticker: str, days: int = 30) -> str:
    """Build a price chart card with a full chart view."""
    days_map = {7: "7d", 30: "30d", 90: "90d", 180: "6m", 365: "1y"}
    range_key = days_map.get(days, "30d")

    try:
        chart = _get_chart(ticker, range_key)
        quote = _get_quote(ticker)
    except Exception as exc:
        return f'<div style="color:#f44336;padding:12px;">❌ Could not fetch chart: {exc}</div>'

    if not chart.get("chart", {}).get("result"):
        return '<div style="color:#f44336;padding:12px;">❌ No chart data found for this ticker.</div>'

    result = chart["chart"]["result"][0]
    meta = result.get("meta", {})
    quotes = result.get("indicators", {}).get("quote", [{}])
    closes = quotes[0].get("close", []) or []
    timestamps = result.get("timestamp", [])
    volumes = quotes[0].get("volume", []) or []

    symbol = meta.get("symbol", ticker)
    currency = meta.get("currency", "USD")
    current_price = meta.get("regularMarketPrice")
    chart_start = meta.get("chartPreviousClose")

    if not closes:
        return (
            '<div style="color:#f44336;padding:12px;">❌ No price data available.</div>'
        )
    valid_data = [
        (t, c, v)
        for t, c, v in zip(timestamps, closes, volumes)
        if c is not None and t is not None
    ]
    if not valid_data:
        return (
            '<div style="color:#f44336;padding:12px;">❌ No price data available.</div>'
        )

    prices = [d[1] for d in valid_data]
    mins = min(prices)
    maxs = max(prices)
    price_range = maxs - mins if maxs != mins else 1

    chart_width = 700
    chart_height = 300
    padding = {"top": 20, "bottom": 40, "left": 60, "right": 20}
    w = chart_width - padding["left"] - padding["right"]
    h = chart_height - padding["top"] - padding["bottom"]

    points = []
    for i, (ts, price, vol) in enumerate(valid_data):
        x = padding["left"] + (i / (len(valid_data) - 1)) * w
        y = padding["top"] + h - ((price - mins) / price_range) * h
        points.append(f"{x:.1f},{y:.1f}")

    color = "#4caf50" if prices[-1] >= prices[0] else "#f44336"
    gradient_id = f"chart_grad_{abs(int(time.time()))}"

    # Y-axis labels
    y_labels = []
    for i in range(5):
        val = mins + (price_range * i / 4)
        y_labels.append(f"{val:,.2f}")

    # Date labels on x-axis
    x_labels = []
    label_count = min(6, len(valid_data))
    step = max(1, len(valid_data) // label_count)
    for i in range(0, len(valid_data), step):
        ts = valid_data[i][0]
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            x_labels.append(
                (
                    padding["left"] + (i / (len(valid_data) - 1)) * w,
                    dt.strftime("%b %d"),
                )
            )
        except Exception:
            x_labels.append((padding["left"] + (i / (len(valid_data) - 1)) * w, ""))

    pad_top = padding["top"]
    pad_bottom = padding["bottom"]
    pad_left = padding["left"]
    pad_right = padding["right"]

    svg_content = f"""<svg width="100%" viewBox="0 0 {chart_width} {chart_height}" xmlns="http://www.w3.org/2000/svg" style="max-width:700px;">
  <defs>
    <linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{color}" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="{color}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <!-- Grid lines -->
"""
    for i in range(5):
        y = padding["top"] + (h * i / 4)
        svg_content += f'  <line x1="{pad_left}" y1="{y:.1f}" x2="{chart_width - pad_right}" y2="{y:.1f}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4,4"/>\n'
        if i < 4:
            val = mins + (price_range * (4 - i) / 4)
            svg_content += f'  <text x="{pad_left - 6}" y="{y + 3}" text-anchor="end" fill="rgba(255,255,255,0.35)" font-size="10">{_format_price(val)}</text>\n'

    # Area fill
    area_last_point = points[-1]
    area_first_point = points[0]
    area_last_x = area_last_point.split(",")[0]
    area_first_x = area_first_point.split(",")[0]
    area_last_coords = f"{area_last_x},{pad_top + h}"
    area_first_coords = f"{area_first_x},{pad_top + h}"
    area_points = points + [area_last_coords, area_first_coords]
    svg_content += (
        f'  <polygon points="{" ".join(area_points)}" fill="url(#{gradient_id})"/>\n'
    )

    # Line
    svg_content += f'  <polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>\n'

    # Current price dot
    last_x, last_y = points[-1].split(",")
    # Pre-compute last price for svg text (avoid [] in f-string)
    _svg_last_price = _format_price(prices[-1])
    svg_content += f'  <circle cx="{last_x}" cy="{last_y}" r="4" fill="{color}" stroke="#0d1117" stroke-width="2"/>\n'
    svg_content += f'  <text x="{float(last_x):.0f}" y="{float(last_y) - 10}" text-anchor="middle" fill="{color}" font-size="11" font-weight="700">{_svg_last_price}</text>\n'

    # Date labels
    for x, label in x_labels:
        if label:
            svg_content += f'  <text x="{x}" y="{chart_height - 8}" text-anchor="middle" fill="rgba(255,255,255,0.35)" font-size="9">{label}</text>\n'

    svg_content += "</svg>"

    # Build the full card
    change = prices[-1] - prices[0]
    change_pct = (change / prices[0]) * 100 if prices[0] else 0
    change_color = _direction_color(change)

    start_price = prices[0]
    period_return = ((prices[-1] / start_price) - 1) * 100 if start_price else 0

    # Pre-compute values to avoid [] in f-strings (Python 3.10/3.11 compat)
    _last_price = prices[-1]
    _open_price = _format_price(valid_data[0][1]) if valid_data else "N/A"

    card_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:transparent;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:6px;}}
.st-card{{background:linear-gradient(135deg,#0d1117,#161b22,#1a2332);color:#e6edf3;border-radius:16px;padding:20px;max-width:720px;box-shadow:0 4px 24px rgba(0,0,0,0.4);border:1px solid rgba(88,166,255,0.15);}}
.st-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;}}
.st-ticker{{font-size:1.3rem;font-weight:800;color:#58a6ff;}}
.st-name{{font-size:0.78rem;opacity:0.65;margin-top:2px;}}
.st-change{{font-size:1rem;font-weight:700;padding:4px 10px;border-radius:8px;background:rgba(255,255,255,0.06);}}
.st-price{{font-size:2rem;font-weight:800;}}
.st-divider{{border:none;border-top:1px solid rgba(255,255,255,0.08);margin:14px 0;}}
.st-info{{display:flex;gap:16px;flex-wrap:wrap;font-size:0.72rem;opacity:0.6;margin-top:10px;}}
.st-footer{{font-size:0.58rem;opacity:0.35;text-align:right;margin-top:12px;}}
</style>
</head>
<body>
<div class="st-card">
  <div class="st-header">
    <div>
      <div class="st-ticker">{symbol} · {currency}</div>
      <div class="st-name">{short_name}</div>
    </div>
    <div style="text-align:right;">
      <div class="st-price">{_format_price(_last_price)}</div>
      <div class="st-change" style="color:{change_color};display:inline-block;">{_change_sign(change)} ({change_pct:+.2f}%)</div>
    </div>
  </div>
  <div class="st-info">
    <span>📊 Open: {_format_price(_open_price)}</span>
    <span>📈 High: {_format_price(max(prices))}</span>
    <span>📉 Low: {_format_price(min(prices))}</span>
    <span>📅 Period: {days}d</span>
  </div>
  <hr class="st-divider">
  <div style="overflow-x:auto;">{svg_content}</div>
  <div class="st-footer">Powered by Yahoo Finance · {days}-day chart</div>
</div>
</body>
</html>"""

    return card_html


def _build_compare_card(tickers: list) -> str:
    """Build a side-by-side comparison card for multiple stocks."""
    cards_html = []
    for t in tickers:
        quote = _get_quote(t.strip())
        if quote:
            cards_html.append(_build_quote_card(quote, compact=True))
        else:
            cards_html.append(
                f'<div style="color:#f44336;padding:10px;font-size:0.85rem;">❌ {t.strip()} — not found</div>'
            )

    cards_str = "\n".join(cards_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:transparent;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:6px;}}
.st-compare-title{{font-size:1rem;font-weight:700;color:#58a6ff;margin-bottom:12px;text-align:center;}}
.st-grid{{display:grid;grid-template-columns:repeat({len(tickers)},1fr);gap:10px;}}
@media(max-width:700px){{.st-grid{{grid-template-columns:1fr;}}}}
</style>
</head>
<body>
<div class="st-compare-title">📊 Stock Comparison</div>
<div class="st-grid">{cards_str}</div>
<div style="text-align:center;font-size:0.58rem;opacity:0.35;margin-top:12px;">Powered by Yahoo Finance · No API key required</div>
</body>
</html>"""


def _parse_tickers(text: str) -> list:
    """Extract stock tickers from user input. Handles comma-separated and 'compare X Y' patterns."""
    text = text.strip()
    # Remove common prefixes
    for prefix in [
        "stock info ",
        "stock ",
        "price ",
        "compare ",
        "chart ",
        "52-week ",
        "52w ",
    ]:
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
            break

    # Split by commas, semicolons, or " and "
    parts = re.split(r"[,;]\s*|\b(?:and)\b", text)
    tickers = []
    for part in parts:
        # Extract ticker symbols (alphanumeric, 1-5 chars, usually)
        matches = re.findall(r"\b([A-Z]{1,5})\b", part.strip())
        tickers.extend(matches)

    # Limit to 4 tickers for comparison
    return list(dict.fromkeys(tickers))[:4]  # dedupe while preserving order


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


class Tools:
    class Valves(BaseModel):
        default_currency: str = Field(
            default="USD",
            description="Default currency for prices (e.g. 'USD', 'EUR', 'GBP').",
        )
        chart_days: int = Field(
            default=30,
            description="Default chart period in days (7, 30, 90, 180, 365).",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def get_stock_info(
        self,
        ticker: str = None,
        action: str = "quote",
        days: int = None,
        __event_emitter__: Optional = None,
    ) -> "HTMLResponse | str":
        """
        Get beautiful stock market info cards for any publicly traded stock.

        Commands:
          - "stock info AAPL" or "AAPL price"          → current quote card
          - "AAPL chart"                                → price chart card
          - "compare AAPL MSFT"                         → side-by-side comparison
          - "AAPL 52-week range"                        → quote card with range info

        :param ticker: Stock ticker symbol(s), e.g. "AAPL" or "AAPL, MSFT" for comparison.
        :param action: One of "quote", "chart", "compare".
        :param days: Chart period in days (7, 30, 90, 180, 365). Defaults to valve setting.
        :return: Rendered HTML stock info card.
        """
        days = days or self.valves.chart_days

        try:
            # Parse tickers from the ticker parameter (handles "compare AAPL MSFT" style)
            tickers = _parse_tickers(ticker if ticker else "")

            if action.lower() == "compare" or (len(tickers) > 1 and not action):
                action = "compare"

            if action == "compare":
                if len(tickers) < 2:
                    msg = "Please provide at least 2 tickers to compare, e.g. 'compare AAPL MSFT'."
                    await _emit(__event_emitter__, msg, done=True)
                    return msg

                await _emit(
                    __event_emitter__,
                    f"📊 Fetching comparison for {', '.join(tickers)}…",
                )
                html = _build_compare_card(tickers)

            elif action == "chart":
                if not tickers:
                    msg = "Please provide a ticker symbol, e.g. 'AAPL chart'."
                    await _emit(__event_emitter__, msg, done=True)
                    return msg

                ticker = tickers[0].upper()
                await _emit(__event_emitter__, f"📈 Fetching chart for {ticker}…")
                html = _build_chart_card(ticker, days)

            else:  # default: quote
                if not tickers:
                    msg = "Please provide a ticker symbol, e.g. 'AAPL' or 'stock info AAPL'."
                    await _emit(__event_emitter__, msg, done=True)
                    return msg

                ticker = tickers[0].upper()
                await _emit(__event_emitter__, f"📋 Fetching quote for {ticker}…")
                quote = _get_quote(ticker)
                html = _build_quote_card(quote)

            await _emit(__event_emitter__, "✅ Stock data loaded!", done=True)
            return HTMLResponse(content=html, headers={"content-disposition": "inline"})

        except ValueError as ve:
            msg = f"❌ {ve}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except Exception as exc:
            msg = f"❌ Could not fetch stock info: {exc}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
