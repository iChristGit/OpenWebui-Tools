"""
title: HLTV CS2 Hub
description: Live scores, upcoming matches, results, news, team search, rankings and tournaments from HLTV.org — the world's leading CS2 stats platform.
author: ichrist
version: 2.0.0
license: MIT
requirements: curl-cffi, beautifulsoup4
"""

import random
import re
import time
from datetime import datetime
from typing import Awaitable, Callable, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE = "https://www.hltv.org"
_CHROME_VERSIONS = ["chrome120", "chrome124", "chrome131"]
_EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.hltv.org/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# ---------------------------------------------------------------------------
# HTTP helper  (unchanged)
# ---------------------------------------------------------------------------


def _get(url: str, timeout: int = 20) -> BeautifulSoup:
    last_exc: Exception = RuntimeError("No attempts made")
    for impersonate in random.sample(_CHROME_VERSIONS, len(_CHROME_VERSIONS)):
        try:
            with cffi_requests.Session(impersonate=impersonate) as s:
                resp = s.get(
                    url, headers=_EXTRA_HEADERS, timeout=timeout, allow_redirects=True
                )
                resp.raise_for_status()
                return BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            last_exc = exc
            time.sleep(0.6)
    raise last_exc


def _debug_classes(soup: BeautifulSoup, limit: int = 80) -> str:
    classes = set()
    for tag in soup.find_all(True):
        for c in tag.get("class", []):
            classes.add(c)
            if len(classes) >= limit:
                return ", ".join(sorted(classes))
    return ", ".join(sorted(classes))


# ---------------------------------------------------------------------------
# URL-pattern parsers  (unchanged)
# ---------------------------------------------------------------------------

_MATCH_URL_RE = re.compile(
    r"^/matches/(\d+)/([a-z0-9][a-z0-9\-]*?)-vs-([a-z0-9][a-z0-9\-]*?)(?:-(.+))?$"
)


def _slug_to_name(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-"))


def _parse_matches_from_links(
    soup: BeautifulSoup, team_filter: Optional[str] = None
) -> list:
    seen = set()
    matches = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _MATCH_URL_RE.match(href)
        if not m:
            continue
        match_id, t1_slug, t2_slug, ev_slug = m.groups()
        if match_id in seen:
            continue
        seen.add(match_id)

        t1 = _slug_to_name(t1_slug)
        t2 = _slug_to_name(t2_slug)
        event = _slug_to_name(ev_slug) if ev_slug else "Unknown Event"

        if team_filter:
            q = team_filter.lower()
            if q not in t1.lower() and q not in t2.lower():
                continue

        time_str = ""
        score_str = ""
        node = a.parent
        for _ in range(5):
            if node is None:
                break
            text = node.get_text(" ", strip=True)
            if not time_str:
                t = re.search(r"\b(\d{1,2}:\d{2})\b", text)
                if t:
                    time_str = t.group(1)
            if not score_str:
                sc = re.search(r"\b(\d+)\s*[-–]\s*(\d+)\b", text)
                if sc:
                    score_str = f"{sc.group(1)} - {sc.group(2)}"
            if time_str or score_str:
                break
            node = node.parent

        matches.append(
            {
                "id": match_id,
                "team1": t1,
                "team2": t2,
                "event": event,
                "href": BASE + href,
                "time": time_str,
                "score": score_str,
            }
        )
    return matches


# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# CSS — v2: CS2 TACTICAL BROADCAST THEME
# Rajdhani (military/esports display) + JetBrains Mono (scores/stats)
# Color palette: near-black + HLTV orange + cold blue accent
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&family=DM+Sans:opsz,wght@9..40,400;9..40,500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg0: #07070d;
  --bg1: #0c0c16;
  --bg2: #10101e;
  --bg3: #141425;
  --line: #1c1c2e;
  --line2: #242438;
  --line3: #2e2e4a;
  --txt: #dde0f0;
  --txt2: #9095b8;
  --dim: #525578;
  --dim2: #303350;
  --orange: #ff6b00;
  --orange2: #e45f00;
  --orange3: #ff9140;
  --glow: rgba(255,107,0,.45);
  --glow2: rgba(255,107,0,.08);
  --blue: #4fc3f7;
  --blue2: #0288d1;
  --green: #00e676;
  --red: #ff4d6a;
  --gold: #ffd740;
}

/* ── CARD SHELL ─────────────────────────────────────────── */
.hv {
  font-family: 'DM Sans', system-ui, sans-serif;
  background: var(--bg0);
  color: var(--txt);
  width: 100%;
  border-radius: 14px;
  padding: 20px 22px 18px;
  border: 1px solid var(--line2);
  box-shadow: 0 20px 60px rgba(0,0,0,.9),
              inset 0 1px 0 rgba(255,107,0,.06);
  position: relative;
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
  color-scheme: dark;
}

/* top accent line */
.hv::before {
  content: '';
  position: absolute;
  top: 0; left: 6%; right: 6%; height: 1px;
  background: linear-gradient(90deg,
    transparent,
    var(--orange2) 25%,
    var(--orange) 50%,
    var(--orange2) 75%,
    transparent);
  filter: blur(.3px);
}

/* subtle crosshair watermark */
.hv::after {
  content: '✛';
  position: absolute;
  bottom: 14px; right: 18px;
  font-size: 1.8rem;
  color: var(--dim2);
  opacity: .25;
  pointer-events: none;
  font-family: 'JetBrains Mono', monospace;
}

/* ── HEADER ─────────────────────────────────────────────── */
.hv-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 13px;
  margin-bottom: 15px;
  border-bottom: 1px solid var(--line);
}
.hv-hd h2 {
  font-family: 'Rajdhani', sans-serif;
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--orange);
  text-shadow: 0 0 22px var(--glow), 0 0 50px rgba(255,107,0,.12);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 9px;
}
.hv-hd time {
  font-family: 'JetBrains Mono', monospace;
  font-size: .6rem;
  color: var(--dim);
  background: var(--bg2);
  padding: 3px 10px;
  border-radius: 20px;
  border: 1px solid var(--line2);
  letter-spacing: .5px;
}

/* ── MATCH CARD ─────────────────────────────────────────── */
.hv-match {
  background: linear-gradient(135deg, var(--bg1) 0%, var(--bg2) 100%);
  border: 1px solid var(--line);
  border-radius: 10px;
  margin: 7px 0;
  overflow: hidden;
  transition: border-color .18s, transform .15s, box-shadow .15s;
  text-decoration: none;
  display: block;
  color: inherit;
}
.hv-match:hover {
  border-color: var(--line3);
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(0,0,0,.4);
}

/* match meta bar */
.hv-match-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 13px 4px;
  border-bottom: 1px solid var(--line);
  background: rgba(0,0,0,.2);
}
.hv-event-name {
  font-size: .6rem;
  font-weight: 600;
  color: var(--dim);
  letter-spacing: .4px;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

/* match body: team | score | team */
.hv-match-body {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 13px 16px 11px;
  gap: 10px;
}

.hv-team {
  display: flex;
  align-items: center;
  gap: 9px;
}
.hv-team.right {
  flex-direction: row-reverse;
  text-align: right;
}
.hv-team-icon {
  width: 34px; height: 34px;
  background: var(--bg3);
  border: 1px solid var(--line2);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: .65rem;
  font-weight: 700;
  color: var(--orange3);
  flex-shrink: 0;
  letter-spacing: -.5px;
}
.hv-team-name {
  font-family: 'Rajdhani', sans-serif;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: .4px;
  text-transform: uppercase;
  color: var(--txt);
  line-height: 1.1;
}
.hv-team-name.winner { color: var(--orange); text-shadow: 0 0 12px var(--glow); }
.hv-team-name.loser  { color: var(--dim); }

/* center block */
.hv-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  min-width: 110px;
}
.hv-score-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.9rem;
  font-weight: 700;
  color: var(--txt);
  letter-spacing: -1px;
  line-height: 1;
}
.hv-score-val .dash { color: var(--dim); padding: 0 4px; font-size: 1.3rem; }
.hv-vs {
  font-family: 'Rajdhani', sans-serif;
  font-size: .95rem;
  font-weight: 700;
  color: var(--dim2);
  letter-spacing: 3px;
}
.hv-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: .7rem;
  color: var(--orange3);
  letter-spacing: .5px;
  margin-top: 1px;
}
.hv-badge {
  font-family: 'Rajdhani', sans-serif;
  font-size: .55rem;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 2px 9px;
  border-radius: 20px;
  border: 1px solid;
  margin-bottom: 2px;
}
.hv-badge.live  { color: var(--red); border-color: var(--red); background: rgba(255,77,106,.1); }
.hv-badge.done  { color: var(--dim); border-color: var(--line2); background: var(--bg3); }
.hv-badge.soon  { color: var(--orange); border-color: var(--orange2); background: var(--glow2); }
.hv-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--red);
  display: inline-block; margin-right: 4px;
  box-shadow: 0 0 6px var(--red); animation: hvpulse 1.1s ease-in-out infinite; }
@keyframes hvpulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.2;transform:scale(.5)} }

/* ── RANK ROW ────────────────────────────────────────────── */
.hv-rank {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--bg1);
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 10px 14px;
  margin: 5px 0;
  transition: border-color .15s;
}
.hv-rank:hover { border-color: var(--line3); }
.hv-rank-pos {
  font-family: 'Rajdhani', sans-serif;
  font-size: 1.3rem;
  font-weight: 700;
  min-width: 38px;
  text-align: center;
  color: var(--orange);
}
.hv-rank-pos.top1  { color: var(--gold); text-shadow: 0 0 14px rgba(255,215,64,.4); }
.hv-rank-pos.top3  { color: var(--orange3); }
.hv-rank-icon {
  width: 30px; height: 30px;
  background: var(--bg3);
  border: 1px solid var(--line2);
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: .55rem;
  font-weight: 700;
  color: var(--orange3);
  flex-shrink: 0;
}
.hv-rank-name {
  flex: 1;
  font-family: 'Rajdhani', sans-serif;
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: .3px;
  color: var(--txt);
}
.hv-rank-pts {
  font-family: 'JetBrains Mono', monospace;
  font-size: .72rem;
  color: var(--dim);
  letter-spacing: .3px;
}

/* ── NEWS ITEM ───────────────────────────────────────────── */
.hv-news {
  background: var(--bg1);
  border: 1px solid var(--line);
  border-left: 3px solid var(--orange2);
  border-radius: 9px;
  padding: 11px 14px;
  margin: 6px 0;
  transition: border-color .15s;
}
.hv-news:hover { border-color: var(--line3); border-left-color: var(--orange); }
.hv-news a {
  font-family: 'Rajdhani', sans-serif;
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: .2px;
  color: var(--blue);
  text-decoration: none;
  line-height: 1.4;
}
.hv-news a:hover { color: var(--orange3); }
.hv-news .hv-date {
  font-family: 'JetBrains Mono', monospace;
  font-size: .62rem;
  color: var(--dim);
  margin-top: 5px;
  letter-spacing: .3px;
}

/* ── EVENT CARD ──────────────────────────────────────────── */
.hv-event {
  background: var(--bg1);
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 11px 14px;
  margin: 6px 0;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: border-color .15s;
}
.hv-event:hover { border-color: var(--line3); }
.hv-event-icon {
  width: 34px; height: 34px;
  background: linear-gradient(135deg, var(--orange2), var(--orange));
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex-shrink: 0;
}
.hv-event-body { flex: 1; min-width: 0; }
.hv-event-name a {
  font-family: 'Rajdhani', sans-serif;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: .3px;
  color: var(--txt);
  text-decoration: none;
}
.hv-event-name a:hover { color: var(--orange3); }
.hv-event-dates {
  font-family: 'JetBrains Mono', monospace;
  font-size: .62rem;
  color: var(--dim);
  margin-top: 3px;
  letter-spacing: .2px;
}

/* ── SECTION DIVIDER ─────────────────────────────────────── */
.hv-sec {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: 'Rajdhani', sans-serif;
  font-size: .72rem;
  font-weight: 700;
  color: var(--orange2);
  text-transform: uppercase;
  letter-spacing: 3px;
  margin: 20px 0 10px;
  padding-bottom: 7px;
  border-bottom: 1px solid var(--line);
}
.hv-sec::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--line2), transparent);
}

/* ── EMPTY STATE ─────────────────────────────────────────── */
.hv-empty {
  color: var(--dim);
  font-size: .85rem;
  padding: 22px 16px;
  text-align: center;
  border: 1px dashed var(--line2);
  border-radius: 10px;
  margin: 10px 0;
  background: var(--bg1);
}

/* ── DEBUG BLOCK ─────────────────────────────────────────── */
.hv-debug {
  font-family: 'JetBrains Mono', monospace;
  font-size: .6rem;
  color: var(--dim);
  background: var(--bg3);
  border: 1px solid var(--line);
  padding: 8px 10px;
  border-radius: 7px;
  margin-top: 10px;
  word-break: break-all;
  line-height: 1.7;
}

/* ── FOOTER ──────────────────────────────────────────────── */
.hv-ft {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  border-top: 1px solid var(--line);
  padding-top: 9px;
  gap: 8px;
}
.hv-ft-source {
  font-family: 'JetBrains Mono', monospace;
  font-size: .58rem;
  color: var(--dim2);
  letter-spacing: .3px;
}
.hv-ft-brand {
  font-family: 'Rajdhani', sans-serif;
  font-weight: 700;
  font-size: .72rem;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--orange2);
}

@media (max-width: 480px) {
  .hv-match-body { padding: 11px 12px 9px; gap: 6px; }
  .hv-center { min-width: 80px; }
  .hv-score-val { font-size: 1.5rem; }
  .hv-team-name { font-size: .92rem; }
  .hv { padding: 14px 14px 14px; }
}
"""


# ---------------------------------------------------------------------------
# HTML card helpers
# ---------------------------------------------------------------------------


def _abbrev(name: str) -> str:
    """Turn 'Team Vitality' → 'TV', 'NaVi' → 'NV', etc."""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def _card(title: str, body: str, icon: str = "🎮", debug: str = "") -> str:
    ts = datetime.utcnow().strftime("%H:%M UTC")
    dbg = f'<div class="hv-debug">🔧 Debug: {debug}</div>' if debug else ""
    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{_CSS}</style></head><body>"
        f'<div class="hv">'
        f'<div class="hv-hd"><h2>{icon} {title}</h2>'
        f"<time>{ts}</time></div>"
        f"{body}{dbg}"
        f'<div class="hv-ft">'
        f'<span class="hv-ft-source">source: hltv.org</span>'
        f'<span class="hv-ft-brand">⚡ HLTV CS2 Hub v2</span>'
        f"</div></div>"
        "</body></html>"
    )


def _html(content: str) -> "HTMLResponse":
    return HTMLResponse(content=content, headers={"content-disposition": "inline"})


def _match_row(m: dict) -> str:
    """Render a single match as a broadcast-style card."""
    t1 = m["team1"]
    t2 = m["team2"]
    event = m["event"]
    score = m["score"]
    mtime = m["time"]
    href = m["href"]

    # Determine what to show in center
    if score:
        # parse sides  "16 - 7"  →  left=16, right=7
        parts = re.split(r"\s*[-–]\s*", score)
        if len(parts) == 2:
            l, r = parts
            try:
                lv, rv = int(l), int(r)
                l_cls = "winner" if lv > rv else ("loser" if lv < rv else "")
                r_cls = "winner" if rv > lv else ("loser" if rv < lv else "")
            except ValueError:
                l_cls = r_cls = ""
        else:
            l = r = score
            l_cls = r_cls = ""
        badge = '<span class="hv-badge done">FINAL</span>'
        center_inner = (
            f"{badge}"
            f'<div class="hv-score-val">'
            f'<span class="{l_cls}">{l}</span>'
            f'<span class="dash"> – </span>'
            f'<span class="{r_cls}">{r}</span>'
            f"</div>"
        )
    elif mtime:
        badge = '<span class="hv-badge soon">UPCOMING</span>'
        center_inner = (
            f"{badge}"
            f'<div class="hv-vs">VS</div>'
            f'<div class="hv-time">{mtime} UTC</div>'
        )
    else:
        center_inner = '<div class="hv-vs">VS</div>'

    a1 = _abbrev(t1)
    a2 = _abbrev(t2)

    return (
        f'<a class="hv-match" href="{href}" target="_blank" rel="noopener">'
        f'<div class="hv-match-meta">'
        f'<span class="hv-event-name">🏆 {event}</span>'
        f"</div>"
        f'<div class="hv-match-body">'
        # left team
        f'<div class="hv-team">'
        f'<div class="hv-team-icon">{a1}</div>'
        f'<div class="hv-team-name">{t1}</div>'
        f"</div>"
        # center
        f'<div class="hv-center">{center_inner}</div>'
        # right team
        f'<div class="hv-team right">'
        f'<div class="hv-team-name">{t2}</div>'
        f'<div class="hv-team-icon">{a2}</div>'
        f"</div>"
        f"</div>"
        f"</a>"
    )


# ---------------------------------------------------------------------------
# EventEmitter
# ---------------------------------------------------------------------------


class EventEmitter:
    def __init__(self, emitter: Callable[[dict], Awaitable[None]]):
        self._emit = emitter

    async def status(self, msg: str, done: bool = False):
        await self._emit({"type": "status", "data": {"description": msg, "done": done}})

    async def done(self, msg: str = "Done"):
        await self.status(msg, done=True)


# ---------------------------------------------------------------------------
# Tools  (scraping logic entirely unchanged — only renders differ)
# ---------------------------------------------------------------------------


class Tools:
    class Valves(BaseModel):
        timeout: int = Field(default=20, description="HTTP timeout in seconds.")
        max_items: int = Field(default=15, description="Max items per query.")
        debug: bool = Field(
            default=False,
            description="When True, appends raw page class names to empty results.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------
    # 1. Upcoming & Live Matches
    # ------------------------------------------------------------------

    async def get_matches(
        self,
        team: Optional[str] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get upcoming and live CS2 matches from HLTV. Optionally filter by team name.
        Use when user asks about upcoming/live matches — e.g. "show upcoming matches",
        "is Vitality playing today", "what matches are live".

        :param team: Optional team name filter e.g. "Vitality", "NaVi", "G2".
        """
        ee = EventEmitter(__event_emitter__) if __event_emitter__ else None
        try:
            if ee:
                await ee.status("🔍 Fetching HLTV matches…")

            soup = _get(f"{BASE}/matches", timeout=self.valves.timeout)
            matches = _parse_matches_from_links(soup, team_filter=team)
            matches = matches[: self.valves.max_items]

            if not matches:
                dbg = _debug_classes(soup) if self.valves.debug else ""
                msg = f"No upcoming matches found{' for **' + team + '**' if team else ''}."
                if ee:
                    await ee.done(msg)
                return _html(
                    _card(
                        "Upcoming Matches",
                        f'<div class="hv-empty">{msg}</div>',
                        "📅",
                        dbg,
                    )
                )

            rows = "".join(_match_row(m) for m in matches)
            title = f"Upcoming Matches — {team}" if team else "Upcoming Matches"
            if ee:
                await ee.done(f"Found {len(matches)} match(es).")
            return _html(_card(title, rows, "📅"))

        except Exception as exc:
            err = f"❌ Could not fetch matches: {exc}"
            if ee:
                await ee.done(err)
            return err

    # ------------------------------------------------------------------
    # 2. Recent Results
    # ------------------------------------------------------------------

    async def get_results(
        self,
        team: Optional[str] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get recent CS2 match results from HLTV. Optionally filter by team.
        Use when user asks about recent results or scores — e.g.
        "latest results", "did Vitality win", "show recent scores".

        :param team: Optional team name filter e.g. "Vitality", "G2".
        """
        ee = EventEmitter(__event_emitter__) if __event_emitter__ else None
        try:
            if ee:
                await ee.status("🔍 Fetching recent results…")

            soup = _get(f"{BASE}/results", timeout=self.valves.timeout)
            matches = _parse_matches_from_links(soup, team_filter=team)
            matches = matches[: self.valves.max_items]

            if not matches:
                dbg = _debug_classes(soup) if self.valves.debug else ""
                msg = (
                    f"No recent results found{' for **' + team + '**' if team else ''}."
                )
                if ee:
                    await ee.done(msg)
                return _html(
                    _card(
                        "Recent Results",
                        f'<div class="hv-empty">{msg}</div>',
                        "🏆",
                        dbg,
                    )
                )

            rows = "".join(_match_row(m) for m in matches)
            title = f"Recent Results — {team}" if team else "Recent Results"
            if ee:
                await ee.done(f"Found {len(matches)} result(s).")
            return _html(_card(title, rows, "🏆"))

        except Exception as exc:
            err = f"❌ Could not fetch results: {exc}"
            if ee:
                await ee.done(err)
            return err

    # ------------------------------------------------------------------
    # 3. Latest News
    # ------------------------------------------------------------------

    async def get_news(
        self,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get the latest CS2 news from HLTV.
        Use when user asks about news, transfers, announcements — e.g.
        "latest CS2 news", "any transfers today", "HLTV news".
        """
        ee = EventEmitter(__event_emitter__) if __event_emitter__ else None
        try:
            if ee:
                await ee.status("📰 Fetching HLTV news…")

            soup = _get(f"{BASE}/", timeout=self.valves.timeout)
            rows = []
            seen = set()

            _news_re = re.compile(r"^/news/(\d+)/[a-z0-9\-]+$")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not _news_re.match(href):
                    continue
                title_txt = a.get_text(strip=True)
                if not title_txt or len(title_txt) < 8 or href in seen:
                    continue
                seen.add(href)

                date_txt = ""
                for node in [a.parent, a.parent.parent if a.parent else None]:
                    if node:
                        d = re.search(
                            r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\w{3,9} \d{1,2},? \d{4})\b",
                            node.get_text(),
                        )
                        if d:
                            date_txt = d.group(1)
                            break

                rows.append(
                    f'<div class="hv-news">'
                    f'<a href="{BASE + href}" target="_blank" rel="noopener">{title_txt}</a>'
                    f'<div class="hv-date">{date_txt}</div>'
                    f"</div>"
                )
                if len(rows) >= self.valves.max_items:
                    break

            if not rows:
                dbg = _debug_classes(soup) if self.valves.debug else ""
                if ee:
                    await ee.done("No news found.")
                return _html(
                    _card(
                        "Latest CS2 News",
                        '<div class="hv-empty">No articles found.</div>',
                        "📰",
                        dbg,
                    )
                )

            if ee:
                await ee.done(f"Found {len(rows)} articles.")
            return _html(_card("Latest CS2 News", "".join(rows), "📰"))

        except Exception as exc:
            err = f"❌ Could not fetch news: {exc}"
            if ee:
                await ee.done(err)
            return err

    # ------------------------------------------------------------------
    # 4. Rankings
    # ------------------------------------------------------------------

    async def get_rankings(
        self,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get the current HLTV CS2 world team rankings.
        Use when user asks about rankings, best teams — e.g.
        "CS2 rankings", "who is #1", "top 10 teams".
        """
        ee = EventEmitter(__event_emitter__) if __event_emitter__ else None
        try:
            if ee:
                await ee.status("🏅 Fetching team rankings…")

            soup = _get(f"{BASE}/ranking/teams", timeout=self.valves.timeout)
            rows = []

            # Strategy 1: classic selectors
            ranked_items = (
                soup.select(".ranked-team")
                or soup.select("[class*='ranked-team']")
                or soup.select("[class*='rankingTeam']")
            )

            if ranked_items:
                for idx, ranked in enumerate(ranked_items[: self.valves.max_items], 1):
                    pos = (
                        ranked.select_one(".position")
                        or ranked.select_one("[class*='position']")
                        or ranked.select_one("[class*='Position']")
                    )
                    name = (
                        ranked.select_one(".name")
                        or ranked.select_one("[class*='teamName']")
                        or ranked.select_one("[class*='name']")
                    )
                    pts = ranked.select_one(".points") or ranked.select_one(
                        "[class*='point']"
                    )
                    if not name:
                        continue
                    pos_txt = pos.get_text(strip=True) if pos else f"#{idx}"
                    name_txt = name.get_text(strip=True)
                    pts_txt = pts.get_text(strip=True) if pts else ""
                    pos_cls = "top1" if idx == 1 else ("top3" if idx <= 3 else "")
                    abbr = _abbrev(name_txt)
                    rows.append(
                        f'<div class="hv-rank">'
                        f'<div class="hv-rank-pos {pos_cls}">{pos_txt}</div>'
                        f'<div class="hv-rank-icon">{abbr}</div>'
                        f'<div class="hv-rank-name">{name_txt}</div>'
                        f'<div class="hv-rank-pts">{pts_txt}</div>'
                        f"</div>"
                    )
            else:
                # Strategy 2: URL-based fallback
                _team_re = re.compile(r"^/team/\d+/[a-z0-9\-]+$")
                seen = set()
                idx = 0
                for a in soup.find_all("a", href=True):
                    if not _team_re.match(a["href"]):
                        continue
                    team_name = a.get_text(strip=True)
                    if not team_name or team_name in seen:
                        continue
                    seen.add(team_name)
                    idx += 1

                    pos = ""
                    node = a.parent
                    for _ in range(6):
                        if node is None:
                            break
                        p = re.search(r"(?<!\d)(\d{1,2})(?!\d)", node.get_text())
                        if p and 1 <= int(p.group(1)) <= 50:
                            pos = f"#{p.group(1)}"
                            break
                        node = node.parent

                    pos_cls = "top1" if idx == 1 else ("top3" if idx <= 3 else "")
                    abbr = _abbrev(team_name)
                    rows.append(
                        f'<div class="hv-rank">'
                        f'<div class="hv-rank-pos {pos_cls}">{pos or f"#{idx}"}</div>'
                        f'<div class="hv-rank-icon">{abbr}</div>'
                        f'<div class="hv-rank-name">{team_name}</div>'
                        f'<div class="hv-rank-pts"></div>'
                        f"</div>"
                    )
                    if len(rows) >= self.valves.max_items:
                        break

            if not rows:
                dbg = _debug_classes(soup) if self.valves.debug else ""
                if ee:
                    await ee.done("No rankings found.")
                return _html(
                    _card(
                        "CS2 Rankings",
                        '<div class="hv-empty">Could not load rankings.</div>',
                        "🥇",
                        dbg,
                    )
                )

            if ee:
                await ee.done(f"Loaded {len(rows)} ranked teams.")
            return _html(_card("CS2 World Team Rankings", "".join(rows), "🥇"))

        except Exception as exc:
            err = f"❌ Could not fetch rankings: {exc}"
            if ee:
                await ee.done(err)
            return err

    # ------------------------------------------------------------------
    # 5. Events / Tournaments
    # ------------------------------------------------------------------

    async def get_events(
        self,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get upcoming and ongoing CS2 tournaments from HLTV.
        Use when user asks about tournaments, events, majors — e.g.
        "upcoming CS2 events", "when is the next major".
        """
        ee = EventEmitter(__event_emitter__) if __event_emitter__ else None
        try:
            if ee:
                await ee.status("🗓️ Fetching upcoming events…")

            soup = _get(f"{BASE}/events", timeout=self.valves.timeout)
            rows = []
            seen = set()

            _ev_re = re.compile(r"^/events/\d+/[a-z0-9\-]+$")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not _ev_re.match(href):
                    continue
                ev_name = a.get_text(strip=True)
                if not ev_name or len(ev_name) < 3 or ev_name in seen:
                    continue
                seen.add(ev_name)

                meta = ""
                node = a.parent
                for _ in range(4):
                    if node is None:
                        break
                    d = re.search(
                        r"[A-Z][a-z]{2,8} \d{1,2}.*?\d{4}",
                        node.get_text(" ", strip=True),
                    )
                    if d:
                        meta = d.group(0)[:70]
                        break
                    node = node.parent

                rows.append(
                    f'<div class="hv-event">'
                    f'<div class="hv-event-icon">🏆</div>'
                    f'<div class="hv-event-body">'
                    f'<div class="hv-event-name"><a href="{BASE + href}" target="_blank" rel="noopener">{ev_name}</a></div>'
                    f'<div class="hv-event-dates">{meta}</div>'
                    f"</div>"
                    f"</div>"
                )
                if len(rows) >= self.valves.max_items:
                    break

            if not rows:
                dbg = _debug_classes(soup) if self.valves.debug else ""
                if ee:
                    await ee.done("No events found.")
                return _html(
                    _card(
                        "Upcoming Events",
                        '<div class="hv-empty">No events found.</div>',
                        "🏟️",
                        dbg,
                    )
                )

            if ee:
                await ee.done(f"Found {len(rows)} events.")
            return _html(
                _card("Upcoming CS2 Events & Tournaments", "".join(rows), "🏟️")
            )

        except Exception as exc:
            err = f"❌ Could not fetch events: {exc}"
            if ee:
                await ee.done(err)
            return err

    # ------------------------------------------------------------------
    # 6. Team Profile
    # ------------------------------------------------------------------

    async def search_team(
        self,
        team: str,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Show upcoming matches and recent results for a specific CS2 team.
        Use when user asks about a specific team — "tell me about Vitality",
        "FaZe schedule", "how is NaVi doing".

        :param team: Team name e.g. "Vitality", "NaVi", "G2", "FaZe".
        """
        ee = EventEmitter(__event_emitter__) if __event_emitter__ else None
        try:
            if ee:
                await ee.status(f"🔎 Looking up {team}…")

            # Fetch both concurrently-ish (sequential since we have no asyncio gather here)
            soup_up = _get(f"{BASE}/matches", timeout=self.valves.timeout)
            soup_res = _get(f"{BASE}/results", timeout=self.valves.timeout)

            upcoming = _parse_matches_from_links(soup_up, team_filter=team)[
                : self.valves.max_items
            ]
            results = _parse_matches_from_links(soup_res, team_filter=team)[
                : self.valves.max_items
            ]

            parts = []
            if upcoming:
                parts.append('<div class="hv-sec">📅 Upcoming Matches</div>')
                parts.extend(_match_row(m) for m in upcoming)
            else:
                parts.append(
                    '<div class="hv-sec">📅 Upcoming Matches</div>'
                    f'<div class="hv-empty">No upcoming matches found for {team}.</div>'
                )

            if results:
                parts.append('<div class="hv-sec">🏆 Recent Results</div>')
                parts.extend(_match_row(m) for m in results)
            else:
                parts.append(
                    '<div class="hv-sec">🏆 Recent Results</div>'
                    f'<div class="hv-empty">No recent results found for {team}.</div>'
                )

            if ee:
                await ee.done(f"Loaded hub for {team}.")
            return _html(_card(f"Team Hub — {team}", "".join(parts), "🎯"))

        except Exception as exc:
            err = f"❌ Could not load team '{team}': {exc}"
            if ee:
                await ee.done(err)
            return err
