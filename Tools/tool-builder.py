"""
title: Tool Builder
author: ichrist
version: 10.0.2
description: Describe a tool in chat. The LLM calls save_tool(code) with the full .py; it is verified (loaded, every method called once) and installed into Open WebUI in one step. Includes a quality bar, polish score, patch edits, version history and card design kits.
requirements: httpx
"""

import ast
import asyncio
import inspect
import json
import logging
import os
import re
import sys
import time
import traceback
import types
import unicodedata
from typing import Optional

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger("tool_builder")

# ==========================================================================
# DESIGN KITS - ready-made code inlined at save time (`# @include ui, http`).
# read_tool() shows them collapsed back to the one-line marker.
# ==========================================================================

_KIT_UI = r'''
import html as _html
import math
import re as _re
from fastapi.responses import HTMLResponse

PALETTES = {"violet": "#8b5cf6", "blue": "#3b82f6", "green": "#22c55e", "orange": "#f97316",
            "pink": "#ec4899", "teal": "#14b8a6", "red": "#ef4444", "gold": "#eab308"}
DONUT_COLORS = ["#8b5cf6", "#22c55e", "#f59e0b", "#ef4444", "#3b82f6", "#ec4899", "#14b8a6", "#eab308"]


class Raw(str):
    """Marks already-safe HTML so esc() leaves it alone."""


def esc(v) -> str:
    """HTML-escape any value (None becomes an em dash). Raw(...) is passed through."""
    if isinstance(v, Raw):
        return str(v)
    return _html.escape("—" if v is None else str(v))


def _hex(c, default="#8b5cf6") -> str:
    c = PALETTES.get(str(c or "").lower(), c or "")
    return c if _re.fullmatch(r"#[0-9a-fA-F]{6}", str(c)) else default


_UI_CSS = """
:root{--a:__A__;--b:__B__;--fg:#fff;--mute:rgba(255,255,255,.55);--ln:rgba(255,255,255,.1)}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent;font-family:'Nunito',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:8px;color:#e8e8f0}
.card{max-width:700px;margin:0 auto;border-radius:24px;overflow:hidden;background:#0d0d14;box-shadow:0 0 0 1px rgba(255,255,255,.06),0 20px 50px rgba(0,0,0,.6),0 0 70px __A__22}
.banner{position:relative;padding:26px;background:linear-gradient(135deg,__A__cc,__B__88 60%,__A__44);display:flex;align-items:center;justify-content:space-between;gap:16px;overflow:hidden}
.banner::after{content:'';position:absolute;top:-90px;right:-70px;width:300px;height:300px;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.12),transparent 70%);pointer-events:none}
.btx{position:relative;z-index:1}
.kicker{font:700 .75rem 'Space Mono',ui-monospace,monospace;letter-spacing:1px;color:rgba(255,255,255,.65)}
.title{font-size:2.3rem;font-weight:900;letter-spacing:-1px;color:#fff;line-height:1.05;text-shadow:0 2px 18px rgba(0,0,0,.35);margin:4px 0 6px}
.sub{font-size:.85rem;color:rgba(255,255,255,.75);font-weight:600;margin-bottom:10px}
.badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{padding:4px 12px;border-radius:999px;font-size:.68rem;font-weight:800;letter-spacing:.8px;text-transform:uppercase;color:#fff;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.28)}
.hero{position:relative;z-index:1;font-size:4rem;line-height:1;filter:drop-shadow(0 6px 20px rgba(0,0,0,.4));animation:float 4s ease-in-out infinite}
.tabs{display:flex;gap:2px;padding:0 16px;background:rgba(0,0,0,.28);border-bottom:1px solid rgba(255,255,255,.06);overflow-x:auto}
.tab{padding:12px 16px;font:800 .72rem 'Nunito',sans-serif;letter-spacing:.8px;text-transform:uppercase;color:rgba(255,255,255,.4);background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap}
.tab:hover{color:rgba(255,255,255,.75)}
.tab.on{color:#fff;border-bottom-color:var(--a)}
.pane{display:none}.pane.on{display:block}
.body{padding:22px 26px;display:flex;flex-direction:column;gap:18px}
.row{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.grow{flex:1;min-width:220px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tile{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:11px 14px}
.tile .l{font-size:.6rem;text-transform:uppercase;letter-spacing:.8px;color:rgba(255,255,255,.4);font-weight:700;margin-bottom:3px}
.tile .v{font-size:.95rem;font-weight:800;color:#f2f2ff;word-break:break-word}
.sec{display:flex;align-items:center;gap:8px;font-size:.65rem;text-transform:uppercase;letter-spacing:1.5px;font-weight:900;color:var(--a)}
.sec::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,__A__55,transparent)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:6px 13px;font-size:.78rem;font-weight:700;color:#d6d6ee}
.bar{display:grid;grid-template-columns:110px 1fr 56px;align-items:center;gap:10px;margin-bottom:8px;font-size:.78rem}
.bn{color:rgba(255,255,255,.55);font-weight:700;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trk{height:8px;background:rgba(255,255,255,.07);border-radius:9px;overflow:hidden}
.fil{height:100%;width:0;border-radius:9px;animation:grow 1s cubic-bezier(.22,1,.36,1) .15s forwards}
.bv{font:700 .75rem 'Space Mono',ui-monospace,monospace;color:#fff}
.note{background:linear-gradient(135deg,__A__16,rgba(255,255,255,.03));border:1px solid __A__44;border-radius:14px;padding:14px 18px;font-size:.88rem;line-height:1.7;color:rgba(255,255,255,.78);font-weight:600}
.scroll{overflow-x:auto}
.tb{width:100%;border-collapse:collapse;font-size:.78rem}
.tb th{font-size:.58rem;text-transform:uppercase;letter-spacing:.8px;color:rgba(255,255,255,.35);font-weight:800;padding:6px 8px;text-align:left;border-bottom:1px solid rgba(255,255,255,.08)}
.tb td{padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.04);color:rgba(255,255,255,.8)}
.tb tr:hover td{background:rgba(255,255,255,.03)}
.donut{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.legend div{font-size:.78rem;font-weight:700;color:rgba(255,255,255,.7);margin:4px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px}
.foot{display:flex;justify-content:space-between;gap:10px;padding:11px 26px;background:rgba(0,0,0,.3);font:600 .62rem 'Space Mono',ui-monospace,monospace;color:rgba(255,255,255,.28)}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes grow{to{width:var(--w)}}
.tb th[data-sort]{cursor:pointer}.tb th[data-sort]:hover{color:var(--a)}
.big{font-size:3.2rem;font-weight:900;color:var(--fg);line-height:1;letter-spacing:-1px}.big small{font-size:1.1rem;color:var(--mute);font-weight:700;margin-left:4px}
.lbl{font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--mute);font-weight:800;margin-top:6px}
.dl{display:inline-block;margin-top:8px;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:800}
.dl.up{color:#22c55e;background:#22c55e22}.dl.dn{color:#ef4444;background:#ef444422}
.tl{border-left:2px solid var(--ln);margin-left:6px;padding-left:18px}
.tl .it{position:relative;margin-bottom:16px}.tl .it::before{content:'';position:absolute;left:-25px;top:4px;width:10px;height:10px;border-radius:50%;background:var(--a);box-shadow:0 0 0 3px __A__33}
.tl .tt{font-weight:800;font-size:.9rem;color:var(--fg)}.tl .tx{font-size:.8rem;color:var(--mute);line-height:1.5;margin-top:2px}.tl .wn{font:700 .65rem 'Space Mono',ui-monospace,monospace;color:var(--a)}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:12px}.cmp>div{background:rgba(127,127,127,.07);border:1px solid var(--ln);border-radius:14px;padding:12px 14px}
.cmp h4{font-size:.9rem;font-weight:900;color:var(--a);margin-bottom:8px}.cmp p{display:flex;justify-content:space-between;gap:8px;font-size:.78rem;padding:4px 0;border-bottom:1px solid var(--ln);color:var(--mute)}.cmp p b{color:var(--fg)}
.rings{display:flex;gap:18px;flex-wrap:wrap}.ring{text-align:center}.ring .lbl{margin-top:2px}
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}.gal img{width:100%;height:110px;object-fit:cover;border-radius:12px;border:1px solid var(--ln)}
.empty{text-align:center;padding:30px 10px}.empty .em{font-size:2.6rem}.empty .t{font-weight:900;font-size:1.05rem;color:var(--fg);margin-top:8px}.empty .x{font-size:.85rem;color:var(--mute);margin-top:4px}
details.col{border:1px solid var(--ln);border-radius:14px;padding:10px 14px}details.col summary{cursor:pointer;font-weight:800;font-size:.85rem;color:var(--fg)}details.col[open] summary{margin-bottom:10px}
.cp{background:rgba(127,127,127,.12);border:1px solid var(--ln);color:var(--fg);border-radius:10px;padding:5px 12px;font:800 .72rem 'Nunito',sans-serif;cursor:pointer}.cp:hover{border-color:var(--a)}
@media(max-width:520px){.cmp{grid-template-columns:1fr}.title{font-size:1.8rem}.banner{flex-direction:column;align-items:flex-start}.bar{grid-template-columns:80px 1fr 48px}.body{padding:18px}}
"""

_UI_LIGHT = """
:root{--fg:#15151f;--mute:rgba(0,0,0,.55);--ln:rgba(0,0,0,.1)}
html,body{color:#15151f}
.card{background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.08),0 14px 36px rgba(0,0,0,.12)}
.tabs{background:rgba(0,0,0,.04);border-bottom-color:rgba(0,0,0,.08)}.tab{color:rgba(0,0,0,.45)}.tab:hover{color:rgba(0,0,0,.8)}.tab.on{color:#111}
.tile{background:rgba(0,0,0,.03);border-color:rgba(0,0,0,.08)}.tile .l{color:rgba(0,0,0,.5)}.tile .v{color:#111}
.chip{background:rgba(0,0,0,.05);border-color:rgba(0,0,0,.1);color:#333}
.bn{color:rgba(0,0,0,.6)}.trk{background:rgba(0,0,0,.08)}.bv{color:#111}.note{color:rgba(0,0,0,.75)}
.tb th{color:rgba(0,0,0,.5);border-bottom-color:rgba(0,0,0,.12)}.tb td{color:rgba(0,0,0,.8);border-bottom-color:rgba(0,0,0,.06)}.tb tr:hover td{background:rgba(0,0,0,.03)}
.legend div{color:rgba(0,0,0,.7)}.foot{background:rgba(0,0,0,.04);color:rgba(0,0,0,.45)}
"""

_UI_JS = """
document.addEventListener('click',function(e){
var b=e.target.closest('[data-tab]');
if(b){var r=b.closest('.card');
r.querySelectorAll('[data-tab]').forEach(function(x){x.classList.toggle('on',x===b)});
r.querySelectorAll('[data-pane]').forEach(function(p){p.classList.toggle('on',p.getAttribute('data-pane')===b.getAttribute('data-tab'))});rh();return;}
var h=e.target.closest('th[data-sort]');
if(h){var t=h.closest('table'),i=Array.prototype.indexOf.call(h.parentNode.children,h),d=h.getAttribute('data-dir')==='a'?-1:1;h.setAttribute('data-dir',d===1?'a':'d');
var rows=Array.prototype.slice.call(t.tBodies[0].rows);
rows.sort(function(x,y){var a=x.cells[i].textContent.trim(),c=y.cells[i].textContent.trim(),n=parseFloat(a.replace(/[^0-9.\\-]/g,'')),m=parseFloat(c.replace(/[^0-9.\\-]/g,''));
return (isNaN(n)||isNaN(m)?a.localeCompare(c):n-m)*d});
rows.forEach(function(r){t.tBodies[0].appendChild(r)});return;}
var c=e.target.closest('[data-copy]');
if(c){var v=c.getAttribute('data-copy'),o=c.textContent;
function ok(){c.textContent='Copied';setTimeout(function(){c.textContent=o},1200)}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(v).then(ok,ok)}else{var a=document.createElement('textarea');a.value=v;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(x){}a.remove();ok()}}
});
function rh(){try{parent.postMessage({type:'iframe:height',height:document.documentElement.scrollHeight},'*')}catch(e){}}
window.addEventListener('load',rh);document.addEventListener('toggle',rh,true);
if(typeof ResizeObserver!=='undefined'){new ResizeObserver(rh).observe(document.body)}
"""


def ui_page(body, accent="violet", accent2="", title="", fonts=True, theme="dark") -> str:
    """Wrap card content into a complete HTML document. accent = palette name or #rrggbb. theme = dark | light | auto (follows the system)."""
    a = _hex(accent)
    b = _hex(accent2, a)
    css = _UI_CSS.replace("__A__", a).replace("__B__", b)
    if theme == "light":
        css += _UI_LIGHT
    elif theme == "auto":
        css += "@media (prefers-color-scheme: light){" + _UI_LIGHT + "}"
    font = ('<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800;900'
            '&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">') if fonts else ""
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            + font + "<title>" + esc(title) + "</title><style>" + css + "</style></head><body>"
            + '<div class="card">' + body + "</div><script>" + _UI_JS + "</script></body></html>")


def ui_banner(title, subtitle="", badges=(), emoji="", kicker="") -> str:
    """Gradient header: kicker (small mono line), big title, subtitle, badges, big hero emoji."""
    chips = "".join('<span class="badge">' + esc(x) + "</span>" for x in badges if x)
    return ('<div class="banner"><div class="btx">'
            + ('<div class="kicker">' + esc(kicker) + "</div>" if kicker else "")
            + '<div class="title">' + esc(title) + "</div>"
            + ('<div class="sub">' + esc(subtitle) + "</div>" if subtitle else "")
            + '<div class="badges">' + chips + "</div></div>"
            + ('<div class="hero">' + esc(emoji) + "</div>" if emoji else "") + "</div>")


def ui_body(*parts) -> str:
    """Padded content area (use when you do not need tabs)."""
    return '<div class="body">' + "".join(parts) + "</div>"


def ui_tabs(panes: dict) -> str:
    """Tab bar + panes. panes = {"Overview": html, "Details": html}. First tab active, JS built in."""
    keys = list(panes)
    bar = "".join('<button class="tab' + (" on" if i == 0 else "") + '" data-tab="' + esc(k) + '">' + esc(k) + "</button>"
                  for i, k in enumerate(keys))
    body = "".join('<div class="pane' + (" on" if i == 0 else "") + '" data-pane="' + esc(k)
                   + '"><div class="body">' + panes[k] + "</div></div>" for i, k in enumerate(keys))
    return '<div class="tabs">' + bar + "</div>" + body


def ui_section(title) -> str:
    return '<div class="sec">' + esc(title) + "</div>"


def ui_tiles(pairs) -> str:
    """Grid of label/value stat tiles. pairs = [("Height", "1.7 m"), ...]."""
    return '<div class="tiles">' + "".join(
        '<div class="tile"><div class="l">' + esc(l) + '</div><div class="v">' + esc(v) + "</div></div>"
        for l, v in pairs) + "</div>"


def ui_badge(text, color="#8b5cf6") -> Raw:
    c = _hex(color)
    return Raw('<span class="chip" style="background:' + c + "22;color:" + c + ";border-color:" + c + '55">'
               + esc(text) + "</span>")


def ui_chips(items, empty="—") -> str:
    items = [i for i in (items or []) if i]
    inner = "".join('<span class="chip">' + esc(i) + "</span>" for i in items) or '<span class="chip">' + esc(empty) + "</span>"
    return '<div class="chips">' + inner + "</div>"


def ui_note(text) -> str:
    return '<div class="note">' + esc(text) + "</div>"


def ui_row(left, right="") -> str:
    """Two blocks side by side (wraps on mobile). Typical: bars left, svg_radar right."""
    return '<div class="row"><div class="grow">' + left + "</div>" + (("<div>" + right + "</div>") if right else "") + "</div>"


def ui_bars(rows, max_value=None, color="", unit="") -> str:
    """Animated horizontal bars. rows = [(label, value[, '#hex'])]. Default colour = accent."""
    rows = list(rows)
    vals = []
    for r in rows:
        try:
            vals.append(float(r[1]))
        except Exception:
            vals.append(0.0)
    mx = max_value or max(vals + [1.0])
    out = []
    for r, v in zip(rows, vals):
        col = _hex(r[2]) if len(r) > 2 else (_hex(color) if color else "var(--a)")
        pct = max(0.0, min(100.0, v / mx * 100)) if mx else 0.0
        shown = (f"{v:,.0f}" if abs(v) >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")) + unit
        out.append('<div class="bar"><span class="bn">' + esc(r[0]) + '</span><div class="trk"><div class="fil" style="--w:'
                   + ("%.1f" % pct) + "%;background:" + col + '"></div></div><span class="bv">' + esc(shown) + "</span></div>")
    return "".join(out)


def ui_table(headers, rows) -> str:
    """Table. Clicking a header sorts the column."""
    th = "".join('<th data-sort="1">' + esc(h) + "</th>" for h in headers)
    tr = "".join("<tr>" + "".join("<td>" + esc(c) + "</td>" for c in r) + "</tr>" for r in rows)
    return '<div class="scroll"><table class="tb"><thead><tr>' + th + "</tr></thead><tbody>" + tr + "</tbody></table></div>"


def ui_footer(left="", right="") -> str:
    return '<div class="foot"><span>' + esc(left) + "</span><span>" + esc(right) + "</span></div>"


def svg_radar(labels, values, max_value=100, color="", size=190) -> str:
    """Radar/spider chart. 3+ axes."""
    n = len(labels)
    c = size / 2.0
    r = size / 2.0 - 26
    ang = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
    col = _hex(color) if color else "var(--a)"

    def pt(f, a):
        return "%.1f,%.1f" % (c + r * f * math.cos(a), c - r * f * math.sin(a))

    grid = "".join('<polygon points="' + " ".join(pt(f, a) for a in ang) + '" fill="none" stroke="rgba(255,255,255,.09)"/>'
                   for f in (0.25, 0.5, 0.75, 1))
    axes = "".join('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="rgba(255,255,255,.09)"/>'
                   % (c, c, c + r * math.cos(a), c - r * math.sin(a)) for a in ang)
    fr = []
    for v in values:
        try:
            fr.append(max(0.0, min(1.0, float(v) / max_value)))
        except Exception:
            fr.append(0.0)
    poly = " ".join(pt(f, a) for f, a in zip(fr, ang))
    labs = "".join('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="8" font-weight="700" '
                   'fill="rgba(255,255,255,.55)" font-family="monospace">%s</text>'
                   % (c + (r + 14) * math.cos(a), c - (r + 14) * math.sin(a) + 3, esc(l)) for l, a in zip(labels, ang))
    return ('<svg viewBox="0 0 %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">' % (size, size, size, size)
            + grid + axes + '<polygon points="' + poly + '" style="fill:' + col + ";fill-opacity:.28;stroke:" + col
            + '" stroke-width="1.6" stroke-linejoin="round"/>' + labs + "</svg>")


def svg_line(values, labels=None, color="", w=460, h=140) -> str:
    """Line/area chart with dots. Needs 2+ numeric values."""
    vals = []
    for v in values:
        try:
            vals.append(float(v))
        except Exception:
            pass
    if len(vals) < 2:
        return ""
    col = _hex(color) if color else "var(--a)"
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pad = 16
    xs = [pad + i * (w - 2 * pad) / (len(vals) - 1) for i in range(len(vals))]
    ys = [h - pad - 10 - (v - lo) / span * (h - 2 * pad - 10) for v in vals]
    pts = " ".join("%.1f,%.1f" % p for p in zip(xs, ys))
    area = "%.1f,%.1f " % (xs[0], h - pad - 10) + pts + " %.1f,%.1f" % (xs[-1], h - pad - 10)
    dots = "".join('<circle cx="%.1f" cy="%.1f" r="2.6" style="fill:%s"/>' % (x, y, col) for x, y in zip(xs, ys))
    txt = ""
    if labels:
        step = max(1, int(math.ceil(len(vals) / 6.0)))
        for i in range(0, len(vals), step):
            if i < len(labels):
                txt += ('<text x="%.1f" y="%d" text-anchor="middle" font-size="8" fill="rgba(255,255,255,.45)" '
                        'font-family="monospace">%s</text>' % (xs[i], h - 2, esc(labels[i])))
    return ('<svg viewBox="0 0 %d %d" width="100%%" xmlns="http://www.w3.org/2000/svg">' % (w, h)
            + '<polygon points="' + area + '" style="fill:' + col + ';fill-opacity:.15"/>'
            + '<polyline points="' + pts + '" fill="none" style="stroke:' + col + '" stroke-width="2" stroke-linejoin="round"/>'
            + dots + txt + "</svg>")


def svg_donut(parts, size=150) -> str:
    """Donut chart with legend. parts = [(label, value[, '#hex'])]."""
    vals = []
    for p in parts:
        try:
            vals.append(max(0.0, float(p[1])))
        except Exception:
            vals.append(0.0)
    tot = sum(vals) or 1.0
    c = size / 2.0
    r = size / 2.0 - 12
    circ = 2 * math.pi * r
    off = 0.0
    segs, legend = "", ""
    for i, (p, v) in enumerate(zip(parts, vals)):
        col = _hex(p[2]) if len(p) > 2 else DONUT_COLORS[i % len(DONUT_COLORS)]
        ln = v / tot * circ
        segs += ('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="16" '
                 'stroke-dasharray="%.2f %.2f" stroke-dashoffset="%.2f" transform="rotate(-90 %.1f %.1f)"/>'
                 % (c, c, r, col, ln, circ - ln, -off, c, c))
        off += ln
        legend += '<div><i style="background:' + col + '"></i>' + esc(p[0]) + " · " + ("%.0f%%" % (v / tot * 100)) + "</div>"
    svg = ('<svg viewBox="0 0 %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">' % (size, size, size, size)
           + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="16"/>' % (c, c, r)
           + segs + "</svg>")
    return '<div class="donut">' + svg + '<div class="legend">' + legend + "</div></div>"


def _safe_url(u) -> str:
    u = str(u or "").strip()
    return u if _re.match(r"https?://", u) else ""


def ui_stat_hero(value, label="", delta=None, unit="") -> str:
    """One big headline number with label and optional trend chip. delta is text like "+2.4%" or "-3" (a leading - or down arrow shows red)."""
    chip = ""
    if delta not in (None, ""):
        d = str(delta).strip()
        chip = '<div class="dl ' + ("dn" if d.startswith(("-", "▼")) else "up") + '">' + esc(d) + "</div>"
    return ('<div><div class="big">' + esc(value) + ("<small>" + esc(unit) + "</small>" if unit else "") + "</div>"
            + ('<div class="lbl">' + esc(label) + "</div>" if label else "") + chip + "</div>")


def ui_timeline(items) -> str:
    """Vertical timeline. items = [(title, text[, when])]."""
    out = ""
    for it in items:
        out += ('<div class="it">' + ('<div class="wn">' + esc(it[2]) + "</div>" if len(it) > 2 and it[2] else "")
                + '<div class="tt">' + esc(it[0]) + "</div>"
                + ('<div class="tx">' + esc(it[1]) + "</div>" if len(it) > 1 and it[1] else "") + "</div>")
    return '<div class="tl">' + out + "</div>"


def ui_compare(left, right) -> str:
    """Two items side by side. left/right = (title, [(label, value), ...])."""
    def col(x):
        return "<div><h4>" + esc(x[0]) + "</h4>" + "".join("<p><span>" + esc(l) + "</span><b>" + esc(v) + "</b></p>" for l, v in x[1]) + "</div>"
    return '<div class="cmp">' + col(left) + col(right) + "</div>"


def ui_ring(value, max_value=100, label="", color="", size=104) -> str:
    """Circular progress ring with the value in the middle. Put several in ui_row or call ui_rings."""
    try:
        f = max(0.0, min(1.0, float(value) / float(max_value)))
    except Exception:
        f = 0.0
    col = _hex(color) if color else "var(--a)"
    r = size / 2.0 - 9
    circ = 2 * math.pi * r
    c = size / 2.0
    svg = ('<svg viewBox="0 0 %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">' % (size, size, size, size)
           + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="rgba(127,127,127,.2)" stroke-width="8"/>' % (c, c, r)
           + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" style="stroke:%s" stroke-width="8" stroke-linecap="round" '
             'stroke-dasharray="%.2f %.2f" transform="rotate(-90 %.1f %.1f)"/>' % (c, c, r, col, f * circ, circ, c, c)
           + '<text x="%.1f" y="%.1f" text-anchor="middle" font-size="%d" font-weight="900" style="fill:var(--fg)" font-family="sans-serif">%s</text></svg>'
           % (c, c + 5, size // 5, esc(value)))
    return '<div class="ring">' + svg + ('<div class="lbl">' + esc(label) + "</div>" if label else "") + "</div>"


def ui_rings(items, max_value=100) -> str:
    """Row of progress rings. items = [(label, value[, '#hex'])]."""
    return '<div class="rings">' + "".join(ui_ring(i[1], max_value, i[0], i[2] if len(i) > 2 else "") for i in items) + "</div>"


def ui_gallery(urls) -> str:
    """Image grid (http/https only, broken images hide themselves)."""
    imgs = "".join('<img src="' + esc(_safe_url(u)) + '" loading="lazy" onerror="this.style.display=\'none\'" alt="">' for u in urls if _safe_url(u))
    return '<div class="gal">' + imgs + "</div>" if imgs else ""


def ui_empty(title="Nothing found", text="", emoji="🔍") -> str:
    """Designed empty state for no-results cases."""
    return ('<div class="empty"><div class="em">' + esc(emoji) + '</div><div class="t">' + esc(title) + "</div>"
            + ('<div class="x">' + esc(text) + "</div>" if text else "") + "</div>")


def ui_collapse(title, content_html, open=False) -> str:
    """Collapsible section for long details. content_html must already be safe HTML (built with ui_* helpers)."""
    return '<details class="col"' + (" open" if open else "") + "><summary>" + esc(title) + "</summary>" + content_html + "</details>"


def ui_copy(text, label="Copy") -> str:
    """Copy-to-clipboard button."""
    return '<button class="cp" data-copy="' + esc(text) + '">' + esc(label) + "</button>"


def ui_error(title, message="", emoji="⚠️", accent="red"):
    """A complete friendly error card. Return it directly from the tool method instead of a bare error string."""
    body = "<!--ui-error-->" + ui_banner(title, "", emoji=emoji) + ui_body(ui_note(message) if message else ui_empty("Something went wrong"))
    return ui_response(ui_page(body, accent=accent, title=title))


def ui_response(page, llm_context=""):
    """Return the card to Open WebUI. llm_context (optional) gives the LLM a text summary of what is shown."""
    resp = HTMLResponse(content=page, headers={"content-disposition": "inline"})
    return (resp, llm_context) if llm_context else resp
'''

_KIT_EVENTS = r'''
from datetime import datetime as _dt


async def emit_status(em, text, done=False):
    """Live progress line above the answer. Call before slow steps, finish with done=True."""
    if em:
        try:
            await em({"type": "status", "data": {"description": text, "done": done}})
        except Exception:
            pass


async def emit_notify(em, text, level="success"):
    """Toast notification. level: info | success | warning | error."""
    if em:
        try:
            await em({"type": "notification", "data": {"type": level, "content": text}})
        except Exception:
            pass


async def emit_followups(em, suggestions):
    """Clickable follow-up suggestions under the answer, e.g. ["Compare with France", "Show another"]."""
    if em:
        try:
            await em({"type": "chat:message:follow_ups", "data": {"follow_ups": list(suggestions)[:4]}})
        except Exception:
            pass


async def emit_cite(em, title, url, snippet=""):
    """Source chip under the answer."""
    if em:
        try:
            await em({"type": "citation", "data": {
                "document": [snippet or title],
                "metadata": [{"date_accessed": _dt.now().isoformat(), "source": title, "url": url}],
                "source": {"name": title, "url": url}}})
        except Exception:
            pass
'''

_KIT_HTTP = r'''
import asyncio
import time as _time
import httpx

_CACHE = {}


async def http_json(url, params=None, headers=None, timeout=15, retries=2, ttl=0):
    """GET -> parsed JSON. Retries timeouts/5xx, 4xx raises httpx.HTTPStatusError. ttl>0 caches in memory (seconds)."""
    key = url + "|" + repr(sorted((params or {}).items()))
    if ttl:
        hit = _CACHE.get(key)
        if hit and _time.time() - hit[0] < ttl:
            return hit[1]
    last = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as c:
        for i in range(retries + 1):
            try:
                r = await c.get(url, params=params)
                if r.status_code < 500:
                    r.raise_for_status()
                    data = r.json()
                    if ttl:
                        if len(_CACHE) > 200:
                            _CACHE.clear()
                        _CACHE[key] = (_time.time(), data)
                    return data
                last = httpx.HTTPStatusError("HTTP %s" % r.status_code, request=r.request, response=r)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
            await asyncio.sleep(0.6 * (i + 1))
    raise last


async def gather_limited(coros, limit=6):
    """Run coroutines in parallel (max `limit` at once). Results in order; failures come back as Exception objects."""
    sem = asyncio.Semaphore(limit)

    async def _run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(_run(c) for c in coros), return_exceptions=True)
'''

_KIT_LLM = r'''
import inspect as _inspect
import json as _json


async def llm_complete(request, user, prompt, model="", system="", max_tokens=300, temperature=0.7) -> str:
    """Ask this server's chat model. Returns "" on ANY failure, so ALWAYS keep a static fallback.
    model=(__model__ or {}).get("id", "") from the tool method, or a LLM_MODEL valve."""
    try:
        from open_webui.utils.chat import generate_chat_completion
        from open_webui.models.users import Users

        uid = (user or {}).get("id")
        if not (request and uid and model):
            return ""
        u = Users.get_user_by_id(uid)
        if _inspect.isawaitable(u):
            u = await u
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        res = await generate_chat_completion(
            request, {"model": model, "messages": msgs, "stream": False, "max_tokens": max_tokens,
                      "temperature": temperature}, user=u)
        if hasattr(res, "body"):
            res = _json.loads(res.body)
        return (res["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""
'''

_KIT_STORE = r'''
import json as _json
import os as _os


def _store_path(name, uid):
    d = _os.path.join(_os.environ.get("DATA_DIR", "/tmp"), "tool_data")
    _os.makedirs(d, exist_ok=True)
    safe = "".join(ch for ch in (str(name) + "_" + str(uid or "anon")) if ch.isalnum() or ch in "-_")
    return _os.path.join(d, safe + ".json")


def store_load(name, uid, default=None):
    """Per-user JSON persistence (trackers, todo lists, counters)."""
    try:
        with open(_store_path(name, uid), "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return default


def store_save(name, uid, data) -> bool:
    try:
        with open(_store_path(name, uid), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False
'''


def _kit(name: str, src: str) -> str:
    return f"# ==== kit:{name} begin ====\n{src.strip()}\n# ==== kit:{name} end ====\n"


KITS = {
    "ui": _kit("ui", _KIT_UI),
    "events": _kit("events", _KIT_EVENTS),
    "http": _kit("http", _KIT_HTTP),
    "llm": _kit("llm", _KIT_LLM),
    "store": _kit("store", _KIT_STORE),
}

# ==========================================================================
# THE GUIDE - the only thing the LLM has to read. One page, one example.
# ==========================================================================

GUIDE = '''HOW TO BUILD AN OPEN WEBUI TOOL (follow exactly)
1. (Optional, for anything non-trivial) plan_tool(idea) returns a 6-line design template. Answer it in your head, do not stall.
2. Write the COMPLETE file and pass it as the `code` argument of save_tool(code=...). Do NOT paste the file into the chat: nothing exists
   until save_tool has returned "Created" or "Updated". The tool call carries the raw code, so you never escape anything.
3. save_tool verifies the file (loads it, calls every method once), installs it, and prints a Polish score with suggestions.
4. Errors come back with the failing line. Fix with patch_tool(tool_id, patch) using SEARCH/REPLACE blocks:
       <<<<<<< SEARCH
       exact old lines (copy from read_tool)
       =======
       new lines
       >>>>>>> REPLACE
   Only resend the whole file for a big rewrite. Never loop more than 3 times: report the exact error instead.
5. If the Polish score is below 8 (simple text tools normally score 10), apply its top suggestions in ONE patch_tool call, then stop polishing.
6. Finish with the user instructions save_tool prints, in this order: FIRST ask the user to refresh the browser (F5), THEN enable the tool
   via the + menu > Tools. You cannot call a tool you just made. To upgrade an existing tool later: improve_tool(tool_id).

FILE RULES
- Write real characters (é, ✓, emoji) in the file, NEVER \\uXXXX escape sequences.
- Header docstring first: title (short Title Case, 1-2 words), description, author, version, requirements (pip names, only if beyond httpx/pydantic/fastapi/requests).
- ONE top-level `class Tools:` with `def __init__(self): self.valves = self.Valves()`.
- Public method = a tool for the LLM: `async def verb_noun(self, x: str) -> "HTMLResponse | str"`, full type hints, a docstring saying WHAT and WHEN
  (and when NOT), `:param x: ...` per parameter. Helpers start with `_`. 1-6 public methods. `await` every async call (a missing await is the #1 bug).
- Settings: `class Valves(BaseModel)` (admin) and optional `class UserValves(BaseModel)` (per user, read with
  `getattr((__user__ or {}).get("valves"), "UNITS", "metric")`). Every Field: default + description. Never hardcode secrets: API_KEY valve.
- Never raise to the LLM: catch and return a friendly message or ui_error card. Free keyless APIs first. Always set timeouts.
- Special args (never in :param): __user__, __request__, __event_emitter__, __event_call__, __model__, __metadata__, __messages__.
- Cards: docstring must say "The card is displayed to the user automatically, so reply with at most one short sentence."

QUALITY BAR - match the effort to the request. SIMPLE tools (calculator, converter, ask-the-user, formatter, a few lines of logic) stay SMALL:
  plain text result, no card, no valves unless something is truly configurable, no status steps, no citations, no follow-ups. Do not over-build them.
  Everything below the line applies to tools that fetch data or show results visually. First decide: will the user LOOK at the result?
  CARD  = several values, an entity with attributes, prices, stats, schedules, comparisons, trackers.
  TEXT  = one value, pure computation, yes/no, or data for you to reason over. Keep text short and structured.
  Card recipe: banner (identity + hero emoji) -> tabs when there are 2+ kinds of info -> ONE headline number (ui_stat_hero) -> tiles for facts
  -> a visual for every set of numbers (ui_bars, svg_radar, svg_line, svg_donut, ui_rings) -> chips for lists -> a note for narrative
  -> footer with the data source. Derive the accent from the data (type colour, up = green, down = red) or an ACCENT valve.
  For CARD or network tools ALWAYS: emit_status before slow steps, emit_cite for every external source, cache with ttl, gather_limited for parallel calls, a valve for every
  number/URL/colour you would hardcode, ui_empty for no results, ui_error for failures, llm_context so you can discuss the result, emit_followups with 2-3 next questions.
  NEVER: raw JSON dumps, None/NaN on screen (use a dash), empty sections (hide them), walls of text, hand-written CSS (use the kit).

KITS - write `# @include ui, http, events` after the imports instead of writing helpers. Never copy or edit them, just call them.
  ui     esc(v) Raw(html) | ui_page(body, accent="teal"|"#hex", title="", theme="dark"|"light"|"auto") | ui_banner(title, subtitle, badges, emoji, kicker)
         ui_tabs({"Overview": html}) ui_body(*parts) ui_section(t) ui_tiles([(label, value)]) ui_chips(list) ui_badge(text, color) ui_note(text)
         ui_stat_hero(value, label, delta="+2%", unit) ui_timeline([(title, text, when)]) ui_compare((title, [(l, v)]), (title, [(l, v)]))
         ui_ring(value, max, label) ui_rings([(label, value)]) ui_gallery(urls) ui_collapse(title, html) ui_copy(text) ui_row(left, right)
         ui_bars([(label, value[, color])], max_value, color, unit) ui_table(headers, rows)  (header click sorts)
         ui_footer(left, right) svg_radar(labels, values, max_value) svg_line(values, labels) svg_donut([(label, value)])
         ui_empty(title, text, emoji) | ui_error(title, message)  <- complete error card, return it directly
         ui_response(page, llm_context="")  <- RETURN THIS from the tool method
  events await emit_status(em, text, done=False) | emit_notify(em, text, level) | emit_cite(em, title, url, snippet) | emit_followups(em, [..])   (em = __event_emitter__)
  http   await http_json(url, params, headers, timeout, retries, ttl) | await gather_limited([coros], limit)
  llm    await llm_complete(__request__, __user__, prompt, model=(__model__ or {}).get("id", ""), max_tokens=100)  -> "" on failure, keep a fallback
  store  store_load(name, user_id, default) | store_save(name, user_id, data)

VERIFY - save_tool calls every public method once with sample arguments. Pin real arguments with comment lines anywhere in the file:
       # test: show_country(name="Japan")
  A method fails the check if it raises, returns text starting with "Error", or returns an un-awaited coroutine. An error card is reported as a
  note (a sample input may legitimately be "not found"). Use `# test: none` to skip.

EXAMPLE 1 - card tool
"""
title: Country Card
description: Show any country as a tabbed visual card.
author: me
version: 1.0.0
requirements: httpx
"""
from pydantic import BaseModel, Field

# ==== kit:ui begin ====
import html as _html
import math
import re as _re
from fastapi.responses import HTMLResponse

PALETTES = {"violet": "#8b5cf6", "blue": "#3b82f6", "green": "#22c55e", "orange": "#f97316",
            "pink": "#ec4899", "teal": "#14b8a6", "red": "#ef4444", "gold": "#eab308"}
DONUT_COLORS = ["#8b5cf6", "#22c55e", "#f59e0b", "#ef4444", "#3b82f6", "#ec4899", "#14b8a6", "#eab308"]


class Raw(str):
    """Marks already-safe HTML so esc() leaves it alone."""


def esc(v) -> str:
    """HTML-escape any value (None becomes an em dash). Raw(...) is passed through."""
    if isinstance(v, Raw):
        return str(v)
    return _html.escape("—" if v is None else str(v))


def _hex(c, default="#8b5cf6") -> str:
    c = PALETTES.get(str(c or "").lower(), c or "")
    return c if _re.fullmatch(r"#[0-9a-fA-F]{6}", str(c)) else default


_UI_CSS = """
:root{--a:__A__;--b:__B__;--fg:#fff;--mute:rgba(255,255,255,.55);--ln:rgba(255,255,255,.1)}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent;font-family:'Nunito',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:8px;color:#e8e8f0}
.card{max-width:700px;margin:0 auto;border-radius:24px;overflow:hidden;background:#0d0d14;box-shadow:0 0 0 1px rgba(255,255,255,.06),0 20px 50px rgba(0,0,0,.6),0 0 70px __A__22}
.banner{position:relative;padding:26px;background:linear-gradient(135deg,__A__cc,__B__88 60%,__A__44);display:flex;align-items:center;justify-content:space-between;gap:16px;overflow:hidden}
.banner::after{content:'';position:absolute;top:-90px;right:-70px;width:300px;height:300px;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.12),transparent 70%);pointer-events:none}
.btx{position:relative;z-index:1}
.kicker{font:700 .75rem 'Space Mono',ui-monospace,monospace;letter-spacing:1px;color:rgba(255,255,255,.65)}
.title{font-size:2.3rem;font-weight:900;letter-spacing:-1px;color:#fff;line-height:1.05;text-shadow:0 2px 18px rgba(0,0,0,.35);margin:4px 0 6px}
.sub{font-size:.85rem;color:rgba(255,255,255,.75);font-weight:600;margin-bottom:10px}
.badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{padding:4px 12px;border-radius:999px;font-size:.68rem;font-weight:800;letter-spacing:.8px;text-transform:uppercase;color:#fff;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.28)}
.hero{position:relative;z-index:1;font-size:4rem;line-height:1;filter:drop-shadow(0 6px 20px rgba(0,0,0,.4));animation:float 4s ease-in-out infinite}
.tabs{display:flex;gap:2px;padding:0 16px;background:rgba(0,0,0,.28);border-bottom:1px solid rgba(255,255,255,.06);overflow-x:auto}
.tab{padding:12px 16px;font:800 .72rem 'Nunito',sans-serif;letter-spacing:.8px;text-transform:uppercase;color:rgba(255,255,255,.4);background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap}
.tab:hover{color:rgba(255,255,255,.75)}
.tab.on{color:#fff;border-bottom-color:var(--a)}
.pane{display:none}.pane.on{display:block}
.body{padding:22px 26px;display:flex;flex-direction:column;gap:18px}
.row{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.grow{flex:1;min-width:220px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tile{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:11px 14px}
.tile .l{font-size:.6rem;text-transform:uppercase;letter-spacing:.8px;color:rgba(255,255,255,.4);font-weight:700;margin-bottom:3px}
.tile .v{font-size:.95rem;font-weight:800;color:#f2f2ff;word-break:break-word}
.sec{display:flex;align-items:center;gap:8px;font-size:.65rem;text-transform:uppercase;letter-spacing:1.5px;font-weight:900;color:var(--a)}
.sec::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,__A__55,transparent)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:6px 13px;font-size:.78rem;font-weight:700;color:#d6d6ee}
.bar{display:grid;grid-template-columns:110px 1fr 56px;align-items:center;gap:10px;margin-bottom:8px;font-size:.78rem}
.bn{color:rgba(255,255,255,.55);font-weight:700;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trk{height:8px;background:rgba(255,255,255,.07);border-radius:9px;overflow:hidden}
.fil{height:100%;width:0;border-radius:9px;animation:grow 1s cubic-bezier(.22,1,.36,1) .15s forwards}
.bv{font:700 .75rem 'Space Mono',ui-monospace,monospace;color:#fff}
.note{background:linear-gradient(135deg,__A__16,rgba(255,255,255,.03));border:1px solid __A__44;border-radius:14px;padding:14px 18px;font-size:.88rem;line-height:1.7;color:rgba(255,255,255,.78);font-weight:600}
.scroll{overflow-x:auto}
.tb{width:100%;border-collapse:collapse;font-size:.78rem}
.tb th{font-size:.58rem;text-transform:uppercase;letter-spacing:.8px;color:rgba(255,255,255,.35);font-weight:800;padding:6px 8px;text-align:left;border-bottom:1px solid rgba(255,255,255,.08)}
.tb td{padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.04);color:rgba(255,255,255,.8)}
.tb tr:hover td{background:rgba(255,255,255,.03)}
.donut{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.legend div{font-size:.78rem;font-weight:700;color:rgba(255,255,255,.7);margin:4px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px}
.foot{display:flex;justify-content:space-between;gap:10px;padding:11px 26px;background:rgba(0,0,0,.3);font:600 .62rem 'Space Mono',ui-monospace,monospace;color:rgba(255,255,255,.28)}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes grow{to{width:var(--w)}}
.tb th[data-sort]{cursor:pointer}.tb th[data-sort]:hover{color:var(--a)}
.big{font-size:3.2rem;font-weight:900;color:var(--fg);line-height:1;letter-spacing:-1px}.big small{font-size:1.1rem;color:var(--mute);font-weight:700;margin-left:4px}
.lbl{font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--mute);font-weight:800;margin-top:6px}
.dl{display:inline-block;margin-top:8px;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:800}
.dl.up{color:#22c55e;background:#22c55e22}.dl.dn{color:#ef4444;background:#ef444422}
.tl{border-left:2px solid var(--ln);margin-left:6px;padding-left:18px}
.tl .it{position:relative;margin-bottom:16px}.tl .it::before{content:'';position:absolute;left:-25px;top:4px;width:10px;height:10px;border-radius:50%;background:var(--a);box-shadow:0 0 0 3px __A__33}
.tl .tt{font-weight:800;font-size:.9rem;color:var(--fg)}.tl .tx{font-size:.8rem;color:var(--mute);line-height:1.5;margin-top:2px}.tl .wn{font:700 .65rem 'Space Mono',ui-monospace,monospace;color:var(--a)}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:12px}.cmp>div{background:rgba(127,127,127,.07);border:1px solid var(--ln);border-radius:14px;padding:12px 14px}
.cmp h4{font-size:.9rem;font-weight:900;color:var(--a);margin-bottom:8px}.cmp p{display:flex;justify-content:space-between;gap:8px;font-size:.78rem;padding:4px 0;border-bottom:1px solid var(--ln);color:var(--mute)}.cmp p b{color:var(--fg)}
.rings{display:flex;gap:18px;flex-wrap:wrap}.ring{text-align:center}.ring .lbl{margin-top:2px}
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}.gal img{width:100%;height:110px;object-fit:cover;border-radius:12px;border:1px solid var(--ln)}
.empty{text-align:center;padding:30px 10px}.empty .em{font-size:2.6rem}.empty .t{font-weight:900;font-size:1.05rem;color:var(--fg);margin-top:8px}.empty .x{font-size:.85rem;color:var(--mute);margin-top:4px}
details.col{border:1px solid var(--ln);border-radius:14px;padding:10px 14px}details.col summary{cursor:pointer;font-weight:800;font-size:.85rem;color:var(--fg)}details.col[open] summary{margin-bottom:10px}
.cp{background:rgba(127,127,127,.12);border:1px solid var(--ln);color:var(--fg);border-radius:10px;padding:5px 12px;font:800 .72rem 'Nunito',sans-serif;cursor:pointer}.cp:hover{border-color:var(--a)}
@media(max-width:520px){.cmp{grid-template-columns:1fr}.title{font-size:1.8rem}.banner{flex-direction:column;align-items:flex-start}.bar{grid-template-columns:80px 1fr 48px}.body{padding:18px}}
"""

_UI_LIGHT = """
:root{--fg:#15151f;--mute:rgba(0,0,0,.55);--ln:rgba(0,0,0,.1)}
html,body{color:#15151f}
.card{background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.08),0 14px 36px rgba(0,0,0,.12)}
.tabs{background:rgba(0,0,0,.04);border-bottom-color:rgba(0,0,0,.08)}.tab{color:rgba(0,0,0,.45)}.tab:hover{color:rgba(0,0,0,.8)}.tab.on{color:#111}
.tile{background:rgba(0,0,0,.03);border-color:rgba(0,0,0,.08)}.tile .l{color:rgba(0,0,0,.5)}.tile .v{color:#111}
.chip{background:rgba(0,0,0,.05);border-color:rgba(0,0,0,.1);color:#333}
.bn{color:rgba(0,0,0,.6)}.trk{background:rgba(0,0,0,.08)}.bv{color:#111}.note{color:rgba(0,0,0,.75)}
.tb th{color:rgba(0,0,0,.5);border-bottom-color:rgba(0,0,0,.12)}.tb td{color:rgba(0,0,0,.8);border-bottom-color:rgba(0,0,0,.06)}.tb tr:hover td{background:rgba(0,0,0,.03)}
.legend div{color:rgba(0,0,0,.7)}.foot{background:rgba(0,0,0,.04);color:rgba(0,0,0,.45)}
"""

_UI_JS = """
document.addEventListener('click',function(e){
var b=e.target.closest('[data-tab]');
if(b){var r=b.closest('.card');
r.querySelectorAll('[data-tab]').forEach(function(x){x.classList.toggle('on',x===b)});
r.querySelectorAll('[data-pane]').forEach(function(p){p.classList.toggle('on',p.getAttribute('data-pane')===b.getAttribute('data-tab'))});rh();return;}
var h=e.target.closest('th[data-sort]');
if(h){var t=h.closest('table'),i=Array.prototype.indexOf.call(h.parentNode.children,h),d=h.getAttribute('data-dir')==='a'?-1:1;h.setAttribute('data-dir',d===1?'a':'d');
var rows=Array.prototype.slice.call(t.tBodies[0].rows);
rows.sort(function(x,y){var a=x.cells[i].textContent.trim(),c=y.cells[i].textContent.trim(),n=parseFloat(a.replace(/[^0-9.\\-]/g,'')),m=parseFloat(c.replace(/[^0-9.\\-]/g,''));
return (isNaN(n)||isNaN(m)?a.localeCompare(c):n-m)*d});
rows.forEach(function(r){t.tBodies[0].appendChild(r)});return;}
var c=e.target.closest('[data-copy]');
if(c){var v=c.getAttribute('data-copy'),o=c.textContent;
function ok(){c.textContent='Copied';setTimeout(function(){c.textContent=o},1200)}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(v).then(ok,ok)}else{var a=document.createElement('textarea');a.value=v;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(x){}a.remove();ok()}}
});
function rh(){try{parent.postMessage({type:'iframe:height',height:document.documentElement.scrollHeight},'*')}catch(e){}}
window.addEventListener('load',rh);document.addEventListener('toggle',rh,true);
if(typeof ResizeObserver!=='undefined'){new ResizeObserver(rh).observe(document.body)}
"""


def ui_page(body, accent="violet", accent2="", title="", fonts=True, theme="dark") -> str:
    """Wrap card content into a complete HTML document. accent = palette name or #rrggbb. theme = dark | light | auto (follows the system)."""
    a = _hex(accent)
    b = _hex(accent2, a)
    css = _UI_CSS.replace("__A__", a).replace("__B__", b)
    if theme == "light":
        css += _UI_LIGHT
    elif theme == "auto":
        css += "@media (prefers-color-scheme: light){" + _UI_LIGHT + "}"
    font = ('<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;700;800;900'
            '&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">') if fonts else ""
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            + font + "<title>" + esc(title) + "</title><style>" + css + "</style></head><body>"
            + '<div class="card">' + body + "</div><script>" + _UI_JS + "</script></body></html>")


def ui_banner(title, subtitle="", badges=(), emoji="", kicker="") -> str:
    """Gradient header: kicker (small mono line), big title, subtitle, badges, big hero emoji."""
    chips = "".join('<span class="badge">' + esc(x) + "</span>" for x in badges if x)
    return ('<div class="banner"><div class="btx">'
            + ('<div class="kicker">' + esc(kicker) + "</div>" if kicker else "")
            + '<div class="title">' + esc(title) + "</div>"
            + ('<div class="sub">' + esc(subtitle) + "</div>" if subtitle else "")
            + '<div class="badges">' + chips + "</div></div>"
            + ('<div class="hero">' + esc(emoji) + "</div>" if emoji else "") + "</div>")


def ui_body(*parts) -> str:
    """Padded content area (use when you do not need tabs)."""
    return '<div class="body">' + "".join(parts) + "</div>"


def ui_tabs(panes: dict) -> str:
    """Tab bar + panes. panes = {"Overview": html, "Details": html}. First tab active, JS built in."""
    keys = list(panes)
    bar = "".join('<button class="tab' + (" on" if i == 0 else "") + '" data-tab="' + esc(k) + '">' + esc(k) + "</button>"
                  for i, k in enumerate(keys))
    body = "".join('<div class="pane' + (" on" if i == 0 else "") + '" data-pane="' + esc(k)
                   + '"><div class="body">' + panes[k] + "</div></div>" for i, k in enumerate(keys))
    return '<div class="tabs">' + bar + "</div>" + body


def ui_section(title) -> str:
    return '<div class="sec">' + esc(title) + "</div>"


def ui_tiles(pairs) -> str:
    """Grid of label/value stat tiles. pairs = [("Height", "1.7 m"), ...]."""
    return '<div class="tiles">' + "".join(
        '<div class="tile"><div class="l">' + esc(l) + '</div><div class="v">' + esc(v) + "</div></div>"
        for l, v in pairs) + "</div>"


def ui_badge(text, color="#8b5cf6") -> Raw:
    c = _hex(color)
    return Raw('<span class="chip" style="background:' + c + "22;color:" + c + ";border-color:" + c + '55">'
               + esc(text) + "</span>")


def ui_chips(items, empty="—") -> str:
    items = [i for i in (items or []) if i]
    inner = "".join('<span class="chip">' + esc(i) + "</span>" for i in items) or '<span class="chip">' + esc(empty) + "</span>"
    return '<div class="chips">' + inner + "</div>"


def ui_note(text) -> str:
    return '<div class="note">' + esc(text) + "</div>"


def ui_row(left, right="") -> str:
    """Two blocks side by side (wraps on mobile). Typical: bars left, svg_radar right."""
    return '<div class="row"><div class="grow">' + left + "</div>" + (("<div>" + right + "</div>") if right else "") + "</div>"


def ui_bars(rows, max_value=None, color="", unit="") -> str:
    """Animated horizontal bars. rows = [(label, value[, '#hex'])]. Default colour = accent."""
    rows = list(rows)
    vals = []
    for r in rows:
        try:
            vals.append(float(r[1]))
        except Exception:
            vals.append(0.0)
    mx = max_value or max(vals + [1.0])
    out = []
    for r, v in zip(rows, vals):
        col = _hex(r[2]) if len(r) > 2 else (_hex(color) if color else "var(--a)")
        pct = max(0.0, min(100.0, v / mx * 100)) if mx else 0.0
        shown = (f"{v:,.0f}" if abs(v) >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")) + unit
        out.append('<div class="bar"><span class="bn">' + esc(r[0]) + '</span><div class="trk"><div class="fil" style="--w:'
                   + ("%.1f" % pct) + "%;background:" + col + '"></div></div><span class="bv">' + esc(shown) + "</span></div>")
    return "".join(out)


def ui_table(headers, rows) -> str:
    """Table. Clicking a header sorts the column."""
    th = "".join('<th data-sort="1">' + esc(h) + "</th>" for h in headers)
    tr = "".join("<tr>" + "".join("<td>" + esc(c) + "</td>" for c in r) + "</tr>" for r in rows)
    return '<div class="scroll"><table class="tb"><thead><tr>' + th + "</tr></thead><tbody>" + tr + "</tbody></table></div>"


def ui_footer(left="", right="") -> str:
    return '<div class="foot"><span>' + esc(left) + "</span><span>" + esc(right) + "</span></div>"


def svg_radar(labels, values, max_value=100, color="", size=190) -> str:
    """Radar/spider chart. 3+ axes."""
    n = len(labels)
    c = size / 2.0
    r = size / 2.0 - 26
    ang = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
    col = _hex(color) if color else "var(--a)"

    def pt(f, a):
        return "%.1f,%.1f" % (c + r * f * math.cos(a), c - r * f * math.sin(a))

    grid = "".join('<polygon points="' + " ".join(pt(f, a) for a in ang) + '" fill="none" stroke="rgba(255,255,255,.09)"/>'
                   for f in (0.25, 0.5, 0.75, 1))
    axes = "".join('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="rgba(255,255,255,.09)"/>'
                   % (c, c, c + r * math.cos(a), c - r * math.sin(a)) for a in ang)
    fr = []
    for v in values:
        try:
            fr.append(max(0.0, min(1.0, float(v) / max_value)))
        except Exception:
            fr.append(0.0)
    poly = " ".join(pt(f, a) for f, a in zip(fr, ang))
    labs = "".join('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="8" font-weight="700" '
                   'fill="rgba(255,255,255,.55)" font-family="monospace">%s</text>'
                   % (c + (r + 14) * math.cos(a), c - (r + 14) * math.sin(a) + 3, esc(l)) for l, a in zip(labels, ang))
    return ('<svg viewBox="0 0 %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">' % (size, size, size, size)
            + grid + axes + '<polygon points="' + poly + '" style="fill:' + col + ";fill-opacity:.28;stroke:" + col
            + '" stroke-width="1.6" stroke-linejoin="round"/>' + labs + "</svg>")


def svg_line(values, labels=None, color="", w=460, h=140) -> str:
    """Line/area chart with dots. Needs 2+ numeric values."""
    vals = []
    for v in values:
        try:
            vals.append(float(v))
        except Exception:
            pass
    if len(vals) < 2:
        return ""
    col = _hex(color) if color else "var(--a)"
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pad = 16
    xs = [pad + i * (w - 2 * pad) / (len(vals) - 1) for i in range(len(vals))]
    ys = [h - pad - 10 - (v - lo) / span * (h - 2 * pad - 10) for v in vals]
    pts = " ".join("%.1f,%.1f" % p for p in zip(xs, ys))
    area = "%.1f,%.1f " % (xs[0], h - pad - 10) + pts + " %.1f,%.1f" % (xs[-1], h - pad - 10)
    dots = "".join('<circle cx="%.1f" cy="%.1f" r="2.6" style="fill:%s"/>' % (x, y, col) for x, y in zip(xs, ys))
    txt = ""
    if labels:
        step = max(1, int(math.ceil(len(vals) / 6.0)))
        for i in range(0, len(vals), step):
            if i < len(labels):
                txt += ('<text x="%.1f" y="%d" text-anchor="middle" font-size="8" fill="rgba(255,255,255,.45)" '
                        'font-family="monospace">%s</text>' % (xs[i], h - 2, esc(labels[i])))
    return ('<svg viewBox="0 0 %d %d" width="100%%" xmlns="http://www.w3.org/2000/svg">' % (w, h)
            + '<polygon points="' + area + '" style="fill:' + col + ';fill-opacity:.15"/>'
            + '<polyline points="' + pts + '" fill="none" style="stroke:' + col + '" stroke-width="2" stroke-linejoin="round"/>'
            + dots + txt + "</svg>")


def svg_donut(parts, size=150) -> str:
    """Donut chart with legend. parts = [(label, value[, '#hex'])]."""
    vals = []
    for p in parts:
        try:
            vals.append(max(0.0, float(p[1])))
        except Exception:
            vals.append(0.0)
    tot = sum(vals) or 1.0
    c = size / 2.0
    r = size / 2.0 - 12
    circ = 2 * math.pi * r
    off = 0.0
    segs, legend = "", ""
    for i, (p, v) in enumerate(zip(parts, vals)):
        col = _hex(p[2]) if len(p) > 2 else DONUT_COLORS[i % len(DONUT_COLORS)]
        ln = v / tot * circ
        segs += ('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="16" '
                 'stroke-dasharray="%.2f %.2f" stroke-dashoffset="%.2f" transform="rotate(-90 %.1f %.1f)"/>'
                 % (c, c, r, col, ln, circ - ln, -off, c, c))
        off += ln
        legend += '<div><i style="background:' + col + '"></i>' + esc(p[0]) + " · " + ("%.0f%%" % (v / tot * 100)) + "</div>"
    svg = ('<svg viewBox="0 0 %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">' % (size, size, size, size)
           + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="16"/>' % (c, c, r)
           + segs + "</svg>")
    return '<div class="donut">' + svg + '<div class="legend">' + legend + "</div></div>"


def _safe_url(u) -> str:
    u = str(u or "").strip()
    return u if _re.match(r"https?://", u) else ""


def ui_stat_hero(value, label="", delta=None, unit="") -> str:
    """One big headline number with label and optional trend chip. delta is text like "+2.4%" or "-3" (a leading - or down arrow shows red)."""
    chip = ""
    if delta not in (None, ""):
        d = str(delta).strip()
        chip = '<div class="dl ' + ("dn" if d.startswith(("-", "▼")) else "up") + '">' + esc(d) + "</div>"
    return ('<div><div class="big">' + esc(value) + ("<small>" + esc(unit) + "</small>" if unit else "") + "</div>"
            + ('<div class="lbl">' + esc(label) + "</div>" if label else "") + chip + "</div>")


def ui_timeline(items) -> str:
    """Vertical timeline. items = [(title, text[, when])]."""
    out = ""
    for it in items:
        out += ('<div class="it">' + ('<div class="wn">' + esc(it[2]) + "</div>" if len(it) > 2 and it[2] else "")
                + '<div class="tt">' + esc(it[0]) + "</div>"
                + ('<div class="tx">' + esc(it[1]) + "</div>" if len(it) > 1 and it[1] else "") + "</div>")
    return '<div class="tl">' + out + "</div>"


def ui_compare(left, right) -> str:
    """Two items side by side. left/right = (title, [(label, value), ...])."""
    def col(x):
        return "<div><h4>" + esc(x[0]) + "</h4>" + "".join("<p><span>" + esc(l) + "</span><b>" + esc(v) + "</b></p>" for l, v in x[1]) + "</div>"
    return '<div class="cmp">' + col(left) + col(right) + "</div>"


def ui_ring(value, max_value=100, label="", color="", size=104) -> str:
    """Circular progress ring with the value in the middle. Put several in ui_row or call ui_rings."""
    try:
        f = max(0.0, min(1.0, float(value) / float(max_value)))
    except Exception:
        f = 0.0
    col = _hex(color) if color else "var(--a)"
    r = size / 2.0 - 9
    circ = 2 * math.pi * r
    c = size / 2.0
    svg = ('<svg viewBox="0 0 %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">' % (size, size, size, size)
           + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="rgba(127,127,127,.2)" stroke-width="8"/>' % (c, c, r)
           + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" style="stroke:%s" stroke-width="8" stroke-linecap="round" '
             'stroke-dasharray="%.2f %.2f" transform="rotate(-90 %.1f %.1f)"/>' % (c, c, r, col, f * circ, circ, c, c)
           + '<text x="%.1f" y="%.1f" text-anchor="middle" font-size="%d" font-weight="900" style="fill:var(--fg)" font-family="sans-serif">%s</text></svg>'
           % (c, c + 5, size // 5, esc(value)))
    return '<div class="ring">' + svg + ('<div class="lbl">' + esc(label) + "</div>" if label else "") + "</div>"


def ui_rings(items, max_value=100) -> str:
    """Row of progress rings. items = [(label, value[, '#hex'])]."""
    return '<div class="rings">' + "".join(ui_ring(i[1], max_value, i[0], i[2] if len(i) > 2 else "") for i in items) + "</div>"


def ui_gallery(urls) -> str:
    """Image grid (http/https only, broken images hide themselves)."""
    imgs = "".join('<img src="' + esc(_safe_url(u)) + '" loading="lazy" onerror="this.style.display=\'none\'" alt="">' for u in urls if _safe_url(u))
    return '<div class="gal">' + imgs + "</div>" if imgs else ""


def ui_empty(title="Nothing found", text="", emoji="🔍") -> str:
    """Designed empty state for no-results cases."""
    return ('<div class="empty"><div class="em">' + esc(emoji) + '</div><div class="t">' + esc(title) + "</div>"
            + ('<div class="x">' + esc(text) + "</div>" if text else "") + "</div>")


def ui_collapse(title, content_html, open=False) -> str:
    """Collapsible section for long details. content_html must already be safe HTML (built with ui_* helpers)."""
    return '<details class="col"' + (" open" if open else "") + "><summary>" + esc(title) + "</summary>" + content_html + "</details>"


def ui_copy(text, label="Copy") -> str:
    """Copy-to-clipboard button."""
    return '<button class="cp" data-copy="' + esc(text) + '">' + esc(label) + "</button>"


def ui_error(title, message="", emoji="⚠️", accent="red"):
    """A complete friendly error card. Return it directly from the tool method instead of a bare error string."""
    body = "<!--ui-error-->" + ui_banner(title, "", emoji=emoji) + ui_body(ui_note(message) if message else ui_empty("Something went wrong"))
    return ui_response(ui_page(body, accent=accent, title=title))


def ui_response(page, llm_context=""):
    """Return the card to Open WebUI. llm_context (optional) gives the LLM a text summary of what is shown."""
    resp = HTMLResponse(content=page, headers={"content-disposition": "inline"})
    return (resp, llm_context) if llm_context else resp
# ==== kit:ui end ====
# ==== kit:http begin ====
import asyncio
import time as _time
import httpx

_CACHE = {}


async def http_json(url, params=None, headers=None, timeout=15, retries=2, ttl=0):
    """GET -> parsed JSON. Retries timeouts/5xx, 4xx raises httpx.HTTPStatusError. ttl>0 caches in memory (seconds)."""
    key = url + "|" + repr(sorted((params or {}).items()))
    if ttl:
        hit = _CACHE.get(key)
        if hit and _time.time() - hit[0] < ttl:
            return hit[1]
    last = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as c:
        for i in range(retries + 1):
            try:
                r = await c.get(url, params=params)
                if r.status_code < 500:
                    r.raise_for_status()
                    data = r.json()
                    if ttl:
                        if len(_CACHE) > 200:
                            _CACHE.clear()
                        _CACHE[key] = (_time.time(), data)
                    return data
                last = httpx.HTTPStatusError("HTTP %s" % r.status_code, request=r.request, response=r)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
            await asyncio.sleep(0.6 * (i + 1))
    raise last


async def gather_limited(coros, limit=6):
    """Run coroutines in parallel (max `limit` at once). Results in order; failures come back as Exception objects."""
    sem = asyncio.Semaphore(limit)

    async def _run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(_run(c) for c in coros), return_exceptions=True)
# ==== kit:http end ====
# ==== kit:events begin ====
from datetime import datetime as _dt


async def emit_status(em, text, done=False):
    """Live progress line above the answer. Call before slow steps, finish with done=True."""
    if em:
        try:
            await em({"type": "status", "data": {"description": text, "done": done}})
        except Exception:
            pass


async def emit_notify(em, text, level="success"):
    """Toast notification. level: info | success | warning | error."""
    if em:
        try:
            await em({"type": "notification", "data": {"type": level, "content": text}})
        except Exception:
            pass


async def emit_followups(em, suggestions):
    """Clickable follow-up suggestions under the answer, e.g. ["Compare with France", "Show another"]."""
    if em:
        try:
            await em({"type": "chat:message:follow_ups", "data": {"follow_ups": list(suggestions)[:4]}})
        except Exception:
            pass


async def emit_cite(em, title, url, snippet=""):
    """Source chip under the answer."""
    if em:
        try:
            await em({"type": "citation", "data": {
                "document": [snippet or title],
                "metadata": [{"date_accessed": _dt.now().isoformat(), "source": title, "url": url}],
                "source": {"name": title, "url": url}}})
        except Exception:
            pass
# ==== kit:events end ====

# test: show_country(name="Japan")


class Tools:
    class Valves(BaseModel):
        TIMEOUT: int = Field(default=15, ge=3, le=60, description="HTTP timeout in seconds")
        CACHE_TTL: int = Field(default=3600, ge=0, le=86400, description="Seconds to cache answers (0 = off)")
        ACCENT: str = Field(default="teal", description="Card accent: violet, blue, green, orange, pink, teal, red, gold or #rrggbb")

    def __init__(self):
        self.valves = self.Valves()

    async def show_country(self, name: str, __event_emitter__=None) -> "HTMLResponse | str":
        """
        Show a country as a visual card (capital, population, region, languages).
        Use when the user asks about one country. Do not use for cities or for comparing many countries.
        The card is displayed to the user automatically, so reply with at most one short sentence.
        :param name: Country name given by the user, e.g. "Japan"
        """
        em = __event_emitter__
        try:
            await emit_status(em, "Looking up " + name + "...")
            data = await http_json("https://restcountries.com/v3.1/name/" + name.strip(),
                                   params={"fields": "name,capital,population,region,flag,languages"},
                                   timeout=self.valves.TIMEOUT, ttl=self.valves.CACHE_TTL)
            c = data[0]
            common = c["name"]["common"]
            pop = c.get("population", 0)
            capital = ", ".join(c.get("capital") or []) or None
            langs = list((c.get("languages") or {}).values())
            overview = (ui_stat_hero(f"{pop / 1e6:.1f}", "Population", unit="M")
                        + ui_tiles([("Capital", capital), ("Region", c.get("region"))]))
            people = (ui_section("Languages") + ui_chips(langs)) if langs else ui_empty("No language data")
            body = (ui_banner(common, c["name"].get("official", ""), badges=[c.get("region")], emoji=c.get("flag", ""))
                    + ui_tabs({"Overview": overview, "People": people}) + ui_footer("Country Card", "restcountries.com"))
            await emit_cite(em, "REST Countries", "https://restcountries.com")
            await emit_followups(em, ["Compare it with another country", "Show a different country"])
            await emit_status(em, "Done", True)
            return ui_response(ui_page(body, accent=self.valves.ACCENT, title=common),
                               llm_context=f"{common}: capital {capital}, population {pop:,}, languages {', '.join(langs)}.")
        except httpx.HTTPStatusError:
            return ui_error("Country not found", "No country matches \\"" + name + "\\". Check the spelling.")
        except Exception as e:
            return ui_error("Lookup failed", str(e))

EXAMPLE 2 - text tool (no card needed)
"""
title: Unit Converter
description: Convert lengths and weights between common units.
author: me
version: 1.0.0
"""
from pydantic import BaseModel, Field

# test: convert_units(value=5, from_unit="km", to_unit="mi")

_UNITS = {"m": 1.0, "km": 1000.0, "mi": 1609.344, "ft": 0.3048, "kg": 1.0, "g": 0.001, "lb": 0.45359237}


class Tools:
    class Valves(BaseModel):
        PRECISION: int = Field(default=4, ge=0, le=10, description="Decimal places in results")

    def __init__(self):
        self.valves = self.Valves()

    async def convert_units(self, value: float, from_unit: str, to_unit: str) -> str:
        """
        Convert a number between length (m, km, mi, ft) or weight (kg, g, lb) units.
        Use when the user asks to convert units. Do not use for currencies or temperatures.
        :param value: The number to convert
        :param from_unit: Source unit, e.g. "km"
        :param to_unit: Target unit, e.g. "mi"
        """
        a, b = _UNITS.get(from_unit.lower()), _UNITS.get(to_unit.lower())
        if a is None or b is None:
            return "Unknown unit. Supported: " + ", ".join(_UNITS)
        return f"{value:g} {from_unit} = {round(value * a / b, self.valves.PRECISION):g} {to_unit}"
'''

# ==========================================================================
# helpers (module level, no state)
# ==========================================================================

_HDR = re.compile(r"""\A\s*("{3}|'{3})(.*?)\1""", re.S)
_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)
_KIT_MARKER = re.compile(r"^[ \t]*#\s*@include\s+([a-z_, \t]+?)[ \t]*$", re.M)
_KIT_BLOCK = re.compile(
    r"^# ==== kit:(\w+) begin ====\n.*?^# ==== kit:\1 end ====\n?", re.S | re.M
)
_PATCH = re.compile(
    r"<<<<<<<[ \t]*SEARCH[ \t]*\r?\n(.*?)\r?\n?={7}[ \t]*\r?\n(.*?)\r?\n?>{7}[ \t]*REPLACE[ \t]*\r?",
    re.S,
)
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9\-]{20,})"
)
_SPECIAL = {
    "self", "__user__", "__request__", "__event_emitter__", "__event_call__",
    "__metadata__", "__messages__", "__files__", "__model__", "__id__", "__oauth_token__",
}  # fmt: skip


def _clean(code: str) -> str:
    code = (code or "").strip()
    if code.startswith("```"):
        m = _FENCE.search(code + ("" if code.endswith("```") else "\n```"))
        if m:
            code = m.group(1)
    return code.strip() + "\n"


_UESC = re.compile(r"(?<!\\)\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8}))")


def _unescape_unicode(code: str) -> str:
    """Turn literal \\u00e9 / \\U0001F4A1 sequences the LLM sometimes emits into real characters (so the header title reads Pokédex).
    Only printable non-ASCII is converted, and only if the result still parses."""

    def one(m):
        cp = int(m.group(1) or m.group(2), 16)
        if (
            cp < 0xA0
            or 0xD800 <= cp <= 0xDFFF
            or cp in (0x2028, 0x2029)
            or cp > 0x10FFFF
        ):
            return m.group(0)
        return chr(cp)

    out = _UESC.sub(one, code)
    if out == code:
        return code
    try:
        ast.parse(out)
        return out
    except SyntaxError:
        return code


def _code_from_messages(messages) -> str:
    """Newest fenced block that contains `class Tools`."""
    for m in reversed(messages or []):
        c = (m or {}).get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        for blk in reversed(_FENCE.findall(c or "")):
            if "class Tools" in blk:
                return blk
    return ""


def _header(code: str) -> dict:
    m = _HDR.match(code)
    out = {}
    if m:
        for line in m.group(2).splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip().isidentifier():
                out[k.strip().lower()] = v.strip()
    return out


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def _expand_kits(code: str) -> tuple:
    """Inline `# @include a, b` markers. Returns (code, error_or_None)."""
    errors = []
    present = set(re.findall(r"^# ==== kit:(\w+) begin ====$", code, re.M))

    def repl(m):
        out = []
        for n in [x.strip().lower() for x in m.group(1).split(",") if x.strip()]:
            if n not in KITS:
                errors.append(f"unknown kit '{n}' (available: {', '.join(KITS)})")
            elif n not in present:
                present.add(n)
                out.append(KITS[n].rstrip("\n"))
        return "\n".join(out)

    code = _KIT_MARKER.sub(repl, code)
    return code, ("; ".join(errors) if errors else None)


def _collapse_kits(code: str) -> str:
    return _KIT_BLOCK.sub(lambda m: f"# @include {m.group(1)}\n", code or "")


def _bump(new: str, old: str) -> str:
    def ver(c):
        m = re.search(r"^\s*version:\s*(\d+)\.(\d+)\.(\d+)", c or "", re.M)
        return m.groups() if m else None

    o, n = ver(old), ver(new)
    if not o or o != n:
        return new
    return re.sub(
        r"^(\s*version:\s*)\d+\.\d+\.\d+",
        rf"\g<1>{o[0]}.{o[1]}.{int(o[2]) + 1}",
        new,
        count=1,
        flags=re.M,
    )


def _public(code: str) -> list:
    try:
        cls = next(
            n
            for n in ast.parse(code).body
            if isinstance(n, ast.ClassDef) and n.name == "Tools"
        )
    except (SyntaxError, StopIteration):
        return []
    return [
        n.name
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not n.name.startswith("_")
    ]


def _valve_names(code: str) -> dict:
    out = {"Valves": [], "UserValves": []}
    try:
        cls = next(
            n
            for n in ast.parse(code).body
            if isinstance(n, ast.ClassDef) and n.name == "Tools"
        )
    except (SyntaxError, StopIteration):
        return out
    for n in cls.body:
        if isinstance(n, ast.ClassDef) and n.name in out:
            out[n.name] = [
                b.target.id
                for b in n.body
                if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name)
            ]
    return out


def _apply_patch(src: str, patch: str) -> tuple:
    """Apply SEARCH/REPLACE blocks. Returns (new_src, error_or_None)."""
    blocks = _PATCH.findall(patch or "")
    if not blocks:
        return (
            src,
            "No SEARCH/REPLACE blocks found. Use:\n<<<<<<< SEARCH\nold lines\n=======\nnew lines\n>>>>>>> REPLACE",
        )
    for i, (old, new) in enumerate(blocks, 1):
        if not old.strip():
            return src, f"Block {i}: SEARCH is empty."
        if src.count(old) == 1:
            src = src.replace(old, new, 1)
            continue
        lines, want = src.split("\n"), [x.rstrip() for x in old.split("\n")]
        norm = [x.rstrip() for x in lines]
        hits = [
            j
            for j in range(len(norm) - len(want) + 1)
            if norm[j : j + len(want)] == want
        ]
        if len(hits) == 1:
            j = hits[0]
            src = "\n".join(lines[:j] + new.split("\n") + lines[j + len(want) :])
        elif not hits:
            return (
                src,
                f"Block {i}: SEARCH text not found. Call read_tool and copy the lines exactly.",
            )
        else:
            return (
                src,
                f"Block {i}: SEARCH matches {len(hits)} places. Add more surrounding lines.",
            )
    return src, None


def _lint_code(code: str) -> list:
    """Non-blocking warnings."""
    out = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out
    cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Tools"),
        None,
    )
    if cls is None:
        return out
    for n in cls.body:
        if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and not n.name.startswith("_"):
            doc = ast.get_docstring(n)
            if not doc:
                out.append(
                    f"`{n.name}` has no docstring: the LLM won't know when to use it."
                )
            for a in n.args.args + n.args.kwonlyargs:
                if a.arg in _SPECIAL:
                    continue
                if a.annotation is None:
                    out.append(f"`{n.name}({a.arg})` needs a type hint.")
                if doc and f":param {a.arg}:" not in doc:
                    out.append(f"`{n.name}`: add `:param {a.arg}:` to the docstring.")
        if isinstance(n, ast.ClassDef) and n.name in ("Valves", "UserValves"):
            for b in n.body:
                if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                    v = b.value
                    if not (
                        isinstance(v, ast.Call)
                        and any(k.arg == "description" for k in v.keywords)
                    ):
                        out.append(
                            f"`{n.name}.{b.target.id}` has no Field(description=...)."
                        )
    if _SECRET.search(code):
        out.append("Looks like a hardcoded secret/API key: move it to a Valves field.")
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in ("eval", "exec", "__import__"):
                out.append(f"Risky call `{f.id}()` at line {n.lineno}.")
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                if (
                    f.value.id in ("httpx", "requests")
                    and f.attr in ("get", "post", "put", "delete", "request")
                    and not any(k.arg == "timeout" for k in n.keywords)
                ):
                    out.append(
                        f"`{f.value.id}.{f.attr}()` at line {n.lineno} has no timeout."
                    )
                if f.value.id == "os" and f.attr in ("system", "popen"):
                    out.append(f"Risky call `os.{f.attr}()` at line {n.lineno}.")
                if f.value.id == "subprocess":
                    out.append(
                        f"Risky call `subprocess.{f.attr}()` at line {n.lineno}."
                    )
        if isinstance(n, ast.AsyncFunctionDef):
            for c in ast.walk(n):
                if (
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name)
                    and c.func.value.id == "requests"
                ):
                    out.append(
                        f"Blocking `requests` call inside async `{n.name}`: use httpx.AsyncClient."
                    )
                    break
    return out[:8]


def _lint_html(html: str) -> list:
    t = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    out = []
    if len(html) < 80 or "</" not in html:
        out.append("card looks empty")
    if re.search(r">\s*(None|nan|NaN|undefined|null)\s*<", t):
        out.append("visible None/NaN text: show '—' or hide the block")
    if "{{" in t or re.search(r"\{[A-Za-z_]\w*\}", t):
        out.append("unformatted {placeholder} in markup")
    for tag in ("div", "span", "table"):
        if len(re.findall(rf"<{tag}\b", t, re.I)) != len(
            re.findall(rf"</{tag}>", t, re.I)
        ):
            out.append(f"unbalanced <{tag}>")
    return out


def _polish(code: str) -> tuple:
    """Advisory quality score. Returns (score 0-10, up to 5 suggestions). Never blocks a save."""
    c = _collapse_kits(code)
    low = c.lower()
    checks = []

    def add(ok, tip):
        checks.append((bool(ok), tip))

    add(
        re.search(r"use (this )?when|use this|when the user", low),
        "Docstrings: say WHEN to use each method and when NOT to ('Use when... Do not use for...').",
    )
    net = "http_json" in c or "httpx" in c or "requests." in c
    if net or "ui_page(" in c:
        add(
            "class Valves" in c,
            "Add a Valves class (TIMEOUT, CACHE_TTL, ACCENT...): never hardcode numbers, URLs or colours.",
        )
        add("emit_status" in c, "Add emit_status steps so the user sees progress.")
        add(
            re.search(r"\btry:", c) and "except" in c,
            "Wrap the body in try/except and return a friendly message or ui_error card.",
        )
    if net:
        add("emit_cite" in c, "Add emit_cite for every external data source.")
        add(
            re.search(r"ttl\s*=", c),
            "Cache stable API data: http_json(..., ttl=self.valves.CACHE_TTL).",
        )
    if "ui_page(" in c:
        add("ui_banner(" in c, "Open the card with ui_banner (identity + hero emoji).")
        add(
            "ui_tabs(" in c or c.count("ui_section(") >= 2,
            "Organise the card: ui_tabs for 2+ kinds of info, or ui_section blocks.",
        )
        add(
            re.search(r"svg_\w+\(|ui_bars\(|ui_rings?\(|ui_stat_hero\(", c),
            "Show numbers as visuals: ui_stat_hero, ui_bars, svg_radar, svg_line, svg_donut or ui_rings.",
        )
        add("ui_footer(" in c, "End the card with ui_footer naming the data source.")
        add(
            "llm_context" in c,
            "Pass llm_context= to ui_response so the LLM can discuss what the card shows.",
        )
        add(
            "displayed to the user automatically" in low,
            "Docstring must say: The card is displayed to the user automatically, so reply with at most one short sentence.",
        )
        add(
            "ui_error(" in c or "ui_empty(" in c,
            "Use ui_error for failures and ui_empty for no-result states instead of bare strings.",
        )
        add(
            "emit_followups" in c, "Add emit_followups with 2-3 natural next questions."
        )
    tips = [t for ok, t in checks if not ok]
    return round(10 * (len(checks) - len(tips)) / max(1, len(checks))), tips[:5]


def _load(code: str) -> tuple:
    """Execute the file in a throwaway module and build Tools(). Returns (instance, error, warning)."""
    name = "_tool_builder_dry_run"
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    try:
        exec(compile(code, "<string>", "exec"), mod.__dict__)
        cls = getattr(mod, "Tools", None)
        if cls is None:
            return None, "After executing the file there is no `Tools` class.", None
        return cls(), None, None
    except ModuleNotFoundError as e:
        return (
            None,
            None,
            f"Could not verify: package '{e.name}' is not installed yet. List it in the header `requirements:` line.",
        )
    except Exception as e:
        return None, f"{type(e).__name__}: {e} ({_where(code)})", None
    finally:
        sys.modules.pop(name, None)


def _where(code: str) -> str:
    """'line N: <source line>' of the innermost traceback frame that belongs to the tool file."""
    tb = traceback.extract_tb(sys.exc_info()[2])
    frame = next((f for f in reversed(tb) if f.filename == "<string>"), None)
    if not frame:
        return "no tool-file line"
    lines = code.splitlines()
    txt = lines[frame.lineno - 1].strip() if 0 < frame.lineno <= len(lines) else ""
    return f"line {frame.lineno}: `{txt[:110]}`"


def _cases(code: str, inst) -> list:
    """[(method, kwargs)] from `# test:` comments, else one auto-generated call per public method."""
    explicit = []
    for m in re.finditer(r"^[ \t]*#\s*test:\s*(.+?)\s*$", code, re.M):
        spec = m.group(1)
        if spec.lower() == "none":
            return []
        try:
            call = ast.parse(spec, mode="eval").body
            explicit.append(
                (
                    call.func.id,
                    {k.arg: ast.literal_eval(k.value) for k in call.keywords},
                )
            )
        except Exception:
            continue
    if explicit:
        return explicit
    sample = {"int": 1, "float": 1.0, "bool": False, "list": [], "dict": {}}
    out = []
    for name in _public(code):
        fn = getattr(inst, name, None)
        if not callable(fn):
            continue
        args = {}
        for p in inspect.signature(fn).parameters.values():
            if (
                p.name in _SPECIAL
                or p.default is not p.empty
                or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            ):
                continue
            args[p.name] = sample.get(
                getattr(p.annotation, "__name__", str(p.annotation)), "test"
            )
        out.append((name, args))
    return out


# test: none

class Tools:
    class Valves(BaseModel):
        OWUI_URL: str = Field(
            default="http://localhost:8080",
            description="Address of THIS Open WebUI server as seen from inside the server. Default fits Docker and `open-webui serve`.",
        )
        API_KEY: str = Field(
            default="",
            description="Optional Open WebUI API key (sk-...). Empty = reuse the logged-in user's own session (recommended).",
        )
        ADMIN_ONLY: bool = Field(
            default=True,
            description="Only admins may create/change tools. Keep on: tools run arbitrary Python on your server.",
        )
        ACCESS: str = Field(
            default="private",
            description="Who can see new tools: 'private' (creator only) or 'public' (all users).",
        )
        TEST_TIMEOUT: int = Field(
            default=30,
            ge=5,
            le=300,
            description="Seconds each verification call may run.",
        )
        BACKUP_DIR: str = Field(
            default="/tmp/tool_builder_backups",
            description="Folder for automatic version backups. Empty disables backups.",
        )
        BACKUP_KEEP: int = Field(
            default=10, ge=1, le=100, description="Backup versions to keep per tool."
        )

    class UserValves(BaseModel):
        AUTHOR: str = Field(
            default="",
            description="Your name. Written as `author:` in every tool you build.",
        )
        AUTHOR_URL: str = Field(
            default="",
            description="Your website or GitHub. Written as `author_url:` in the header.",
        )
        LICENSE: str = Field(
            default="",
            description="License written to the header, e.g. MIT. Empty = leave as written.",
        )
        NEW_TOOL_ACCESS: str = Field(
            default="",
            description="Who can see tools you create: 'private', 'public', or empty for the admin default.",
        )
        AUTO_VERSION_BUMP: bool = Field(
            default=True,
            description="Raise the patch version (1.0.0 -> 1.0.1) automatically when you update a tool.",
        )
        VERIFY: bool = Field(
            default=True,
            description="After saving, call every tool method once to check it works. Turn off for tools that need keys or slow services.",
        )
        STYLE_REQUIREMENTS: str = Field(
            default="",
            description="Your style and special requirements, in your own words. The LLM follows them for every tool it builds. E.g. 'dark cards, teal accent, free APIs only, short comments'.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------ plumbing

    @staticmethod
    def _uvraw(user, key: str):
        v = (user or {}).get("valves")
        return v.get(key) if isinstance(v, dict) else getattr(v, key, None)

    def _uv(self, user, key: str) -> str:
        val = self._uvraw(user, key)
        return "" if val is None else str(val).strip()

    def _flag(self, user, key: str, default: bool) -> bool:
        val = self._uvraw(user, key)
        return default if val is None else bool(val)

    def _prefs(self, user) -> str:
        req = self._uv(user, "STYLE_REQUIREMENTS")
        return (
            f"\nUSER STYLE / SPECIAL REQUIREMENTS (follow them):\n{req}\n"
            if req
            else ""
        )

    def _denied(self, user) -> Optional[str]:
        if self.valves.ADMIN_ONLY and (user or {}).get("role") != "admin":
            return (
                "Denied: only admins can manage tools (Tool Builder valve ADMIN_ONLY)."
            )
        return None

    def _headers(self, request) -> dict:
        if self.valves.API_KEY:
            return {"Authorization": f"Bearer {self.valves.API_KEY}"}
        if request is not None:
            auth = request.headers.get("authorization")
            if auth:
                return {"Authorization": auth}
            tok = request.cookies.get("token")
            if tok:
                return {"Authorization": f"Bearer {tok}"}
        return {}

    async def _api(self, method: str, path: str, request, body=None):
        url = self.valves.OWUI_URL.rstrip("/") + path
        async with httpx.AsyncClient(timeout=60) as c:
            return await c.request(
                method, url, headers=self._headers(request), json=body
            )

    def _access(self, user=None):
        mode = (self._uv(user, "NEW_TOOL_ACCESS") or self.valves.ACCESS).lower()
        if mode == "public":
            return None
        empty = {"group_ids": [], "user_ids": []}
        return {"read": dict(empty), "write": dict(empty)}

    async def _status(self, em, text: str, done: bool = False):
        if em:
            try:
                await em(
                    {"type": "status", "data": {"description": text, "done": done}}
                )
            except Exception:
                pass

    def _backup(self, tid: str, content: str):
        d = self.valves.BACKUP_DIR
        if not d or not content:
            return
        try:
            p = os.path.join(d, tid)
            os.makedirs(p, exist_ok=True)
            stamp = (
                time.strftime("%Y%m%d-%H%M%S")
                + f"-{int(time.time() * 1000) % 1000:03d}"
            )
            with open(os.path.join(p, stamp + ".py"), "w", encoding="utf-8") as f:
                f.write(content)
            for old in sorted(os.listdir(p))[: -self.valves.BACKUP_KEEP]:
                os.unlink(os.path.join(p, old))
        except Exception:
            log.exception("Tool Builder: backup failed for %s", tid)

    def _versions(self, tid: str) -> list:
        try:
            return sorted(
                f[:-3]
                for f in os.listdir(os.path.join(self.valves.BACKUP_DIR, tid))
                if f.endswith(".py")
            )
        except Exception:
            return []

    # ------------------------------------------------------------ verification

    async def _invoke(self, inst, method: str, args: dict, user, request):
        fn = getattr(inst, method, None)
        if method.startswith("_") or not callable(fn):
            raise ValueError(f"no public method '{method}'")

        async def _noop(*a, **k):
            return None

        params = inspect.signature(fn).parameters
        injected = {
            "__user__": user or {},
            "__request__": request,
            "__event_emitter__": _noop,
            "__event_call__": _noop,
            "__metadata__": {},
            "__model__": {},
            "__messages__": [],
        }
        kwargs = dict(args)
        for k, v in injected.items():
            if k in params and k not in kwargs:
                kwargs[k] = v
        res = fn(**kwargs)
        if inspect.isawaitable(res):
            res = await res
        return res

    async def _smoke(self, code: str, inst, user, request) -> tuple:
        tmo = self.valves.TEST_TIMEOUT
        """Call each method once. Returns (lines, n_failed)."""
        lines, bad = [], 0
        for method, args in _cases(code, inst):
            try:
                res = await asyncio.wait_for(
                    self._invoke(inst, method, args, user, request), tmo
                )
                if inspect.iscoroutine(res):
                    res.close()
                    raise RuntimeError(
                        "returned an un-awaited coroutine: add `await` before the async call"
                    )
                if isinstance(res, tuple) and res:
                    res = res[0]
                body = getattr(res, "body", None)
                is_card = isinstance(body, (bytes, bytearray))
                text = (
                    bytes(body).decode("utf-8", "replace")
                    if is_card
                    else (res if isinstance(res, str) else json.dumps(res, default=str))
                )
                if text.strip().lower().startswith(("error", "❌")):
                    bad += 1
                    lines.append(f"✗ {method}({_fmt(args)}): {text[:160]}")
                    continue
                if is_card and "<!--ui-error-->" in text:
                    m = re.search(r'<div class="title">(.*?)</div>', text)
                    lines.append(
                        f"⚠ {method}({_fmt(args)}): returned an error card ('{m.group(1) if m else 'error'}'). "
                        "If the sample input was valid, fix the cause; pin real arguments with `# test: ...`."
                    )
                    continue
                note = (
                    f"card {len(text) // 1024 or 1} KB"
                    if is_card
                    else f"{len(text)} chars"
                )
                issues = _lint_html(text) if is_card else []
                lines.append(
                    f"✓ {method} ({note})"
                    + (f"  ⚠ {'; '.join(issues)}" if issues else "")
                )
            except asyncio.TimeoutError:
                bad += 1
                lines.append(f"✗ {method}: timed out after {tmo}s")
            except Exception as e:
                bad += 1
                lines.append(
                    f"✗ {method}({_fmt(args)}): {type(e).__name__}: {e} ({_where(code)})"
                )
        return lines, bad

    # ------------------------------------------------------------ save pipeline

    async def _save(
        self, src: str, tool_id: str, user, request, em, verb: str = ""
    ) -> str:
        src, err = _expand_kits(_unescape_unicode(_clean(src)))
        if err:
            return "NOT SAVED. " + err
        for key, uk in (
            ("author", "AUTHOR"),
            ("license", "LICENSE"),
            ("author_url", "AUTHOR_URL"),
        ):
            src = _set_header(src, key, self._uv(user, uk))
        meta = _header(src)
        name = meta.get("title", "")
        if not name:
            return "NOT SAVED. The file must start with a header docstring containing `title:` (plus description, author, version)."
        desc = meta.get("description") or name
        tid = _slug(tool_id) or _slug(name)
        if not tid:
            return "NOT SAVED. Could not derive a tool id from the title."
        try:
            ast.parse(src)
        except SyntaxError as e:
            return f"NOT SAVED. SyntaxError line {e.lineno}: {e.msg}"
        if "Tools" not in _class_names(src):
            return "NOT SAVED. No top-level `class Tools:` found."
        if not _public(src):
            return "NOT SAVED. `class Tools` has no public methods."

        await self._status(em, f"Verifying '{name}'...")
        inst, load_err, load_warn = await asyncio.to_thread(_load, src)
        if load_err:
            await self._status(em, "Not saved", True)
            return f"NOT SAVED. The file failed to load: {load_err}\nFix it and call save_tool() again."
        warnings = _lint_code(src) + ([load_warn] if load_warn else [])

        try:
            cur = await self._api("GET", f"/api/v1/tools/id/{tid}", request)
        except Exception as e:
            return f"NOT SAVED. Could not reach Open WebUI at {self.valves.OWUI_URL}: {e}. Check the OWUI_URL valve."
        exists = cur.is_success
        if exists:
            old = cur.json()
            self._backup(tid, old.get("content", ""))
            if self._flag(user, "AUTO_VERSION_BUMP", True):
                src = _bump(src, old.get("content", ""))
            form = {
                "id": tid,
                "name": name,
                "content": src,
                "meta": {**(old.get("meta") or {}), "description": desc},
                "access_control": old.get("access_control"),
            }
            r = await self._api("POST", f"/api/v1/tools/id/{tid}/update", request, form)
        else:
            try:
                others = await self._api("GET", "/api/v1/tools/", request)
                words = {
                    w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) > 2
                }
                for t in (
                    others.json() if others is not None and others.is_success else []
                ):
                    if words & set(
                        re.findall(r"[a-z0-9]+", (t.get("name") or "").lower())
                    ):
                        warnings.append(
                            f"Similar tool already exists: '{t.get('name')}' (id: {t.get('id')})."
                        )
            except Exception:
                pass
            form = {
                "id": tid,
                "name": name,
                "content": src,
                "meta": {"description": desc, "manifest": {}},
                "access_control": self._access(user),
            }
            r = await self._api("POST", "/api/v1/tools/create", request, form)

        if not r.is_success:
            await self._status(em, "Not saved", True)
            hint = (
                " (Auth failed: set the API_KEY valve.)"
                if r.status_code in (401, 403)
                else ""
            )
            return (
                f"NOT SAVED. Open WebUI answered {r.status_code}: {r.text[:300]}{hint}"
            )

        verify = inst is not None and self._flag(user, "VERIFY", True)
        lines, bad = await self._smoke(src, inst, user, request) if verify else ([], 0)
        await self._status(em, "Verification failed" if bad else "Saved", True)
        version = _header(src).get("version") or "?"
        what = verb or ("updated" if exists else "created")
        mark = "⚠" if bad else "✓"
        out = [f"{mark} {what.capitalize()} '{name}' (id: {tid}, v{version})"]
        if lines:
            out.append("Verification:\n" + "\n".join(lines))
        elif load_warn:
            out.append(load_warn)
        if warnings:
            out.append("Warnings (optional):\n- " + "\n- ".join(warnings[:8]))
        score, tips = _polish(src)
        out.append(f"Polish: {score}/10")
        if tips and score < 8 and not bad and verb != "patched":
            out.append(
                "Before telling the user, apply these in ONE patch_tool call (then stop polishing):\n- "
                + "\n- ".join(tips)
            )
        if bad:
            out.append(
                f"FIX: patch_tool(tool_id='{tid}', patch=<SEARCH/REPLACE blocks>). Do NOT tell the user it is ready yet."
            )
        else:
            v = _valve_names(src)
            if v["Valves"] or v["UserValves"]:
                out.append(
                    "Settings: "
                    + (f"Valves {', '.join(v['Valves'])}. " if v["Valves"] else "")
                    + (
                        f"User valves {', '.join(v['UserValves'])}."
                        if v["UserValves"]
                        else ""
                    )
                )
            out.append(
                f"NEXT: tell the user exactly this, in order: (1) Refresh the browser now (F5) so the new tool loads. "
                f"(2) Then click the ➕ / Integrations button in the message box, open Tools and switch on '{name}'. "
                f"Settings: Workspace > Tools > ⚙️. '{name}' is saved and verified. Do not try to call the new tool yourself."
            )
        return "\n".join(out)

    # ------------------------------------------------------------ LLM-facing tools

    async def get_guide(self, __user__: Optional[dict] = None) -> str:
        """
        Get the build instructions for Open WebUI tools: workflow, file rules, design kit signatures and one working example.
        Call this ONCE before writing a new tool.
        :return: The guide.
        """
        return GUIDE + self._prefs(__user__)

    async def plan_tool(self, idea: str) -> str:
        """
        Get a 6-line design template for a new tool so it comes out polished. Use for any tool that is not trivial.
        :param idea: What the tool should do, in one sentence.
        :return: The design questions to answer before writing code.
        """
        return (
            f"PLAN for: {idea}\n"
            "Answer these in six short lines, then write the file and call save_tool(code=...):\n"
            "1. Output: CARD (user looks at it) or TEXT (one value / data for the LLM)?\n"
            "2. Data: which free keyless API or source? Which 3-6 fields matter? What happens when nothing is found?\n"
            "3. Layout: banner emoji + accent (from the data?), which tabs, the ONE headline number, which visual for the numbers.\n"
            "4. Valves: 3-6 admin settings (TIMEOUT, CACHE_TTL, ACCENT, limits, defaults). UserValves only if per-user.\n"
            "5. Methods: 1-6 public methods, each with 'Use when / Do not use for' in its docstring.\n"
            "6. Finishing: status steps, citations, caching, llm_context, follow-up suggestions, ui_error / ui_empty states."
        )

    async def improve_tool(
        self, tool_id: str, __user__: Optional[dict] = None, __request__=None
    ) -> str:
        """
        Upgrade an existing tool: scores its polish and lists what to add. Use when the user says make a tool better or nicer.
        :param tool_id: Id of the tool to improve.
        :return: Polish score, suggestions and the current source.
        """
        if d := self._denied(__user__):
            return d
        tid = _slug(tool_id)
        try:
            r = await self._api("GET", f"/api/v1/tools/id/{tid}", __request__)
        except Exception as e:
            return f"Request failed: {e}"
        if not r.is_success:
            return f"Tool '{tid}' not found ({r.status_code}). Call list_tools."
        src = _collapse_kits(r.json().get("content", ""))
        score, tips = _polish(src)
        if not tips:
            return f"'{tid}' is already at {score}/10. Nothing to improve."
        return (
            f"Polish {score}/10 for '{tid}'. Suggestions:\n- "
            + "\n- ".join(tips)
            + "\n\nApply them with ONE patch_tool call (SEARCH/REPLACE), keep the existing behaviour, then stop. Current source:\n\n"
            + src
        )

    async def save_tool(
        self,
        code: str,
        tool_id: str = "",
        __user__: Optional[dict] = None,
        __request__=None,
        __messages__: Optional[list] = None,
        __event_emitter__=None,
    ) -> str:
        """
        SAVE a tool into Open WebUI: verifies it, then installs it (updates it if the same id exists, old version backed up).
        Pass the COMPLETE Python file as `code`. Do NOT print the file in the chat instead: nothing is saved until this tool is called.
        :param code: The complete .py file (header docstring + `class Tools:`), plain source, no JSON escaping, no markdown fences needed.
        :param tool_id: Optional. Override the id (default: derived from the header title). Use it to update an existing tool.
        :return: Verification result, the tool id and the next step.
        """
        if d := self._denied(__user__):
            return d
        src = code if (code or "").strip() else _code_from_messages(__messages__)
        if not (src or "").strip():
            return "No code received. Call save_tool again with the complete .py file as the `code` argument (do not just print it in the chat)."
        return await self._save(src, tool_id, __user__, __request__, __event_emitter__)

    async def patch_tool(
        self,
        tool_id: str,
        patch: str,
        __user__: Optional[dict] = None,
        __request__=None,
        __event_emitter__=None,
    ) -> str:
        """
        Edit an existing tool with SEARCH/REPLACE blocks instead of resending the file, then verify it again. Copy the SEARCH lines exactly from read_tool.
        Format, repeatable:
        <<<<<<< SEARCH
        old lines
        =======
        new lines
        >>>>>>> REPLACE
        :param tool_id: Id of the tool to edit.
        :param patch: One or more SEARCH/REPLACE blocks as plain text.
        :return: Verification result.
        """
        if d := self._denied(__user__):
            return d
        tid = _slug(tool_id)
        try:
            r = await self._api("GET", f"/api/v1/tools/id/{tid}", __request__)
        except Exception as e:
            return f"Request failed: {e}"
        if not r.is_success:
            return f"Tool '{tid}' not found ({r.status_code}). Call list_tools."
        src, err = _apply_patch(_collapse_kits(r.json().get("content", "")), patch)
        if err:
            return "NOT PATCHED. " + err
        return await self._save(
            src, tid, __user__, __request__, __event_emitter__, verb="patched"
        )

    async def read_tool(
        self, tool_id: str, __user__: Optional[dict] = None, __request__=None
    ) -> str:
        """
        Read the source of an existing tool (design kits shown as one-line `# @include` markers), e.g. before patch_tool.
        :param tool_id: Id of the tool.
        :return: The Python source.
        """
        if d := self._denied(__user__):
            return d
        try:
            r = await self._api(
                "GET", f"/api/v1/tools/id/{_slug(tool_id)}", __request__
            )
        except Exception as e:
            return f"Request failed: {e}"
        if not r.is_success:
            return f"Tool not found ({r.status_code}). Call list_tools."
        return _collapse_kits(r.json().get("content", ""))

    async def list_tools(self, query: str = "", __request__=None) -> str:
        """
        List installed tools (id, name, description). Use it to find a tool id or check whether a similar tool already exists.
        :param query: Optional keyword filter, e.g. "weather".
        :return: One tool per line.
        """
        try:
            r = await self._api("GET", "/api/v1/tools/", __request__)
            r.raise_for_status()
        except Exception as e:
            return f"Request failed: {e}"
        words = (query or "").lower().split()
        out = []
        for t in r.json():
            d = (t.get("meta") or {}).get("description") or ""
            if all(w in f"{t.get('id')} {t.get('name')} {d}".lower() for w in words):
                out.append(f"- {t.get('id')} ({t.get('name')}): {d[:100]}")
        return "\n".join(out) or "No matching tools."

    async def revert_tool(
        self,
        tool_id: str,
        version: str = "",
        __user__: Optional[dict] = None,
        __request__=None,
        __event_emitter__=None,
    ) -> str:
        """
        Restore an earlier version after a bad edit (the current version is backed up first).
        :param tool_id: Id of the tool.
        :param version: A version id, "list" to show the available ones, or empty for the newest backup.
        :return: Result of the restore, or the version list.
        """
        if d := self._denied(__user__):
            return d
        tid = _slug(tool_id)
        vs = self._versions(tid)
        if not vs:
            return "No backups found for this tool."
        if version.strip().lower() == "list":
            return "Versions (oldest first): " + ", ".join(vs)
        pick = version.strip() or vs[-1]
        if pick not in vs:
            return f"Unknown version '{pick}'. Available: {', '.join(vs)}."
        try:
            with open(
                os.path.join(self.valves.BACKUP_DIR, tid, pick + ".py"),
                "r",
                encoding="utf-8",
            ) as f:
                old = f.read()
        except Exception as e:
            return f"Could not read backup: {e}"
        return await self._save(
            old, tid, __user__, __request__, __event_emitter__, verb="reverted"
        )


def _set_header(code: str, key: str, value: str) -> str:
    """Force `key:` in the header docstring to `value` (no-op when the value is empty)."""
    if not value:
        return code
    value = value.replace("\n", " ")
    m = _HDR.match(code)
    if not m:
        return code
    body = m.group(2)
    pat = r"^(\s*" + re.escape(key) + r":).*$"
    if re.search(pat, body, re.M):
        body = re.sub(
            pat, lambda x: x.group(1) + " " + value, body, count=1, flags=re.M
        )
    else:
        body = body.rstrip("\n") + "\n" + key + ": " + value + "\n"
    return code[: m.start(2)] + body + code[m.end(2) :]


def _fmt(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())[:80]


def _class_names(code: str) -> list:
    try:
        return [n.name for n in ast.parse(code).body if isinstance(n, ast.ClassDef)]
    except SyntaxError:
        return []
