"""
title: Podcast Player
description: >
  Stream any podcast directly in chat using the free iTunes Search API + RSS feeds.
  No API key required. Features a cinematic audio player with animated waveform,
  playback speed control, 30-second skip (podcast standard), and episode browsing.

  Commands:
    - "play podcast Joe Rogan"                       → latest episode
    - "play podcast Serial episode 5"                → episode by number
    - "play podcast Hardcore History Blitzkrieg"     → episode by title keyword
    - "search podcast true crime"                    → browse matching shows
    - "top podcasts"                                 → Apple's top 25 right now
    - "random podcast episode Lex Fridman"           → surprise episode

  Setup: No configuration needed — works out of the box.
  Optional: Set COUNTRY_CODE in Valves to localise the top-chart rankings (default: us).

author: ichrist
version: 1.0.0
license: MIT
"""

import aiohttp
import logging
import re
import random
import json as _json
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Optional, Callable, Awaitable

from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_ITUNES_SEARCH = "https://itunes.apple.com/search"
_APPLE_TOP_URL = (
    "https://rss.applemarketingtools.com/api/v2/{country}/podcasts/top/25/podcasts.json"
)
_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"

_HUE_FAMILIES = [
    (300, 330),
    (175, 200),
    (90, 130),
    (25, 50),
    (250, 280),
    (0, 18),
    (155, 175),
    (330, 355),
]

# ── Colour palette (same engine as the Jellyfin tool) ────────────────────────


def _vivid_palette():
    fam = random.sample(_HUE_FAMILIES, 5)
    h = [random.randint(lo, hi) for lo, hi in fam]
    s = [random.randint(96, 100)] * 5
    l_ = [random.randint(60, 70)] * 5
    solid = [f"hsl({h[i]},{s[i]}%,{l_[i]}%)" for i in range(5)]
    faint = [f"hsla({h[i]},{s[i]}%,{l_[i]}%,0.09)" for i in range(5)]
    mid = [f"hsla({h[i]},{s[i]}%,{l_[i]}%,0.26)" for i in range(5)]
    glow = [f"hsla({h[i]},{s[i]}%,{l_[i]}%,0.55)" for i in range(5)]
    return solid, faint, mid, glow


# ── Generic helpers ───────────────────────────────────────────────────────────


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


def _parse_dur(s: str) -> int:
    """'HH:MM:SS' | 'MM:SS' | raw-seconds → int seconds."""
    if not s:
        return 0
    parts = s.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(float(s))
    except (ValueError, IndexError):
        return 0


def _fmt_time(sec: int) -> str:
    sec = max(0, int(sec or 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_date(pub: str) -> str:
    if not pub:
        return ""
    try:
        return parsedate_to_datetime(pub).strftime("%b %d, %Y")
    except Exception:
        return pub[:10]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#\d+;", "", text)
    return " ".join(text.split()).strip()


# ── iTunes / RSS helpers ──────────────────────────────────────────────────────


async def _search_itunes(session, term: str, limit: int = 10) -> list:
    try:
        async with session.get(
            _ITUNES_SEARCH,
            params={
                "term": term,
                "media": "podcast",
                "entity": "podcast",
                "limit": limit,
            },
            timeout=aiohttp.ClientTimeout(total=12),
        ) as r:
            if r.status != 200:
                return []
            d = await r.json(content_type=None)
        return d.get("results", [])
    except Exception as exc:
        logger.error(f"iTunes search error: {exc}")
        return []


async def _fetch_rss(session, feed_url: str):
    """Returns (podcast_meta_dict, episodes_list).  Both are empty on failure."""
    try:
        async with session.get(
            feed_url,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OpenWebUI-PodcastPlayer/1.0)"
            },
        ) as r:
            if r.status != 200:
                return {}, []
            raw = await r.read()
        root = ET.fromstring(raw)
    except Exception as exc:
        logger.error(f"RSS error {feed_url}: {exc}")
        return {}, []

    ch = root.find("channel")
    if ch is None:
        return {}, []

    img_el = ch.find(f"{{{_ITUNES_NS}}}image")
    meta = {
        "title": (ch.findtext("title") or "").strip(),
        "art": (
            img_el.get("href", "")
            if img_el is not None
            else ch.findtext("image/url") or ""
        ),
    }

    eps = []
    for item in ch.findall("item"):
        enc = item.find("enclosure")
        if enc is None:
            continue
        url = enc.get("url", "")
        if not url or not url.startswith("http"):
            continue
        img2 = item.find(f"{{{_ITUNES_NS}}}image")
        eps.append(
            {
                "title": (item.findtext("title") or "Unknown").strip(),
                "audio_url": url,
                "description": _strip_html(item.findtext("description") or "")[:500],
                "pub_date": item.findtext("pubDate") or "",
                "duration_s": _parse_dur(
                    item.findtext(f"{{{_ITUNES_NS}}}duration") or ""
                ),
                "ep_num": item.findtext(f"{{{_ITUNES_NS}}}episode") or "",
                "ep_image": (img2.get("href", "") if img2 is not None else ""),
            }
        )

    return meta, eps


def _pick_episode(episodes: list, query: str):
    """Return (index, episode_dict).  Supports episode numbers and title keywords."""
    if not episodes:
        return 0, {}
    q = query.strip()
    if not q:
        return 0, episodes[0]

    # Pure integer → try itunes:episode tag, then 1-based positional index
    if re.fullmatch(r"\d+", q):
        n = int(q)
        for i, ep in enumerate(episodes):
            if ep.get("ep_num") == str(n):
                return i, ep
        idx = min(max(n - 1, 0), len(episodes) - 1)
        return idx, episodes[idx]

    # Text → fuzzy title match
    q_low = q.lower()
    q_words = set(re.split(r"\W+", q_low)) - {""}
    best_i, best = 0, -1
    for i, ep in enumerate(episodes):
        t = ep["title"].lower()
        score = len(q_words & set(re.split(r"\W+", t))) * 2
        if q_low in t:
            score += 10
        if score > best:
            best, best_i = score, i
    return best_i, episodes[best_i]


# ── HTML builders ─────────────────────────────────────────────────────────────


def _build_player(
    podcast_name: str, episode: dict, art_url: str, ep_idx: int, total: int
) -> str:
    """Build and return the full HTML string for the audio player card."""

    p, pa, pm, pg = _vivid_palette()
    safe = re.sub(r"[^a-zA-Z0-9]", "", episode.get("title", "x"))[:14]
    pid = f"pod{safe}{random.randint(1000, 9999)}"

    title = episode.get("title", "Unknown")
    audio_url = episode.get("audio_url", "")
    desc = episode.get("description", "")
    dur_s = episode.get("duration_s", 0)
    dur_str = _fmt_time(dur_s) if dur_s else "–"
    pub_str = _fmt_date(episode.get("pub_date", ""))
    ep_num = episode.get("ep_num", "")
    art = episode.get("ep_image", "") or art_url

    meta_str = "  ·  ".join(x for x in [pub_str, dur_str] if x)
    ep_label = f"Episode {ep_num}" if ep_num else f"#{ep_idx + 1} of {total}"

    # Pre-build conditional HTML fragments (avoids nested-quote hell in f-strings)
    art_img = (
        (
            '<img src="' + art + '" alt="" '
            'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1;" '
            "onerror=\"this.style.display='none'\">"
        )
        if art
        else ""
    )

    desc_block = f'<p class="edesc">{desc}</p>' if desc else ""

    # CSS variable injection string
    cv = "".join(
        f"--c{i}:{p[i]};--ca{i}:{pa[i]};--cm{i}:{pm[i]};--cg{i}:{pg[i]};"
        for i in range(5)
    )

    # Speed-control buttons
    speeds = [
        ("0.75×", "0.75"),
        ("1×", "1"),
        ("1.25×", "1.25"),
        ("1.5×", "1.5"),
        ("2×", "2"),
    ]
    spd_btns = "".join(
        f'<button class="sb{"  sa" if v == "1" else ""}" data-s="{v}" onclick="setSpd(this)">{lbl}</button>'
        for lbl, v in speeds
    )

    COLS_JS = ",".join(_json.dumps(c) for c in p)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{{cv}}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{
  background:linear-gradient(135deg,#060608 0%,#0c0810 40%,#080c10 100%);
  font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;
  height:auto;overflow:hidden;padding:6px;
}}
.card{{
  border-radius:20px;overflow:hidden;
  background:linear-gradient(160deg,#0d0d14 0%,#0a0a0e 100%);
  border:1px solid {pm[0]};
  box-shadow:0 0 0 1px {pa[0]},0 0 60px {pa[1]},0 0 120px {pa[3]},0 24px 60px rgba(0,0,0,.98);
}}
.stripe{{
  height:3px;
  background:linear-gradient(90deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[0]});
  background-size:300% 100%;animation:ss 3s linear infinite;
}}
@keyframes ss{{0%{{background-position:0%}}100%{{background-position:300%}}}}

/* ── Hero / metadata row ── */
.hero{{
  display:flex;gap:18px;padding:20px 20px 16px;
  background:linear-gradient(160deg,#0e0e16 0%,#0a0a10 100%);
  position:relative;overflow:hidden;
}}
.hero::before{{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:
    radial-gradient(ellipse 80% 100% at 0% 0%,{pa[0]} 0%,transparent 55%),
    radial-gradient(ellipse 60% 80% at 100% 100%,{pa[2]} 0%,transparent 60%);
}}
.ao{{flex-shrink:0;width:118px;height:118px;position:relative;z-index:1;}}
.aring{{
  position:absolute;inset:-3px;border-radius:17px;
  background:conic-gradient({p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[0]});
  animation:spin 5s linear infinite;z-index:0;
}}
.ai{{
  position:absolute;inset:3px;border-radius:13px;overflow:hidden;z-index:1;
  background:linear-gradient(135deg,{pa[0]},{pa[2]});
  display:flex;align-items:center;justify-content:center;
}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.afb{{font-size:38px;line-height:1;}}
.meta{{flex:1;min-width:0;position:relative;z-index:1;display:flex;flex-direction:column;gap:3px;}}
.pname{{
  font-size:9px;font-weight:900;letter-spacing:2px;text-transform:uppercase;
  color:{p[0]};text-shadow:0 0 18px {pg[0]};margin-bottom:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}}
.etitle{{
  font-size:18px;font-weight:900;color:#fff;line-height:1.2;letter-spacing:-.3px;
  text-shadow:0 2px 16px {pa[0]};
  overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
}}
.emeta{{font-size:11px;color:#445;margin-top:2px;letter-spacing:.3px;}}
.elbl{{
  display:inline-block;font-size:9px;font-weight:900;
  background:{pa[2]};color:{p[2]};border:1px solid {pm[2]};
  padding:2px 10px;border-radius:20px;margin-top:5px;
}}
.edesc{{
  font-size:11.5px;color:#666;line-height:1.6;margin-top:8px;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
}}

/* ── Player zone ── */
.pzone{{
  padding:16px 20px 18px;
  background:linear-gradient(180deg,{pa[0]} 0%,transparent 50%),#0d0d14;
  border-top:1px solid {pm[0]};
}}

/* Waveform */
.ww{{position:relative;cursor:pointer;margin-bottom:10px;user-select:none;}}
canvas#wv_{pid}{{width:100%;height:52px;display:block;border-radius:7px;background:rgba(0,0,0,.3);}}
.pline{{
  position:absolute;top:0;bottom:0;width:2px;
  background:linear-gradient(180deg,{p[0]},{p[2]});
  box-shadow:0 0 8px {pg[0]};pointer-events:none;border-radius:2px;
  left:0%;transition:left .1s linear;
}}

.trow{{
  display:flex;justify-content:space-between;
  font-size:10.5px;color:#404040;font-family:'SF Mono','Fira Code',monospace;
  margin-bottom:12px;letter-spacing:.4px;
}}

/* Speed row */
.srow{{display:flex;align-items:center;gap:5px;margin-bottom:14px;flex-wrap:wrap;}}
.slbl{{
  font-size:9px;font-weight:900;letter-spacing:1.5px;text-transform:uppercase;
  color:{p[1]};margin-right:3px;white-space:nowrap;
}}
.sb{{
  font-size:10px;font-weight:900;padding:3px 9px;border-radius:20px;
  border:1.5px solid {pm[1]};background:{pa[1]};color:{p[1]};
  cursor:pointer;transition:all .15s;white-space:nowrap;
}}
.sb:hover,.sa{{background:{pm[1]};color:#000;border-color:{p[1]};box-shadow:0 0 14px {pm[1]};}}

/* Transport */
.transport{{display:flex;align-items:center;justify-content:center;gap:14px;margin-bottom:16px;}}
.bplay{{
  width:56px;height:56px;border-radius:50%;border:none;cursor:pointer;
  background:linear-gradient(135deg,{p[0]},{p[2]});color:#000;
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 28px {pg[0]};transition:all .2s;
}}
.bplay:hover{{transform:scale(1.08);box-shadow:0 0 50px {pg[0]};}}
.bplay svg{{margin-left:3px;}}
.bsk{{
  width:40px;height:40px;border-radius:50%;
  border:1.5px solid {pm[2]};background:{pa[2]};color:{p[2]};
  cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;
  box-shadow:0 0 12px {pa[2]};transition:all .2s;flex-shrink:0;
}}
.bsk:hover{{border-color:{p[2]};background:{pm[2]};color:#000;}}
.bsk .skn{{font-size:7px;font-weight:900;line-height:1;}}

/* Bottom row */
.brow{{
  display:flex;align-items:center;gap:10px;
  border-top:1px solid {pa[1]};padding-top:12px;flex-wrap:wrap;
}}
.vwrap{{display:flex;align-items:center;gap:7px;flex:1;min-width:100px;}}
.vic{{color:{p[3]};flex-shrink:0;}}
input.vsl{{
  -webkit-appearance:none;appearance:none;flex:1;height:4px;
  border-radius:2px;outline:none;cursor:pointer;
  background:linear-gradient(to right,{p[3]} var(--v,80%),#252530 var(--v,80%));
}}
input.vsl::-webkit-slider-thumb{{
  -webkit-appearance:none;width:13px;height:13px;border-radius:50%;
  background:{p[3]};box-shadow:0 0 9px {pg[3]};cursor:pointer;
}}
.dlbtn{{
  display:inline-flex;align-items:center;gap:5px;
  background:{pa[3]};color:{p[3]};border:1.5px solid {pm[3]};border-radius:20px;
  font-size:11px;font-weight:900;padding:5px 12px;text-decoration:none;
  box-shadow:0 0 12px {pa[3]};transition:all .2s;white-space:nowrap;
}}
.dlbtn:hover{{background:{pm[3]};color:#000;transform:translateY(-1px);}}

/* EQ animation */
.eq{{display:flex;align-items:flex-end;gap:2px;height:15px;}}
.eb{{
  width:3px;border-radius:2px;
  background:linear-gradient(180deg,{p[0]},{p[2]});
  animation:eq var(--d,.6s) ease-in-out infinite alternate;
}}
@keyframes eq{{from{{height:3px}}to{{height:var(--h,12px)}}}}
</style>
</head>
<body>
<div class="card">
  <div class="stripe"></div>

  <!-- ── Metadata hero ── -->
  <div class="hero">
    <div class="ao">
      <div class="aring"></div>
      <div class="ai">
        {art_img}
        <div class="afb">🎙</div>
      </div>
    </div>
    <div class="meta">
      <div class="pname">{podcast_name}</div>
      <div class="etitle">{title}</div>
      <div class="emeta">{meta_str}</div>
      <span class="elbl">{ep_label}</span>
      {desc_block}
    </div>
  </div>

  <!-- ── Player controls ── -->
  <div class="pzone">
    <!-- Waveform / scrubber -->
    <div class="ww" id="ww_{pid}">
      <canvas id="wv_{pid}" height="52"></canvas>
      <div class="pline" id="pl_{pid}"></div>
    </div>
    <div class="trow">
      <span id="ct_{pid}">0:00</span>
      <span id="dt_{pid}">{dur_str}</span>
    </div>

    <!-- Speed -->
    <div class="srow">
      <span class="slbl">Speed</span>
      {spd_btns}
    </div>

    <!-- Transport -->
    <div class="transport">
      <button class="bsk" onclick="seek(-30)" title="Back 30 s">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="1 4 1 10 7 10"/>
          <path d="M3.51 15a9 9 0 1 0 .49-3.54"/>
        </svg>
        <span class="skn">30</span>
      </button>

      <button class="bplay" id="bp_{pid}">
        <svg id="bpi_{pid}" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5,3 19,12 5,21"/>
        </svg>
      </button>

      <button class="bsk" onclick="seek(30)" title="Forward 30 s">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-.49-3.54"/>
        </svg>
        <span class="skn">30</span>
      </button>
    </div>

    <!-- Volume + EQ + download -->
    <div class="brow">
      <div class="vwrap">
        <svg class="vic" width="15" height="15" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
        </svg>
        <input type="range" class="vsl" id="vol_{pid}" min="0" max="100" value="80">
      </div>
      <div class="eq" id="eq_{pid}" style="display:none;">
        <div class="eb" style="--d:.5s;--h:9px;"></div>
        <div class="eb" style="--d:.3s;--h:14px;animation-delay:.1s"></div>
        <div class="eb" style="--d:.4s;--h:10px;animation-delay:.2s"></div>
        <div class="eb" style="--d:.6s;--h:7px; animation-delay:.05s"></div>
        <div class="eb" style="--d:.35s;--h:12px;animation-delay:.15s"></div>
      </div>
      <a class="dlbtn" href="{audio_url}" download>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>Download
      </a>
    </div>
  </div>
</div>

<audio id="aud_{pid}" preload="auto" src="{audio_url}"></audio>

<script>
(function() {{
  var PID  = {_json.dumps(pid)};
  var DUR  = {dur_s};
  var COLS = [{COLS_JS}];
  var N    = 90;

  var aud = document.getElementById("aud_" + PID);
  var bp  = document.getElementById("bp_"  + PID);
  var bpi = document.getElementById("bpi_" + PID);
  var ct  = document.getElementById("ct_"  + PID);
  var dt  = document.getElementById("dt_"  + PID);
  var pl  = document.getElementById("pl_"  + PID);
  var ww  = document.getElementById("ww_"  + PID);
  var cvs = document.getElementById("wv_"  + PID);
  var vsl = document.getElementById("vol_" + PID);
  var eq  = document.getElementById("eq_"  + PID);
  var ctx = cvs ? cvs.getContext("2d") : null;
  var bars = [];

  // Generate a pseudo-waveform (smoothed random bars)
  (function gen() {{
    for (var i = 0; i < N; i++) bars.push(0.15 + Math.random() * 0.65);
    for (var pass = 0; pass < 4; pass++)
      for (var i = 1; i < N - 1; i++)
        bars[i] = (bars[i-1] + bars[i] * 2 + bars[i+1]) / 4;
  }})();

  function pad(n) {{ return String(n).padStart(2, "0"); }}
  function fmt(sec) {{
    sec = Math.floor(sec || 0);
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    return h ? h + ":" + pad(m) + ":" + pad(s) : m + ":" + pad(s);
  }}

  function draw(prog) {{
    if (!ctx || !cvs) return;
    var dpr = window.devicePixelRatio || 1;
    var W = (cvs.offsetWidth || 500) * dpr;
    var H = 52 * dpr;
    if (cvs.width !== W) {{ cvs.width = W; cvs.height = H; }}
    ctx.clearRect(0, 0, W, H);
    var bw = W / N, gap = Math.max(1, bw * 0.2);
    for (var i = 0; i < N; i++) {{
      var bh = bars[i] * H * 0.82, y = (H - bh) / 2;
      ctx.fillStyle = (i / N < prog)
        ? COLS[Math.floor(i / N * COLS.length)]
        : "rgba(255,255,255,0.10)";
      ctx.fillRect(i * bw + gap / 2, y, Math.max(1, bw - gap), bh);
    }}
  }}

  function upd() {{
    var dur = aud.duration || DUR || 1;
    var prog = (aud.currentTime || 0) / dur;
    pl.style.left = (prog * 100).toFixed(2) + "%";
    ct.textContent = fmt(aud.currentTime);
    if (aud.duration) dt.textContent = fmt(aud.duration);
    draw(prog);
  }}

  // Exposed globals so onclick="" attributes can reach them
  window.seek = function(delta) {{
    aud.currentTime = Math.max(0, Math.min(aud.duration || 0, aud.currentTime + delta));
    upd();
  }};

  window.setSpd = function(btn) {{
    document.querySelectorAll(".sb").forEach(function(b) {{ b.classList.remove("sa"); }});
    btn.classList.add("sa");
    aud.playbackRate = parseFloat(btn.dataset.s);
  }};

  ww.addEventListener("click", function(e) {{
    var r = ww.getBoundingClientRect();
    aud.currentTime = ((e.clientX - r.left) / r.width) * (aud.duration || DUR || 1);
    upd();
  }});

  bp.addEventListener("click", function() {{
    if (aud.paused) aud.play().catch(function() {{}});
    else aud.pause();
  }});

  aud.volume = 0.8;
  vsl.addEventListener("input", function() {{
    aud.volume = this.value / 100;
    vsl.style.setProperty("--v", this.value + "%");
  }});
  vsl.style.setProperty("--v", "80%");

  var PLAY_SVG  = "<polygon points='5,3 19,12 5,21'/>";
  var PAUSE_SVG = "<rect x='6' y='4' width='4' height='16'/><rect x='14' y='4' width='4' height='16'/>";

  aud.addEventListener("play",  function() {{ bpi.innerHTML = PAUSE_SVG; eq.style.display = "flex"; }});
  aud.addEventListener("pause", function() {{ bpi.innerHTML = PLAY_SVG;  eq.style.display = "none"; }});
  aud.addEventListener("ended", function() {{
    bpi.innerHTML = PLAY_SVG;
    eq.style.display = "none";
    pl.style.left = "0%";
    draw(0);
  }});
  aud.addEventListener("timeupdate",    upd);
  aud.addEventListener("loadedmetadata", function() {{ dt.textContent = fmt(aud.duration); draw(0); }});

  setTimeout(function() {{
    draw(0);
    try {{
      window.parent.postMessage(
        {{type: "iframe-resize", id: PID, height: document.documentElement.scrollHeight}},
        "*"
      );
    }} catch (e) {{}}
  }}, 0);
  window.addEventListener("resize", function() {{ setTimeout(upd, 50); }});
}})();
</script>
</body>
</html>""".strip()


def _build_list_html(heading: str, items: list, footer_tip: str = "") -> str:
    """Build an HTML results table for search / top-charts views."""
    p, pa, pm, pg = _vivid_palette()

    rows = ""
    for i, it in enumerate(items):
        art = (it.get("artworkUrl100") or "").replace("100x100bb", "200x200bb")
        name = it.get("collectionName") or it.get("name") or "Unknown"
        author = it.get("artistName") or ""
        genres = [
            g for g in (it.get("genres") or []) if g.lower() not in ("podcasts", "")
        ]
        genre = genres[0] if genres else (it.get("primaryGenreName") or "")
        count = it.get("trackCount") or ""
        ci = i % 5

        rank_style = (
            f"font-size:15px;font-weight:900;color:{p[0]};text-shadow:0 0 16px {pg[0]};"
            if i == 0
            else f"font-size:11px;font-weight:700;color:{pm[ci]};"
        )

        genre_badge = (
            (
                f'<span style="font-size:9px;font-weight:900;'
                f"background:{pa[ci]};color:{p[ci]};border:1px solid {pm[ci]};"
                f'padding:2px 8px;border-radius:20px;white-space:nowrap;">{genre}</span>'
            )
            if genre
            else ""
        )

        count_line = (
            (
                f'<div style="font-size:10px;color:#2a2a35;margin-top:3px;">{count} eps</div>'
            )
            if count
            else ""
        )

        rows += (
            f"<tr>"
            f'<td style="padding:9px 10px;border-bottom:1px solid #131316;'
            f'width:26px;text-align:center;">'
            f'<span style="{rank_style}">#{i+1}</span>'
            f"</td>"
            f'<td style="padding:9px 10px;border-bottom:1px solid #131316;width:52px;">'
            f'<img src="{art}" style="width:40px;height:40px;border-radius:8px;'
            f'object-fit:cover;display:block;background:#111;" onerror="this.style.display=\'none\'">'
            f"</td>"
            f'<td style="padding:9px 10px;border-bottom:1px solid #131316;">'
            f'<div style="font-weight:800;color:#ddd;font-size:13px;">{name}</div>'
            f'<div style="color:#404040;font-size:11px;margin-top:2px;">{author}</div>'
            f"</td>"
            f'<td style="padding:9px 10px;border-bottom:1px solid #131316;'
            f'text-align:right;white-space:nowrap;">'
            f"{genre_badge}{count_line}"
            f"</td>"
            f"</tr>"
        )

    footer_html = (
        (
            f'<p style="font-size:11px;color:#2a2a35;margin-top:8px;text-align:center;">'
            f"{footer_tip}</p>"
        )
        if footer_tip
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:transparent;font-family:-apple-system,'Helvetica Neue',sans-serif;padding:4px;}}
.hd{{font-size:13px;font-weight:900;color:#fff;margin-bottom:8px;
     display:flex;align-items:center;gap:8px;}}
.stripe{{height:2px;margin-bottom:8px;border-radius:2px;
  background:linear-gradient(90deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]});}}
table{{width:100%;border-collapse:collapse;background:#0a0a0d;border-radius:14px;
  overflow:hidden;box-shadow:0 0 0 1px {pa[0]},0 0 40px {pa[1]};}}
th{{padding:9px 10px;text-align:left;color:{p[0]};font-weight:900;font-size:9px;
   letter-spacing:1px;text-transform:uppercase;border-bottom:2px solid {pm[0]};
   background:#0e0e12;text-shadow:0 0 14px {pa[0]};}}
tr:last-child td{{border-bottom:none!important;}}
</style></head>
<body>
<div class="hd">🎙 {heading}</div>
<div class="stripe"></div>
<table>
<thead><tr>
<th>#</th><th>Art</th><th>Podcast</th><th style="text-align:right;">Genre</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
{footer_html}
</body></html>""".strip()


# ══ Tool class ════════════════════════════════════════════════════════════════


class Tools:
    class Valves(BaseModel):
        COUNTRY_CODE: str = Field(
            default="us",
            description=(
                "2-letter ISO country code for Apple top-chart rankings "
                "(e.g. 'us', 'gb', 'ca', 'au', 'de'). Does not affect search."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Helper: find podcast + RSS ────────────────────────────────────────────

    async def _resolve_podcast(self, podcast_name: str):
        """Return (found_name, art_url, feed_url, meta, episodes) or raise."""
        async with aiohttp.ClientSession() as session:
            results = await _search_itunes(session, podcast_name, limit=5)

        if not results:
            raise LookupError(f"No podcast found matching '{podcast_name}'.")

        hit = results[0]
        feed_url = hit.get("feedUrl", "")
        name = hit.get("collectionName", podcast_name)
        art_url = hit.get("artworkUrl600") or hit.get("artworkUrl100") or ""

        if not feed_url:
            raise LookupError(
                f"No public RSS feed found for '{name}'. "
                "This podcast may restrict external access."
            )

        async with aiohttp.ClientSession() as session:
            meta, episodes = await _fetch_rss(session, feed_url)

        if not episodes:
            raise LookupError(f"No playable episodes found in '{name}'.")

        return name, art_url, feed_url, meta, episodes

    # ── Tool 1: play a specific episode ──────────────────────────────────────

    async def play_podcast(
        self,
        podcast_name: str,
        episode_query: str = "",
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Search for a podcast and stream an episode with a beautiful audio player.
        Supports the latest episode, a specific episode number, or an episode title keyword.
        :param podcast_name: Podcast to find, e.g. "Serial", "Radiolab", "Joe Rogan Experience"
        :param episode_query: Optional — episode number ("42"), or title keyword ("war of currents").
                              Leave blank or omit to play the latest episode.
        """
        await _emit(__event_emitter__, f"🎙 Searching for '{podcast_name}'…")

        try:
            found_name, art_url, _, meta, episodes = await self._resolve_podcast(
                podcast_name
            )
        except LookupError as exc:
            await _emit(__event_emitter__, "❌ Not found", done=True)
            return f"❌ {exc}"

        ep_idx, episode = _pick_episode(episodes, episode_query)
        ep_title = episode.get("title", "Unknown")

        await _emit(__event_emitter__, f"▶ Loading: {ep_title}…")

        art = meta.get("art") or art_url
        html = _build_player(found_name, episode, art, ep_idx, len(episodes))

        await _emit(__event_emitter__, f"▶ Now playing: {ep_title}", done=True)
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 2: search the directory ─────────────────────────────────────────

    async def search_podcasts(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Search the iTunes podcast directory and show a browsable results list.
        :param query: Search term — show name, topic, genre, or host, e.g. "true crime" or "Neil deGrasse Tyson"
        """
        await _emit(__event_emitter__, f"🔎 Searching podcasts for '{query}'…")

        async with aiohttp.ClientSession() as session:
            results = await _search_itunes(session, query, limit=15)

        if not results:
            await _emit(__event_emitter__, "No results", done=True)
            return f"❌ No podcasts found for '{query}'."

        html = _build_list_html(
            f'Search: "{query}"  ({len(results)} results)',
            results,
            footer_tip='Say "play podcast [name]" to listen · "random podcast episode [name]" for a surprise',
        )
        await _emit(__event_emitter__, f"✅ {len(results)} podcasts found", done=True)
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 3: top charts ────────────────────────────────────────────────────

    async def top_podcasts(
        self,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Show today's top 25 podcasts from Apple Podcasts charts.
        Country is controlled by the COUNTRY_CODE valve (default: us).
        """
        country = (self.valves.COUNTRY_CODE or "us").lower().strip()
        url = _APPLE_TOP_URL.format(country=country)
        await _emit(__event_emitter__, f"📊 Fetching top podcasts ({country.upper()})…")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=12)
                ) as r:
                    if r.status != 200:
                        raise RuntimeError(f"HTTP {r.status}")
                    d = await r.json(content_type=None)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Failed", done=True)
                return f"❌ Could not fetch top podcasts: {exc}"

        raw = d.get("feed", {}).get("results", [])
        if not raw:
            await _emit(__event_emitter__, "No data", done=True)
            return "❌ No top podcast data returned."

        # Normalise to the same field names used by _build_list_html
        items = []
        for r in raw:
            items.append(
                {
                    "collectionName": r.get("name", ""),
                    "artistName": r.get("artistName", ""),
                    "artworkUrl100": r.get("artworkUrl100", ""),
                    "genres": [g.get("name", "") for g in r.get("genres", [])],
                    "primaryGenreName": (r.get("genres") or [{}])[0].get("name", ""),
                }
            )

        html = _build_list_html(
            f"Top Podcasts — {country.upper()} today",
            items,
            footer_tip='Say "play podcast [name]" to listen',
        )
        await _emit(__event_emitter__, "✅ Top 25 loaded", done=True)
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 4: random episode ────────────────────────────────────────────────

    async def random_podcast_episode(
        self,
        podcast_name: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Pick a random episode from a podcast and start playing it — great for rediscovering a back-catalogue.
        :param podcast_name: Podcast to pick from, e.g. "Radiolab", "Planet Money", "99% Invisible"
        """
        await _emit(
            __event_emitter__, f"🎲 Finding a random episode from '{podcast_name}'…"
        )

        try:
            found_name, art_url, _, meta, episodes = await self._resolve_podcast(
                podcast_name
            )
        except LookupError as exc:
            await _emit(__event_emitter__, "❌ Not found", done=True)
            return f"❌ {exc}"

        ep_idx = random.randint(0, len(episodes) - 1)
        episode = episodes[ep_idx]
        ep_title = episode.get("title", "Unknown")

        await _emit(__event_emitter__, f"🎲 Picked: {ep_title}…")

        art = meta.get("art") or art_url
        html = _build_player(found_name, episode, art, ep_idx, len(episodes))

        await _emit(__event_emitter__, f"▶ Now playing: {ep_title}", done=True)
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})
