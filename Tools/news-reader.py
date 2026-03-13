"""
title: News Reader
description: >
  Fetch and display the latest news directly in chat from 45 hand-picked RSS feeds
  across 11 categories. Cards are fully expandable. The LLM can also fetch and
  summarize actual article content on demand — not just RSS snippets.

  Commands:
    - "latest news" / "top headlines"      → curated front page
    - "tech news", "AI news", etc.         → category feeds
    - "news about [topic]"                 → keyword search across all feeds
    - "summarize the latest [X] news"      → LLM reads articles and writes real summaries
    - "what's happening with [topic]"      → fetch + summarize matching articles

  Setup: No configuration needed — works out of the box.
  Valve: MAX_ARTICLES (default 15, max 40)

author: ichrist
version: 2.0.0
license: MIT
"""

import aiohttp
import asyncio
import logging
import re
import random
import json as _json
import html as _html_module
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional, Callable, Awaitable

from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  FEED CATALOGUE  ·  45 feeds, 11 categories
# ══════════════════════════════════════════════════════════════════════════════

FEEDS: dict = {
    "world": [
        {"name": "Reuters", "url": "https://feeds.reuters.com/reuters/topNews"},
        {"name": "AP News", "url": "https://feeds.apnews.com/rss/topnews"},
        {"name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    ],
    "tech": [
        {
            "name": "Ars Technica",
            "url": "https://feeds.arstechnica.com/arstechnica/index",
        },
        {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
        {"name": "Wired", "url": "https://www.wired.com/feed/rss"},
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
        {"name": "Hacker News", "url": "https://hnrss.org/frontpage"},
    ],
    "ai": [
        {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/"},
        {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/"},
        {"name": "The Decoder", "url": "https://the-decoder.com/feed/"},
        {
            "name": "Ars Technica",
            "url": "https://feeds.arstechnica.com/arstechnica/index",
        },
    ],
    "science": [
        {"name": "NASA", "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss"},
        {"name": "New Scientist", "url": "https://www.newscientist.com/feed/home/"},
        {"name": "Science Daily", "url": "https://www.sciencedaily.com/rss/all.xml"},
        {"name": "Phys.org", "url": "https://phys.org/rss-feed/"},
    ],
    "business": [
        {"name": "Financial Times", "url": "https://www.ft.com/rss/home/uk"},
        {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss"},
        {
            "name": "CNBC",
            "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        },
        {"name": "Forbes", "url": "https://www.forbes.com/business/feed/"},
    ],
    "sports": [
        {"name": "ESPN", "url": "https://www.espn.com/espn/rss/news"},
        {"name": "BBC Sport", "url": "http://feeds.bbci.co.uk/sport/rss.xml"},
        {"name": "Sky Sports", "url": "https://www.skysports.com/rss/12040"},
        {"name": "The Athletic", "url": "https://theathletic.com/rss/"},
    ],
    "gaming": [
        {"name": "IGN", "url": "https://feeds.feedburner.com/ign/all"},
        {"name": "Kotaku", "url": "https://kotaku.com/rss"},
        {"name": "PC Gamer", "url": "https://www.pcgamer.com/rss/"},
        {"name": "Eurogamer", "url": "https://www.eurogamer.net/feed"},
    ],
    "health": [
        {"name": "NHS UK", "url": "https://www.nhs.uk/news/feed.xml"},
        {"name": "MedicalNewsToday", "url": "https://www.medicalnewstoday.com/rss"},
        {"name": "WHO", "url": "https://www.who.int/feeds/entity/news/en/rss.xml"},
        {
            "name": "WebMD",
            "url": "https://rssfeeds.webmd.com/rss/rss.aspx?RSSSource=RSS_PUBLIC",
        },
    ],
    "politics": [
        {"name": "Politico", "url": "https://www.politico.com/rss/politicopicks.xml"},
        {"name": "The Hill", "url": "https://thehill.com/feed/"},
        {"name": "NPR Politics", "url": "https://feeds.npr.org/1014/rss.xml"},
        {
            "name": "BBC Politics",
            "url": "http://feeds.bbci.co.uk/news/politics/rss.xml",
        },
    ],
    "entertainment": [
        {"name": "Variety", "url": "https://variety.com/feed/"},
        {"name": "Deadline", "url": "https://deadline.com/feed/"},
        {"name": "Rolling Stone", "url": "https://www.rollingstone.com/feed/"},
        {"name": "The A.V. Club", "url": "https://www.avclub.com/rss"},
    ],
    "climate": [
        {
            "name": "The Guardian Env",
            "url": "https://www.theguardian.com/environment/rss",
        },
        {"name": "Carbon Brief", "url": "https://www.carbonbrief.org/feed"},
        {"name": "Inside Climate", "url": "https://insideclimatenews.org/feed/"},
        {"name": "ClimateWire", "url": "https://www.eenews.net/climatewire/rss"},
    ],
}

_KEYWORD_MAP: list = [
    (
        [
            "tech",
            "technology",
            "software",
            "hardware",
            "computer",
            "device",
            "app",
            "startup",
            "silicon valley",
            "coding",
            "developer",
        ],
        "tech",
    ),
    (
        [
            "ai",
            "artificial intelligence",
            "machine learning",
            "llm",
            "gpt",
            "openai",
            "deepmind",
            "chatgpt",
            "neural",
            "model",
            "robot",
        ],
        "ai",
    ),
    (
        [
            "science",
            "space",
            "nasa",
            "physics",
            "biology",
            "chemistry",
            "research",
            "study",
            "discovery",
            "universe",
            "planet",
            "star",
        ],
        "science",
    ),
    (
        [
            "business",
            "market",
            "stock",
            "finance",
            "economy",
            "trade",
            "investment",
            "wall street",
            "gdp",
            "inflation",
            "earnings",
            "ipo",
        ],
        "business",
    ),
    (
        [
            "sport",
            "sports",
            "football",
            "soccer",
            "basketball",
            "baseball",
            "nfl",
            "nba",
            "mlb",
            "tennis",
            "golf",
            "cricket",
            "rugby",
            "f1",
            "racing",
        ],
        "sports",
    ),
    (
        [
            "gaming",
            "game",
            "games",
            "video game",
            "xbox",
            "playstation",
            "nintendo",
            "steam",
            "esports",
            "twitch",
            "pc game",
            "console",
        ],
        "gaming",
    ),
    (
        [
            "health",
            "medical",
            "medicine",
            "hospital",
            "disease",
            "virus",
            "vaccine",
            "drug",
            "fitness",
            "mental health",
            "cancer",
            "diet",
        ],
        "health",
    ),
    (
        [
            "politic",
            "politics",
            "election",
            "government",
            "congress",
            "senate",
            "president",
            "democrat",
            "republican",
            "policy",
            "law",
            "vote",
            "white house",
            "parliament",
        ],
        "politics",
    ),
    (
        [
            "entertainment",
            "movie",
            "film",
            "tv",
            "television",
            "celebrity",
            "music",
            "album",
            "artist",
            "hollywood",
            "netflix",
            "oscar",
            "grammy",
        ],
        "entertainment",
    ),
    (
        [
            "climate",
            "environment",
            "global warming",
            "carbon",
            "fossil fuel",
            "renewable",
            "energy",
            "pollution",
            "ocean",
            "wildlife",
            "nature",
        ],
        "climate",
    ),
    (
        [
            "world",
            "global",
            "international",
            "breaking",
            "latest",
            "headline",
            "top news",
            "news today",
            "current events",
            "israel",
            "ukraine",
            "china",
            "russia",
            "strike",
            "war",
            "conflict",
        ],
        "world",
    ),
]

_FALLBACK_CAT = "world"

_CAT_ICONS = {
    "world": "🌍",
    "tech": "💻",
    "ai": "🤖",
    "science": "🔬",
    "business": "📈",
    "sports": "⚽",
    "gaming": "🎮",
    "health": "🩺",
    "politics": "🏛️",
    "entertainment": "🎬",
    "climate": "🌱",
}

# ══════════════════════════════════════════════════════════════════════════════
#  Utilities
# ══════════════════════════════════════════════════════════════════════════════


def _detect_category(text: str) -> str:
    t = text.lower()
    for keywords, cat in _KEYWORD_MAP:
        if any(k in t for k in keywords):
            return cat
    return _FALLBACK_CAT


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", " ", raw or "")
    raw = _html_module.unescape(raw)
    return " ".join(raw.split()).strip()


def _age_str(pub_date: str) -> str:
    if not pub_date:
        return ""
    try:
        try:
            dt = parsedate_to_datetime(pub_date)
        except Exception:
            dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 0:
            return "just now"
        if diff < 60:
            return f"{diff}s ago"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        d = diff // 86400
        return f"{d}d ago" if d < 30 else dt.strftime("%b %d")
    except Exception:
        return pub_date[:10] if len(pub_date) >= 10 else pub_date


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


_SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ══════════════════════════════════════════════════════════════════════════════
#  RSS fetching
# ══════════════════════════════════════════════════════════════════════════════


async def _fetch_feed(
    session: aiohttp.ClientSession,
    feed: dict,
    limit: int = 10,
    keyword: str = "",
) -> list:
    try:
        async with session.get(
            feed["url"],
            headers=_SESSION_HEADERS,
            timeout=aiohttp.ClientTimeout(total=12),
            ssl=False,
        ) as r:
            if r.status != 200:
                return []
            raw = await r.read()
    except Exception as exc:
        logger.debug(f"Feed fetch failed [{feed['name']}]: {exc}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    ns_atom = "http://www.w3.org/2005/Atom"
    ns_content = "http://purl.org/rss/1.0/modules/content/"
    items_rss = root.findall(".//item")
    items_atom = root.findall(f".//{{{ns_atom}}}entry")
    raw_items = items_rss or items_atom
    is_atom = bool(items_atom) and not items_rss
    kw_low = keyword.strip().lower()
    articles = []

    for item in raw_items:
        if len(articles) >= limit:
            break

        if is_atom:
            title = (item.findtext(f"{{{ns_atom}}}title") or "").strip()
            link_el = item.find(f"{{{ns_atom}}}link")
            link = link_el.get("href", "") if link_el is not None else ""
            body_raw = (
                item.findtext(f"{{{ns_atom}}}content")
                or item.findtext(f"{{{ns_atom}}}summary")
                or ""
            )
            pub = (
                item.findtext(f"{{{ns_atom}}}published")
                or item.findtext(f"{{{ns_atom}}}updated")
                or ""
            )
        else:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not link:
                lel = item.find("link")
                if lel is not None and lel.tail:
                    link = lel.tail.strip()
            body_raw = (
                item.findtext(f"{{{ns_content}}}encoded")
                or item.findtext("description")
                or ""
            )
            pub = item.findtext("pubDate") or ""

        title = _strip_html(title)
        summary = _strip_html(body_raw)

        if not title or not link:
            continue
        if kw_low and kw_low not in title.lower() and kw_low not in summary.lower():
            continue

        articles.append(
            {
                "source": feed["name"],
                "title": title,
                "link": link,
                "summary": summary,  # full RSS description — no truncation yet
                "age": _age_str(pub),
                "pub_raw": pub,
            }
        )

    return articles


async def _fetch_many(
    feeds: list,
    limit_per_feed: int = 8,
    total_limit: int = 15,
    keyword: str = "",
) -> list:
    conn = aiohttp.TCPConnector(ssl=False, limit=12)
    async with aiohttp.ClientSession(connector=conn) as session:
        tasks = [_fetch_feed(session, f, limit_per_feed, keyword) for f in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    merged = []
    for r in results:
        if isinstance(r, list):
            merged.extend(r)

    def _sort_key(a):
        age = a.get("age", "")
        if age.endswith("s ago"):
            return int(age[:-5].strip() or 0)
        if age.endswith("m ago"):
            return int(age[:-5].strip() or 0) * 60
        if age.endswith("h ago"):
            return int(age[:-5].strip() or 0) * 3600
        if age.endswith("d ago"):
            return int(age[:-5].strip() or 0) * 86400
        return 999_999_999

    merged.sort(key=_sort_key)
    return merged[:total_limit]


# ══════════════════════════════════════════════════════════════════════════════
#  Article text extractor  (used by summarize_news)
# ══════════════════════════════════════════════════════════════════════════════

_BOILERPLATE_RE = re.compile(
    r"(cookie|subscribe|sign up|newsletter|advertisement|©|copyright|"
    r"all rights reserved|privacy policy|terms of service|follow us|"
    r"share this|click here|read more|continue reading)",
    re.I,
)


async def _fetch_article_text(
    session: aiohttp.ClientSession, url: str, max_chars: int = 3000
) -> str:
    """Fetch a URL and extract readable body text (best-effort)."""
    try:
        async with session.get(
            url,
            headers=_SESSION_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
            allow_redirects=True,
        ) as r:
            if r.status != 200:
                return ""
            ct = r.headers.get("Content-Type", "")
            if "html" not in ct and "xml" not in ct and "text" not in ct:
                return ""
            raw = await r.text(errors="replace")
    except Exception as exc:
        logger.debug(f"Article fetch failed {url}: {exc}")
        return ""

    # Remove scripts, styles, nav, footer, header, aside, ads
    raw = re.sub(
        r"(?is)<(script|style|nav|footer|header|aside|figure|figcaption|form|button|select|noscript)[^>]*>.*?</\1>",
        " ",
        raw,
    )
    # Extract paragraph text
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", raw)
    text = " ".join(_strip_html(p) for p in paras)
    if len(text) < 200:
        # Fallback: strip all tags
        text = _strip_html(raw)

    # Remove boilerplate sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    clean = [s for s in sentences if not _BOILERPLATE_RE.search(s) and len(s) > 40]
    result = " ".join(clean)
    return result[:max_chars].strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Colour palette
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
#  HTML news card builder  —  expandable cards with full summary
# ══════════════════════════════════════════════════════════════════════════════


def _build_news_html(
    articles: list,
    heading: str,
    category: str,
    sources_used: list,
) -> str:
    p, pa, pm, pg = _vivid_palette()
    icon = _CAT_ICONS.get(category, "📰")

    # Source pills
    pills_html = ""
    for i, src in enumerate(sources_used[:8]):
        ci = i % 5
        pills_html += (
            f'<span class="pill" style="background:{pa[ci]};color:{p[ci]};border-color:{pm[ci]};">'
            f"{_html_module.escape(src)}</span>"
        )

    # Article cards — full summary stored in data-summary, revealed on expand
    cards_html = ""
    for i, art in enumerate(articles):
        ci = i % 5
        src = _html_module.escape(art.get("source", ""))
        title = _html_module.escape(art.get("title", "Unknown"))
        summary = art.get("summary", "")
        link = _html_module.escape(art.get("link", "#"))
        age = _html_module.escape(art.get("age", ""))

        # Truncated preview (2 lines) + full text for expand
        preview = _html_module.escape(
            summary[:180] + ("…" if len(summary) > 180 else "")
        )
        full = _html_module.escape(summary)
        has_more = len(summary) > 180

        age_badge = f'<span class="age">{age}</span>' if age else ""

        expand_btn = ""
        full_block = ""
        if has_more:
            expand_btn = (
                f'<button class="xbtn" id="xb{i}" onclick="tog({i})">'
                f'<span id="xl{i}">Read more</span>'
                f'<svg id="xa{i}" width="11" height="11" viewBox="0 0 24 24" fill="none" '
                f'stroke="currentColor" stroke-width="2.8" stroke-linecap="round">'
                f'<polyline points="6 9 12 15 18 9"/></svg>'
                f"</button>"
            )
            full_block = (
                f'<div class="full" id="fx{i}" style="display:none;">'
                f'<p class="fbody">{full}</p>'
                f"</div>"
            )

        cards_html += f"""
<div class="card" style="--cc:{p[ci]};--ca:{pa[ci]};--cm:{pm[ci]};--cg:{pg[ci]};
     animation-delay:{i * 0.045:.3f}s;" id="card{i}">

  <!-- Header row: badge + age + arrow link -->
  <div class="card-head">
    <div class="head-left">
      <span class="src-badge" style="background:{pa[ci]};color:{p[ci]};border-color:{pm[ci]};">{src}</span>
      {age_badge}
    </div>
    <a href="{link}" target="_blank" rel="noopener" class="ext-link" title="Open article">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
        <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
      </svg>
    </a>
  </div>

  <!-- Title (clickable to expand) -->
  <div class="ttl" onclick="tog({i})" style="cursor:pointer;">{title}</div>

  <!-- Preview (always visible) -->
  <p class="preview">{preview}</p>

  <!-- Full summary (hidden until expand) -->
  {full_block}

  <!-- Expand button + read link row -->
  <div class="card-foot">
    {expand_btn}
    <a href="{link}" target="_blank" rel="noopener" class="read-link">
      Full article
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <line x1="5" y1="12" x2="19" y2="12"/>
        <polyline points="12 5 19 12 12 19"/>
      </svg>
    </a>
  </div>
</div>"""

    cv = "".join(
        f"--c{i}:{p[i]};--ca{i}:{pa[i]};--cm{i}:{pm[i]};--cg{i}:{pg[i]};"
        for i in range(5)
    )
    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC · %b %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{{cv}}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:transparent;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;padding:4px;color:#e0e0e0;}}

/* ── Masthead ── */
.mast{{
  border-radius:14px;overflow:hidden;
  background:linear-gradient(160deg,#0d0d14 0%,#0a0a0e 100%);
  border:1px solid {pm[0]};
  box-shadow:0 0 0 1px {pa[0]},0 0 50px {pa[1]},0 0 100px {pa[3]};
  margin-bottom:10px;position:relative;
}}
.mast::before{{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:
    radial-gradient(ellipse 80% 120% at 0% 0%,{pa[0]} 0%,transparent 55%),
    radial-gradient(ellipse 60% 80% at 100% 100%,{pa[2]} 0%,transparent 60%);
}}
.stripe{{
  height:3px;
  background:linear-gradient(90deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[0]});
  background-size:300% 100%;animation:ss 3s linear infinite;
}}
@keyframes ss{{0%{{background-position:0%}}100%{{background-position:300%}}}}
.mast-inner{{padding:14px 18px 16px;position:relative;z-index:1;}}
.mast-top{{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-bottom:10px;}}
.mast-title{{font-size:22px;font-weight:900;letter-spacing:-.5px;color:#fff;text-shadow:0 2px 18px {pa[0]};display:flex;align-items:center;gap:8px;}}
.mast-time{{font-size:10px;color:#333;font-family:'SF Mono','Fira Code',monospace;letter-spacing:.5px;}}
.pills{{display:flex;flex-wrap:wrap;gap:5px;}}
.pill{{font-size:9px;font-weight:900;border:1px solid;padding:2px 10px;border-radius:20px;white-space:nowrap;letter-spacing:.3px;}}

/* ── Cards ── */
.feed{{display:flex;flex-direction:column;gap:7px;}}

.card{{
  background:linear-gradient(160deg,#0f0f16 0%,#0b0b12 100%);
  border:1px solid #1c1c26;
  border-left:3px solid var(--cc);
  border-radius:11px;
  padding:13px 15px 11px;
  position:relative;overflow:hidden;
  opacity:0;
  animation:fadeUp .38s ease forwards;
  transition:border-color .18s,box-shadow .18s,background .18s;
}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(7px)}}to{{opacity:1;transform:translateY(0)}}}}
.card::before{{
  content:'';position:absolute;inset:0;pointer-events:none;opacity:0;
  background:radial-gradient(ellipse 60% 70% at 0% 50%,var(--ca) 0%,transparent 55%);
  transition:opacity .2s;
}}
.card:hover{{border-color:var(--cc);background:linear-gradient(160deg,#131320 0%,#0e0e16 100%);box-shadow:0 0 0 1px var(--ca),0 2px 24px var(--ca);}}
.card:hover::before{{opacity:1;}}

/* Card header row */
.card-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:8px;}}
.head-left{{display:flex;align-items:center;gap:7px;flex-wrap:wrap;}}
.src-badge{{font-size:9px;font-weight:900;letter-spacing:.8px;text-transform:uppercase;border:1px solid;padding:2px 9px;border-radius:20px;white-space:nowrap;}}
.age{{font-size:10px;color:#3a3a4a;font-family:'SF Mono','Fira Code',monospace;white-space:nowrap;}}
.ext-link{{color:#2a2a3a;transition:color .15s;flex-shrink:0;display:flex;align-items:center;text-decoration:none;}}
.ext-link:hover{{color:var(--cc);}}

/* Title */
.ttl{{
  font-size:15px;font-weight:800;color:#cdd0d8;line-height:1.38;
  letter-spacing:-.15px;margin-bottom:7px;
  transition:color .15s;
}}
.ttl:hover{{color:#fff;}}

/* Preview text (always shown) */
.preview{{
  font-size:12.5px;color:#555;line-height:1.7;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;
  transition:all .2s;
}}
.preview.open{{
  -webkit-line-clamp:unset;overflow:visible;display:block;
  color:#6a6a7a;
}}

/* Full summary reveal */
.full{{margin-top:8px;padding-top:8px;border-top:1px solid var(--ca);}}
.fbody{{font-size:12.5px;color:#6a6a7a;line-height:1.75;}}

/* Footer row */
.card-foot{{display:flex;align-items:center;justify-content:space-between;margin-top:10px;gap:8px;flex-wrap:wrap;}}
.xbtn{{
  display:inline-flex;align-items:center;gap:4px;
  font-size:10px;font-weight:900;letter-spacing:.5px;
  color:var(--cc);background:var(--ca);border:1px solid var(--cm);
  padding:3px 10px;border-radius:20px;cursor:pointer;
  transition:all .15s;white-space:nowrap;
}}
.xbtn:hover{{background:var(--cm);color:#000;}}
.xbtn svg{{transition:transform .2s;}}
.xbtn.open svg{{transform:rotate(180deg);}}
.read-link{{
  display:inline-flex;align-items:center;gap:4px;
  font-size:10px;font-weight:800;color:#2e2e42;
  text-decoration:none;letter-spacing:.3px;
  transition:color .15s;
}}
.read-link:hover{{color:var(--cc);}}

/* Footer */
.foot{{text-align:center;font-size:10px;color:#1e1e28;margin-top:8px;padding-bottom:2px;letter-spacing:.3px;}}
</style>
</head>
<body>

<div class="mast">
  <div class="stripe"></div>
  <div class="mast-inner">
    <div class="mast-top">
      <div class="mast-title">{icon} {_html_module.escape(heading)}</div>
      <div class="mast-time">{now_str}</div>
    </div>
    <div class="pills">{pills_html}</div>
  </div>
</div>

<div class="feed">
{cards_html}
</div>

<div class="foot">{len(articles)} articles — click any headline or "Read more" to expand</div>

<script>
function tog(i) {{
  var preview = document.querySelector('#card' + i + ' .preview');
  var full    = document.getElementById('fx' + i);
  var btn     = document.getElementById('xb' + i);
  var lbl     = document.getElementById('xl' + i);
  var isOpen  = btn && btn.classList.contains('open');

  if (preview) preview.classList.toggle('open', !isOpen);
  if (full)    full.style.display  = isOpen ? 'none'  : 'block';
  if (btn)     btn.classList.toggle('open',   !isOpen);
  if (lbl)     lbl.textContent    = isOpen ? 'Read more' : 'Collapse';

  postH();
}}

function postH() {{
  try {{
    window.parent.postMessage(
      {{type:'iframe-resize', id:'newsreader', height: document.documentElement.scrollHeight}},
      '*'
    );
  }} catch(e) {{}}
}}

setTimeout(postH, 120);
window.addEventListener('load', function() {{ setTimeout(postH, 300); }});
</script>
</body>
</html>""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tool class
# ══════════════════════════════════════════════════════════════════════════════


class Tools:
    class Valves(BaseModel):
        MAX_ARTICLES: int = Field(
            default=15,
            description="Maximum articles to show per request (5–40).",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _limit(self) -> int:
        return max(5, min(40, self.valves.MAX_ARTICLES))

    # ── Tool 1: get_news — auto-routes by category keyword ───────────────────

    async def get_news(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Fetch and display the latest news for any topic or category as an interactive
        card feed. Each card shows headline + preview and expands to the full summary.
        Handles: "tech news", "latest sports headlines", "AI news", "latest news",
        "business news", "science news", "gaming news", "health news", "politics news",
        "entertainment news", "climate news", "latest usa and israel strikes news", etc.
        :param query: Natural-language news request, e.g. "tech news" or "latest world news"
        """
        cat = _detect_category(query)
        feeds = FEEDS.get(cat, FEEDS["world"])
        icon = _CAT_ICONS.get(cat, "📰")
        label = cat.title()

        await _emit(__event_emitter__, f"{icon} Fetching {label} news…")

        lim = self._limit()
        articles = await _fetch_many(feeds, limit_per_feed=8, total_limit=lim)

        if not articles:
            await _emit(__event_emitter__, "❌ No articles retrieved", done=True)
            return (
                f"❌ Could not load {label} news right now. "
                "Feeds may be temporarily unavailable — please try again."
            )

        sources = list(dict.fromkeys(a["source"] for a in articles))
        html = _build_news_html(articles, f"{label} News", cat, sources)

        await _emit(
            __event_emitter__, f"✅ {len(articles)} {label} headlines loaded", done=True
        )
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 2: top_headlines — curated multi-source front page ──────────────

    async def top_headlines(
        self,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Show a curated cross-category front page with the most important stories right now
        — world news, tech, business, science, and health combined.
        Use for: "top headlines", "front page", "what's happening", "news roundup".
        """
        await _emit(__event_emitter__, "📰 Building front page from multiple sources…")

        cats = ["world", "tech", "business", "science", "health"]
        lim = self._limit()
        per_cat = max(2, lim // len(cats))
        feeds = []
        for cat in cats:
            feeds.extend(FEEDS[cat][:2])

        articles = await _fetch_many(feeds, limit_per_feed=per_cat, total_limit=lim)

        if not articles:
            await _emit(__event_emitter__, "❌ No articles", done=True)
            return "❌ Could not load headlines right now — please try again."

        sources = list(dict.fromkeys(a["source"] for a in articles))
        html = _build_news_html(articles, "Top Headlines", "world", sources)

        await _emit(
            __event_emitter__, f"✅ {len(articles)} top stories loaded", done=True
        )
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 3: search_news — keyword filter across all feeds ─────────────────

    async def search_news(
        self,
        keyword: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Search for news articles containing a specific keyword or phrase across all 45 feeds.
        Use for: "news about [topic]", "articles about [person/event/company]".
        :param keyword: Word or phrase to filter by, e.g. "SpaceX", "Bitcoin", "Gaza", "Trump"
        """
        if not keyword.strip():
            return "❌ Please provide a keyword to search for."

        await _emit(__event_emitter__, f"🔎 Searching all feeds for '{keyword}'…")

        all_feeds = [f for feeds in FEEDS.values() for f in feeds]
        seen: set = set()
        unique = []
        for f in all_feeds:
            if f["url"] not in seen:
                seen.add(f["url"])
                unique.append(f)

        lim = self._limit()
        articles = await _fetch_many(
            unique, limit_per_feed=5, total_limit=lim, keyword=keyword.strip()
        )

        if not articles:
            await _emit(__event_emitter__, f"No results for '{keyword}'", done=True)
            return (
                f"❌ No articles found mentioning **{keyword}** right now. "
                "Try a broader term, or check back as feeds refresh."
            )

        sources = list(dict.fromkeys(a["source"] for a in articles))
        html = _build_news_html(articles, f'News: "{keyword}"', "world", sources)

        await _emit(
            __event_emitter__, f"✅ {len(articles)} results for '{keyword}'", done=True
        )
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 4: summarize_news — FETCHES real article text for LLM to read ───

    async def summarize_news(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        Fetch the latest news articles for a topic AND retrieve the actual full text of each
        article so the AI can write a real, detailed summary — not just a headline list.
        Use when the user asks to SUMMARIZE, EXPLAIN, BRIEF, or RECAP recent news on any topic.
        Examples: "summarize the latest AI news", "brief me on tech news today",
        "what's happening with the Israel war", "give me a news summary about climate",
        "summarize US politics today", "what's going on with [topic]".
        :param query: Topic or category to summarize, e.g. "AI news", "Israel conflict", "tech today"
        """
        cat = _detect_category(query)
        feeds = FEEDS.get(cat, FEEDS["world"])
        label = cat.title()

        await _emit(__event_emitter__, f"🔍 Fetching {label} headlines…")

        # Step 1: get RSS articles (fewer items, richer content needed)
        articles = await _fetch_many(feeds, limit_per_feed=5, total_limit=8)

        if not articles:
            await _emit(__event_emitter__, "❌ No articles", done=True)
            return f"❌ Could not retrieve {label} news right now."

        # Step 2: concurrently fetch full article text for up to 6 articles
        await _emit(__event_emitter__, f"📖 Reading {min(len(articles), 6)} articles…")

        conn = aiohttp.TCPConnector(ssl=False, limit=6)
        async with aiohttp.ClientSession(connector=conn) as session:
            fetch_tasks = [
                _fetch_article_text(session, a["link"], max_chars=2500)
                for a in articles[:6]
            ]
            texts = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Step 3: build a rich context string for the LLM
        blocks = []
        for i, (art, body) in enumerate(zip(articles[:6], texts)):
            if isinstance(body, Exception):
                body = ""
            rss_summary = art.get("summary", "")
            content = body if len(body) > len(rss_summary) else rss_summary
            content = content[:2000].strip()

            blocks.append(
                f"--- Article {i+1} ---\n"
                f"Source:    {art['source']}\n"
                f"Published: {art.get('age', 'unknown')}\n"
                f"Title:     {art['title']}\n"
                f"URL:       {art['link']}\n"
                f"Content:\n{content}"
            )

        context = "\n\n".join(blocks)

        await _emit(
            __event_emitter__, f"✅ Ready — summarizing {label} news", done=True
        )

        # Return the raw text so the LLM (caller) uses it to write the summary
        return (
            f"Here is the full content of the {len(blocks)} most recent {label} news articles "
            f"fetched right now. Use this to write a comprehensive, well-structured summary "
            f"for the user. Group related stories, highlight the most important developments, "
            f"and mention sources. Do not just list headlines — write real paragraphs.\n\n"
            f"{context}"
        )
