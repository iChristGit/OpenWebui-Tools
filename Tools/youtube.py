"""
title: YouTube Player
description: >
  Watch YouTube videos, browse search results, and get AI-powered summaries — directly in chat.
  Search powered by YouTube's own InnerTube API (fast, no key needed).
  Likes/dislikes loaded client-side via Return YouTube Dislike API.
  Transcripts fetched via youtube-transcript-api (fast, reliable).

  Commands:
    - "I need a tutorial on X" / "show me a video about X"   → embed best result with stats
    - "search youtube for X"                                  → browse 8 results
    - "summarize this youtube video: [url]"                   → transcript + AI recap
    - "get transcript of [url]"                              → full transcript text
    - "play [youtube url]"                                   → embed a specific video

  Valves:
    YOUTUBE_API_KEY    — YouTube Data API v3 key (optional, improves search accuracy)
    INVIDIOUS_INSTANCE — Preferred Invidious instance for transcripts (optional)

requirements: youtube-transcript-api
author: ichrist
version: 2.4.0
license: MIT
"""

import aiohttp
import asyncio
import json
import logging
import re
import random
import html as _html
from typing import Any, Optional, Callable, Awaitable
from urllib.parse import urlencode

from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════════════════════

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.privacyredirect.com",
    "https://yt.artemislena.eu",
    "https://invidious.nerdvpn.de",
    "https://iv.melmac.space",
]

_SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# InnerTube — YouTube's own internal API (~200-400ms, no key needed)
_INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/search"
_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"  # public web key
_INNERTUBE_CLIENT = {
    "clientName": "WEB",
    "clientVersion": "2.20240101.00.00",
    "hl": "en",
    "gl": "US",
}

# ANDROID client for /player endpoint — bypasses bot-detection and returns
# captionTracks with signed baseUrl values that actually resolve correctly.
_ANDROID_UA = "com.google.android.youtube/19.44.38 (Linux; U; Android 11) gzip"
_INNERTUBE_ANDROID_CLIENT = {
    "clientName": "ANDROID",
    "clientVersion": "19.44.38",
    "androidSdkVersion": 30,
    "userAgent": _ANDROID_UA,
    "hl": "en",
    "gl": "US",
}
_INNERTUBE_PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"

_HUE_FAMILIES = [
    (0, 18),
    (25, 50),
    (90, 130),
    (155, 175),
    (175, 200),
    (250, 280),
    (300, 330),
    (330, 355),
]

RYDA_URL = "https://returnyoutubedislikeapi.com/votes?videoId={}"
YT_EMBED = "https://www.youtube-nocookie.com/embed/{}?rel=0&modestbranding=1"
YT_WATCH = "https://www.youtube.com/watch?v={}"
# ══════════════════════════════════════════════════════════════════════════════
#  InnerTube search  (direct, fast, no third-party proxy)
# ══════════════════════════════════════════════════════════════════════════════


def _parse_duration_text(txt: str) -> int:
    """'12:34' or '1:23:45' → seconds."""
    parts = (txt or "").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        pass
    return 0


def _parse_view_count(txt: str) -> int:
    """'1,234,567 views' → int."""
    digits = re.sub(r"[^\d]", "", (txt or ""))
    return int(digits) if digits else 0


def _innertube_extract_videos(data: dict, limit: int) -> list:
    """Walk the InnerTube search response and pull out video cards."""
    videos = []
    try:
        sections = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )
        for section in sections:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                vr = item.get("videoRenderer", {})
                if not vr:
                    continue
                vid_id = vr.get("videoId", "")
                if not vid_id:
                    continue

                title = vr.get("title", {}).get("runs", [{}])[0].get("text", "")
                channel = vr.get("ownerText", {}).get("runs", [{}])[0].get("text", "")
                duration_txt = vr.get("lengthText", {}).get("simpleText", "") or vr.get(
                    "lengthText", {}
                ).get("accessibility", {}).get("accessibilityData", {}).get("label", "")
                view_txt = vr.get("viewCountText", {}).get("simpleText", "") or vr.get(
                    "viewCountText", {}
                ).get("runs", [{}])[0].get("text", "")
                pub_txt = vr.get("publishedTimeText", {}).get("simpleText", "")
                thumbs = vr.get("thumbnail", {}).get("thumbnails", [])

                videos.append(
                    {
                        "videoId": vid_id,
                        "title": title,
                        "author": channel,
                        "lengthSeconds": _parse_duration_text(duration_txt),
                        "viewCount": _parse_view_count(view_txt),
                        "publishedText": pub_txt,
                        "videoThumbnails": [
                            {"url": t.get("url", ""), "quality": "medium"}
                            for t in thumbs
                        ],
                    }
                )
                if len(videos) >= limit:
                    return videos
    except Exception as exc:
        logger.debug(f"InnerTube parse error: {exc}")
    return videos


async def _innertube_search(
    session: aiohttp.ClientSession, query: str, limit: int = 8
) -> list:
    """Search via YouTube's own InnerTube API — fast, no key, no proxy."""
    payload = {
        "query": query,
        "context": {"client": _INNERTUBE_CLIENT},
        "params": "CAISAhAB",  # filter: videos only
    }
    try:
        async with session.post(
            _INNERTUBE_URL,
            params={"key": _INNERTUBE_KEY, "prettyPrint": "false"},
            json=payload,
            headers={**_SESSION_HEADERS, "Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=6),
            ssl=False,
        ) as r:
            if r.status != 200:
                logger.warning(f"InnerTube returned HTTP {r.status}")
                return []
            data = await r.json(content_type=None)
        return _innertube_extract_videos(data, limit)
    except Exception as exc:
        logger.warning(f"InnerTube search failed: {exc}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  Colour palette  (same vivid engine as News Reader & Podcast Player)
# ══════════════════════════════════════════════════════════════════════════════


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
#  Utilities
# ══════════════════════════════════════════════════════════════════════════════


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


def _extract_video_id(text: str) -> str:
    """Extract 11-char YouTube video ID from any URL or bare ID."""
    m = re.search(
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/watch\?v=)([a-zA-Z0-9_-]{11})",
        text,
    )
    if m:
        return m.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{11}$", text.strip()):
        return text.strip()
    return ""


def _fmt_count(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "—"
    if n <= 0:
        return "—"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_duration(seconds) -> str:
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    h, r = divmod(s, 3600)
    m, sc = divmod(r, 60)
    return f"{h}:{m:02d}:{sc:02d}" if h else f"{m}:{sc:02d}"


def _parse_iso_duration(d: str) -> int:
    """Parse ISO 8601 duration (PT4M13S) → seconds."""
    if not d:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0
    return (
        int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
    )


# ══════════════════════════════════════════════════════════════════════════════
#  API helpers
# ══════════════════════════════════════════════════════════════════════════════


def _dedup_ordered(items):
    """Return list with duplicates removed while preserving order."""
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


async def _invidious_request(
    session, path: str, params: dict, preferred: str = ""
) -> Any:
    """Try Invidious instances in priority order until one responds."""
    instances = _dedup_ordered([preferred] + INVIDIOUS_INSTANCES)
    for base in instances:
        try:
            async with session.get(
                f"{base}{path}",
                params=params,
                timeout=aiohttp.ClientTimeout(total=8),
                ssl=False,
            ) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
        except Exception as exc:
            logger.debug(f"Invidious {base}{path} failed: {exc}")
    return None


async def _yt_api(session, path: str, params: dict, api_key: str) -> Any:
    """Call YouTube Data API v3."""
    params = {**params, "key": api_key}
    try:
        async with session.get(
            f"https://www.googleapis.com/youtube/v3{path}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status == 200:
                return await r.json(content_type=None)
    except Exception as exc:
        logger.error(f"YouTube API {path} error: {exc}")
    return None


async def _get_ryda(session, video_id: str) -> dict:
    """Return YouTube Dislike API — {likes, dislikes, viewCount, rating, …}"""
    try:
        async with session.get(
            RYDA_URL.format(video_id),
            timeout=aiohttp.ClientTimeout(total=6),
        ) as r:
            if r.status == 200:
                return await r.json(content_type=None)
    except Exception:
        pass
    return {}


# ══════════════════════════════════════════════════════════════════════════════
#  Transcript fetching
# ══════════════════════════════════════════════════════════════════════════════


def _parse_vtt(vtt: str) -> str:
    """Parse WebVTT captions → clean plain text."""
    result = []
    for line in vtt.splitlines():
        if "-->" in line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d+$", line.strip()):
            continue
        text = re.sub(r"<[^>]+>", "", line)
        text = _html.unescape(text).strip()
        if text and len(text) > 1:
            result.append(text)
    # Deduplicate consecutive identical lines (VTT often repeats)
    deduped, prev = [], None
    for line in result:
        if line != prev:
            deduped.append(line)
        prev = line
    return " ".join(deduped)


def _parse_json3(data: dict) -> str:
    """Parse YouTube json3 timedtext format → plain text."""
    parts = []
    for ev in data.get("events", []):
        for seg in ev.get("segs", []):
            t = seg.get("utf8", "").replace("\n", " ")
            if t.strip():
                parts.append(t)
    return " ".join(" ".join(parts).split())


def _pick_best_caption_track(tracks: list) -> dict | None:
    """Return the best caption track: English manual > English auto > any manual > any."""
    if not tracks:
        return None

    def priority(t):
        lang = t.get("languageCode", "")
        is_asr = t.get("kind", "") == "asr"
        if lang.startswith("en") and not is_asr:
            return 0
        if lang.startswith("en"):
            return 1
        if not is_asr:
            return 2
        return 3

    return min(tracks, key=priority)


async def _fetch_caption_url(session, base_url: str) -> str:
    """Download a caption baseUrl (+ &fmt=json3) and return clean text."""
    url = re.sub(r"&fmt=[^&]*", "", base_url) + "&fmt=json3"
    try:
        async with session.get(
            url,
            headers=_SESSION_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
        ) as r:
            if r.status != 200:
                return ""
            d = await r.json(content_type=None)
            return _parse_json3(d)
    except Exception as exc:
        logger.debug(f"Caption URL fetch failed: {exc}")
        return ""


async def _transcript_via_innertube_player(session, video_id: str) -> str:
    """
    Primary transcript method (2025+).

    Calls the InnerTube /player endpoint with the ANDROID client context.
    The ANDROID client is much less aggressively bot-detected than WEB and
    returns full captionTracks with signed baseUrl tokens baked in — these
    tokens are what the old bare ?v=ID&lang=en endpoint was missing.
    """
    payload = {
        "videoId": video_id,
        "context": {"client": _INNERTUBE_ANDROID_CLIENT},
    }
    try:
        async with session.post(
            _INNERTUBE_PLAYER_URL,
            params={"key": _INNERTUBE_KEY, "prettyPrint": "false"},
            json=payload,
            headers={
                **_SESSION_HEADERS,
                "Content-Type": "application/json",
                "User-Agent": _ANDROID_UA,
            },
            timeout=aiohttp.ClientTimeout(total=10),
            ssl=False,
        ) as r:
            if r.status != 200:
                logger.debug(f"InnerTube /player returned HTTP {r.status}")
                return ""
            data = await r.json(content_type=None)
    except Exception as exc:
        logger.debug(f"InnerTube /player request failed: {exc}")
        return ""

    tracks = (
        data.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    )
    if not tracks:
        logger.debug(f"No captionTracks in InnerTube /player response for {video_id}")
        return ""

    track = _pick_best_caption_track(tracks)
    if not track or not track.get("baseUrl"):
        return ""

    return await _fetch_caption_url(session, track["baseUrl"])


async def _transcript_via_watch_page(session, video_id: str) -> str:
    """
    Secondary transcript method.

    Fetches the YouTube watch page, extracts ytInitialPlayerResponse from the
    inline script, then uses the captionTracks baseUrl from there.  Slower
    than the InnerTube /player call (~500 KB page) but a solid fallback.
    """
    try:
        async with session.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers=_SESSION_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
        ) as r:
            if r.status != 200:
                return ""
            html = await r.text()
    except Exception as exc:
        logger.debug(f"Watch page fetch failed: {exc}")
        return ""

    # Extract ytInitialPlayerResponse JSON blob
    m = re.search(
        r"ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;?\s*(?:var\s+\w|<\/script)",
        html,
        re.DOTALL,
    )
    if not m:
        logger.debug("ytInitialPlayerResponse not found in watch page HTML")
        return ""

    try:
        player = json.loads(m.group(1))
    except Exception:
        return ""

    tracks = (
        player.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    )
    track = _pick_best_caption_track(tracks)
    if not track or not track.get("baseUrl"):
        return ""

    return await _fetch_caption_url(session, track["baseUrl"])


async def _transcript_via_invidious(session, video_id: str, preferred: str = "") -> str:
    """Last-resort: fetch caption URL via Invidious captions API."""
    instances = _dedup_ordered([preferred] + INVIDIOUS_INSTANCES)
    for base in instances:
        try:
            async with session.get(
                f"{base}/api/v1/captions/{video_id}",
                timeout=aiohttp.ClientTimeout(total=8),
                ssl=False,
            ) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)

            tracks = data.get("captions", [])
            if not tracks:
                continue
            en = next(
                (t for t in tracks if t.get("languageCode", "").startswith("en")),
                tracks[0],
            )
            cap_url = en.get("url", "")
            if not cap_url:
                continue
            if cap_url.startswith("/"):
                cap_url = base + cap_url
            if "fmt=" not in cap_url:
                cap_url += "&fmt=vtt"

            async with session.get(
                cap_url, timeout=aiohttp.ClientTimeout(total=15), ssl=False
            ) as r:
                if r.status != 200:
                    continue
                raw = await r.text()
                parsed = _parse_vtt(raw)
                if parsed and len(parsed) > 100:
                    return parsed
        except Exception as exc:
            logger.debug(f"Invidious captions {base} failed: {exc}")
    return ""


async def _get_transcript(session, video_id: str, preferred: str = "") -> str:
    """
    Fetch a transcript for the given video ID.

    Priority order (fastest / most reliable first):
      1. youtube-transcript-api library  — direct, fast, handles all CC types
      2. InnerTube /player (ANDROID)     — signed baseUrl tokens, no bot-detection
      3. Watch-page scrape               — heavy fallback (~500 KB page)
      4. Invidious captions API          — last resort
    """

    # ── 1. youtube-transcript-api (primary) ──────────────────────────────────
    # Uses the new object-based API introduced in youtube-transcript-api 0.6+.
    # Snippet objects expose .text / .start / .duration attributes (not dicts).
    try:
        from youtube_transcript_api import (  # type: ignore
            YouTubeTranscriptApi,
            TranscriptsDisabled,
            NoTranscriptFound,
        )

        def _fetch_lib():
            ytt = YouTubeTranscriptApi()
            # Try English variants first, then accept any available language
            for langs in (["en", "en-US", "en-GB", "en-CA", "en-AU"], None):
                try:
                    snippets = (
                        ytt.fetch(video_id, languages=langs)
                        if langs
                        else ytt.fetch(video_id)
                    )
                    return " ".join(
                        getattr(
                            s, "text", s.get("text", "") if isinstance(s, dict) else ""
                        ).replace("\n", " ")
                        for s in snippets
                    ).strip()
                except (TranscriptsDisabled, NoTranscriptFound):
                    if langs is None:
                        raise
                    continue
            return ""

        text = await asyncio.to_thread(_fetch_lib)
        if text and len(text) > 100:
            return text
    except Exception as exc:
        logger.debug(f"youtube-transcript-api failed: {exc}")

    # ── 2. InnerTube ANDROID /player ─────────────────────────────────────────
    t = await _transcript_via_innertube_player(session, video_id)
    if t and len(t) > 100:
        return t

    # ── 3. Watch-page scrape ─────────────────────────────────────────────────
    t = await _transcript_via_watch_page(session, video_id)
    if t and len(t) > 100:
        return t

    # ── 4. Invidious — last resort ───────────────────────────────────────────
    return await _transcript_via_invidious(session, video_id, preferred)


# ══════════════════════════════════════════════════════════════════════════════
#  HTML: YouTube-style Video Player
# ══════════════════════════════════════════════════════════════════════════════


def _build_player_html(
    video_id: str,
    title: str,
    channel: str,
    view_count: int,
    published: str,
    description: str,
    duration: str,
    invidious_base: str = "",
) -> str:
    yt_url = YT_WATCH.format(video_id)
    embed_url = YT_EMBED.format(video_id)

    safe_title = _html.escape(title or "Unknown Title")
    safe_channel = _html.escape(channel or "Unknown Channel")
    safe_pub = _html.escape(published or "")
    safe_desc = _html.escape((description or "")[:1200])
    if len(description or "") > 1200:
        safe_desc += "\u2026"

    views = _fmt_count(view_count) if view_count else ""
    views_str = f"{views} views" if views else ""
    meta_parts = [x for x in [views_str, safe_pub] if x]
    meta_str = "  \u00b7  ".join(meta_parts)
    dur_str = _html.escape(duration or "")
    has_desc = bool((description or "").strip())

    dur_chip = f'<div class="chip">\u23f1 {dur_str}</div>' if dur_str else ""
    view_chip = (
        (
            f'<div class="chip">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">'
            f'<path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11'
            f" 11-7.5c-1.73-4.39-6-7.5-11-7.5zm0 12.5c-2.76 0-5-2.24-5-5s2.24-5 5-5"
            f" 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34"
            f' 3-3-1.34-3-3-3z"/></svg> {views_str}</div>'
        )
        if views_str
        else ""
    )

    if has_desc:
        desc_section = (
            f'<div class="desc-wrap">'
            f'<button class="desc-toggle" id="dtog" onclick="togDesc()">'
            f"<span>Description</span>"
            f'<svg class="arr" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">'
            f'<path d="M7 10l5 5 5-5z"/></svg>'
            f"</button>"
            f'<div class="desc-body" id="desc-body"><p>{safe_desc}</p></div>'
            f"</div>"
        )
    else:
        desc_section = f'<div style="padding:8px 0 14px;font-size:12px;color:#717171;">{meta_str}</div>'

    # Pre-compute download attrs — backslashes not allowed inside f-strings

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<style>\n"
        "*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}\n"
        "html,body{\n"
        "  background:transparent;\n"
        '  font-family:-apple-system,"Helvetica Neue",Roboto,Arial,sans-serif;\n'
        "  color:#f1f1f1;font-size:14px;line-height:1.5;\n"
        "}\n"
        ".yt{background:#0f0f0f;border-radius:12px;overflow:hidden;border:1px solid #272727;}\n"
        ".vid{position:relative;width:100%;padding-top:56.25%;background:#000;}\n"
        ".vid iframe{position:absolute;inset:0;width:100%;height:100%;border:none;}\n"
        ".info{padding:12px 14px 4px;}\n"
        ".vtitle{font-size:16px;font-weight:600;color:#f1f1f1;line-height:1.4;margin-bottom:12px;}\n"
        ".ch-row{display:flex;align-items:center;gap:10px;padding-bottom:12px;border-bottom:1px solid #272727;flex-wrap:wrap;}\n"
        ".ch-avatar{width:36px;height:36px;border-radius:50%;background:#272727;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:16px;}\n"
        ".ch-info{flex:1;min-width:0;}\n"
        ".ch-name{font-size:14px;font-weight:600;color:#f1f1f1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}\n"
        ".ch-sub{font-size:12px;color:#aaa;margin-top:1px;}\n"
        ".sub-btn{margin-left:auto;background:#f1f1f1;color:#0f0f0f;border:none;border-radius:18px;font-size:13px;font-weight:700;padding:8px 16px;cursor:default;white-space:nowrap;flex-shrink:0;}\n"
        ".action-bar{display:flex;align-items:center;gap:6px;padding:10px 0;border-bottom:1px solid #272727;flex-wrap:wrap;}\n"
        ".like-pill{display:inline-flex;align-items:center;background:#272727;border-radius:18px;overflow:hidden;}\n"
        ".lbtn{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;font-size:13px;font-weight:500;color:#f1f1f1;white-space:nowrap;}\n"
        ".lbtn:first-child{border-right:1px solid #3d3d3d;}\n"
        ".ratio-wrap{display:flex;flex-direction:column;justify-content:center;gap:3px;padding:0 4px;}\n"
        ".ratio-label{font-size:10px;color:#717171;white-space:nowrap;}\n"
        ".ratio-track{width:72px;height:3px;background:#3d3d3d;border-radius:2px;overflow:hidden;}\n"
        ".ratio-fill{height:100%;background:#f1f1f1;border-radius:2px;width:50%;transition:width .5s;}\n"
        ".chip{display:inline-flex;align-items:center;gap:5px;background:#272727;border-radius:18px;color:#f1f1f1;font-size:13px;font-weight:500;padding:7px 14px;white-space:nowrap;}\n"
        ".yt-btn{display:inline-flex;align-items:center;gap:7px;background:#272727;border:1px solid #404040;color:#f1f1f1;border-radius:18px;font-size:13px;font-weight:600;padding:7px 16px;text-decoration:none;white-space:nowrap;transition:background .15s;margin-left:auto;}\n"
        ".yt-btn:hover{background:#3d3d3d;}\n"
        ".yt-btn .yt-logo{flex-shrink:0;}\n"
        ".desc-wrap{padding:10px 0 14px;}\n"
        ".desc-toggle{display:inline-flex;align-items:center;gap:4px;background:none;border:none;color:#f1f1f1;font-size:13px;font-weight:600;cursor:pointer;padding:0;}\n"
        ".arr{transition:transform .2s;}\n"
        ".arr.open{transform:rotate(180deg);}\n"
        ".desc-body{display:none;margin-top:10px;font-size:13px;color:#aaa;line-height:1.75;white-space:pre-wrap;word-break:break-word;}\n"
        ".desc-body.open{display:block;}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="yt">\n'
        '  <div class="vid">\n'
        f'    <iframe src="{embed_url}"\n'
        '      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"\n'
        "      allowfullscreen></iframe>\n"
        "  </div>\n"
        '  <div class="info">\n'
        f'    <div class="vtitle" style="margin-top:12px;">{safe_title}</div>\n'
        '    <div class="ch-row">\n'
        '      <div class="ch-avatar">\u25b6</div>\n'
        '      <div class="ch-info">\n'
        f'        <div class="ch-name">{safe_channel}</div>\n'
        f'        <div class="ch-sub">{meta_str}</div>\n'
        "      </div>\n"
        '      <button class="sub-btn">Subscribe</button>\n'
        "    </div>\n"
        '    <div class="action-bar">\n'
        '      <div class="like-pill">\n'
        '        <div class="lbtn">\n'
        '          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">\n'
        '            <path d="M1 21h4V9H1v12zM23 10c0-1.1-.9-2-2-2h-6.3l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/>\n'
        "          </svg>\n"
        '          <span id="yt-likes">&mdash;</span>\n'
        "        </div>\n"
        '        <div class="lbtn">\n'
        '          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="transform:scaleY(-1)">\n'
        '            <path d="M1 21h4V9H1v12zM23 10c0-1.1-.9-2-2-2h-6.3l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/>\n'
        "          </svg>\n"
        '          <span id="yt-dislikes">&mdash;</span>\n'
        "        </div>\n"
        "      </div>\n"
        '      <div class="ratio-wrap">\n'
        '        <div class="ratio-label" id="yt-ratio-label"></div>\n'
        '        <div class="ratio-track"><div class="ratio-fill" id="yt-ratio"></div></div>\n'
        "      </div>\n"
        f"      {view_chip}\n"
        f"      {dur_chip}\n"
        f'      <a class="yt-btn" href="{yt_url}" target="_blank" rel="noopener">\n'
        '        <svg class="yt-logo" width="18" height="13" viewBox="0 0 18 13" fill="none">\n'
        '          <rect width="18" height="13" rx="3" fill="#FF0000"/>\n'
        '          <polygon points="7,3 7,10 13,6.5" fill="#fff"/>\n'
        "        </svg>\n"
        "        Watch on YouTube\n"
        "      </a>\n"
        "    </div>\n"
        f"    {desc_section}\n"
        "  </div>\n"
        "</div>\n"
        "<script>\n"
        "(function(){\n"
        f'  var VID="{video_id}";\n'
        "  function fmt(n){\n"
        '    if(!n||n<=0)return"\u2014";\n'
        '    if(n>=1e9)return(n/1e9).toFixed(1)+"B";\n'
        '    if(n>=1e6)return(n/1e6).toFixed(1)+"M";\n'
        '    if(n>=1e3)return(n/1e3).toFixed(1)+"K";\n'
        "    return n.toLocaleString();\n"
        "  }\n"
        '  fetch("https://returnyoutubedislikeapi.com/votes?videoId="+VID)\n'
        "    .then(function(r){return r.ok?r.json():null;})\n"
        "    .then(function(d){\n"
        "      if(!d)return;\n"
        "      var l=d.likes||0,dl=d.dislikes||0,t=Math.max(l+dl,1);\n"
        "      var pct=(l/t*100).toFixed(0);\n"
        '      var el=document.getElementById("yt-likes");\n'
        '      var ed=document.getElementById("yt-dislikes");\n'
        '      var er=document.getElementById("yt-ratio");\n'
        '      var rl=document.getElementById("yt-ratio-label");\n'
        "      if(el)el.textContent=fmt(l);\n"
        "      if(ed)ed.textContent=fmt(dl);\n"
        '      if(er)er.style.width=pct+"%";\n'
        '      if(rl)rl.textContent=pct+"% liked";\n'
        "    }).catch(function(){});\n"
        "  window.togDesc=function(){\n"
        '    var b=document.getElementById("desc-body");\n'
        '    var a=document.querySelector(".arr");\n'
        '    if(b)b.classList.toggle("open");\n'
        '    if(a)a.classList.toggle("open");\n'
        "    ph();\n"
        "  };\n"
        "  function ph(){\n"
        '    try{window.parent.postMessage({type:"iframe-resize",id:"ytplayer",height:document.documentElement.scrollHeight},"*");}catch(e){}\n'
        "  }\n"
        "  setTimeout(ph,300);\n"
        '  window.addEventListener("resize",function(){setTimeout(ph,100);});\n'
        "})();\n"
        "</script>\n"
        "</body>\n"
        "</html>"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  HTML: Search Results Grid
# ══════════════════════════════════════════════════════════════════════════════


def _build_search_html(videos: list, query: str) -> str:
    p, pa, pm, pg = _vivid_palette()
    safe_query = _html.escape(query)

    cards_html = ""
    for i, v in enumerate(videos):
        ci = i % 5
        vid_id = v.get("videoId", "")
        if not vid_id:
            continue

        title = _html.escape((v.get("title") or "Unknown")[:90])
        channel = _html.escape((v.get("author") or v.get("channelTitle") or "")[:50])
        views = _fmt_count(v.get("viewCount", 0))
        dur = _fmt_duration(v.get("lengthSeconds", 0))
        pub = _html.escape((v.get("publishedText") or "")[:20])

        # Thumbnail: prefer Invidious thumbnails, fall back to ytimg CDN
        thumbs = v.get("videoThumbnails", [])
        thumb = ""
        if thumbs:
            th = next(
                (
                    t
                    for t in thumbs
                    if t.get("quality") in ("medium", "sddefault", "default")
                ),
                thumbs[-1],
            )
            thumb = th.get("url", "")
        if not thumb:
            thumb = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"

        yt_url = YT_WATCH.format(vid_id)
        stat_str = " · ".join(
            x
            for x in [
                f"👁 {views}" if views and views != "—" else "",
                pub,
            ]
            if x
        )

        cards_html += f"""
<div class="vc" style="border-left-color:{p[ci]};animation-delay:{i * 0.05:.2f}s;">
  <a href="{yt_url}" target="_blank" rel="noopener" class="tw">
    <img src="{thumb}" class="th" loading="lazy" alt=""
         onerror="this.src='https://i.ytimg.com/vi/{vid_id}/default.jpg'">
    {"<span class='dur'>" + dur + "</span>" if dur else ""}
  </a>
  <div class="vm">
    <a href="{yt_url}" target="_blank" rel="noopener" class="vt"
       style="color:{p[ci]};">{title}</a>
    <div class="vchan">{channel}</div>
    <div class="vstat">{stat_str}</div>
    <a class="vbtn" href="{yt_url}" target="_blank" rel="noopener"
       style="background:{pa[ci]};color:{p[ci]};border-color:{pm[ci]};">▶ Watch</a>
  </div>
</div>"""

    cv = "".join(
        f"--c{i}:{p[i]};--ca{i}:{pa[i]};--cm{i}:{pm[i]};--cg{i}:{pg[i]};"
        for i in range(5)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{{cv}}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:transparent;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;padding:4px;}}

.hd{{
  font-size:13px;font-weight:900;color:#fff;margin-bottom:8px;
  display:flex;align-items:center;gap:8px;
}}
.stripe{{
  height:2px;margin-bottom:10px;border-radius:2px;
  background:linear-gradient(90deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]});
}}

.vc{{
  display:flex;gap:11px;
  background:#0a0a0e;border:1px solid #131320;border-left:3px solid;
  border-radius:10px;padding:10px;margin-bottom:7px;
  opacity:0;animation:fadeUp .32s ease forwards;
  transition:box-shadow .15s,background .15s;
}}
.vc:hover{{background:#0e0e14;box-shadow:0 0 24px rgba(255,255,255,.03);}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:translateY(0)}}}}

.tw{{
  flex-shrink:0;position:relative;
  width:136px;height:77px;
  border-radius:7px;overflow:hidden;
  background:#111;display:block;
}}
.th{{width:100%;height:100%;object-fit:cover;display:block;}}
.dur{{
  position:absolute;bottom:4px;right:4px;
  font-size:9px;font-weight:900;
  background:rgba(0,0,0,.85);color:#fff;
  padding:2px 5px;border-radius:4px;letter-spacing:.3px;
}}

.vm{{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px;}}
.vt{{
  font-size:13px;font-weight:800;line-height:1.3;
  text-decoration:none;transition:opacity .12s;
}}
.vt:hover{{opacity:.75;}}
.vchan{{font-size:10px;color:#444;}}
.vstat{{font-size:10px;color:#2a2a35;}}
.vbtn{{
  display:inline-flex;align-items:center;gap:5px;
  font-size:10px;font-weight:900;border:1px solid;
  padding:4px 12px;border-radius:20px;
  text-decoration:none;margin-top:2px;align-self:flex-start;
  transition:filter .12s;
}}
.vbtn:hover{{filter:brightness(1.35);}}

.foot{{
  text-align:center;font-size:10px;color:#1e1e28;
  margin-top:6px;letter-spacing:.3px;
}}
</style>
</head>
<body>
<div class="hd">🎬 YouTube: "{safe_query}" · {len(videos)} results</div>
<div class="stripe"></div>
{cards_html}
<div class="foot">Click any result to open on YouTube · Say "play youtube [title]" to embed in chat</div>
<script>
setTimeout(function() {{
  try {{
    window.parent.postMessage(
      {{type:"iframe-resize",id:"ytsearch",height:document.documentElement.scrollHeight}},
      "*"
    );
  }} catch(e) {{}}
}}, 200);
</script>
</body>
</html>""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tool class
# ══════════════════════════════════════════════════════════════════════════════


class Tools:
    class Valves(BaseModel):
        YOUTUBE_API_KEY: str = Field(
            default="",
            description=(
                "YouTube Data API v3 key for higher-quality search results and accurate stats. "
                "Get a free key at https://console.cloud.google.com — enable 'YouTube Data API v3'. "
                "Leave blank to use Invidious (works without a key)."
            ),
        )
        INVIDIOUS_INSTANCE: str = Field(
            default="",
            description=(
                "Preferred Invidious instance URL, e.g. https://invidious.example.com. "
                "Leave blank to auto-select from the built-in list."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _preferred(self) -> str:
        return (self.valves.INVIDIOUS_INSTANCE or "").rstrip("/")

    def _has_api(self) -> bool:
        return bool((self.valves.YOUTUBE_API_KEY or "").strip())

    async def _search(self, session, query: str, limit: int = 8) -> list:
        """
        Search priority:
          1. YouTube Data API v3  (if key configured — most accurate)
          2. YouTube InnerTube    (YouTube's own internal API — fast, no key)
          3. Invidious            (last resort fallback)
        """
        if self._has_api():
            d = await _yt_api(
                session,
                "/search",
                {"part": "snippet", "type": "video", "maxResults": limit, "q": query},
                self.valves.YOUTUBE_API_KEY,
            )
            if d and d.get("items"):
                out = []
                for item in d["items"]:
                    sn = item.get("snippet", {})
                    out.append(
                        {
                            "videoId": item.get("id", {}).get("videoId", ""),
                            "title": sn.get("title", ""),
                            "author": sn.get("channelTitle", ""),
                            "publishedText": sn.get("publishedAt", "")[:10],
                            "videoThumbnails": [
                                {
                                    "url": sn.get("thumbnails", {})
                                    .get("medium", {})
                                    .get("url", ""),
                                    "quality": "medium",
                                }
                            ],
                            "viewCount": 0,
                            "lengthSeconds": 0,
                        }
                    )
                return out

        # InnerTube — fast, direct, no proxy needed
        results = await _innertube_search(session, query, limit)
        if results:
            return results

        # Last resort: Invidious
        data = await _invidious_request(
            session,
            "/api/v1/search",
            {"q": query, "type": "video", "page": 1},
            self._preferred(),
        )
        return (data or [])[:limit]

    async def _video_stats(self, session, video_id: str) -> dict:
        """Fetch detailed video info via YouTube API or Invidious."""
        if self._has_api():
            d = await _yt_api(
                session,
                "/videos",
                {"part": "statistics,snippet,contentDetails", "id": video_id},
                self.valves.YOUTUBE_API_KEY,
            )
            if d and d.get("items"):
                item = d["items"][0]
                sn = item.get("snippet", {})
                st = item.get("statistics", {})
                cd = item.get("contentDetails", {})
                th = sn.get("thumbnails", {})
                best = (
                    th.get("maxres") or th.get("high") or th.get("medium") or {}
                ).get("url", "")
                return {
                    "title": sn.get("title", ""),
                    "author": sn.get("channelTitle", ""),
                    "viewCount": int(st.get("viewCount", 0) or 0),
                    "likeCount": int(st.get("likeCount", 0) or 0),
                    "description": sn.get("description", ""),
                    "publishedText": sn.get("publishedAt", "")[:10],
                    "lengthSeconds": _parse_iso_duration(cd.get("duration", "")),
                    "videoThumbnails": [{"url": best, "quality": "maxres"}],
                }

        # Fall back to Invidious
        data = await _invidious_request(
            session, f"/api/v1/videos/{video_id}", {}, self._preferred()
        )
        return data or {}

    # ── Tool 1: watch_youtube ─────────────────────────────────────────────────

    async def watch_youtube(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Embed and play a single YouTube video in chat. Use this by default for any
        video request — it finds the best match and plays it immediately.

        Decision rule (pick ONE tool, never both):
          → watch_youtube  — user wants to WATCH something  ("show me", "play", "tutorial on",
                             "how do I", "video about", "review of", a bare YouTube URL)
          → search_youtube — user explicitly wants to BROWSE/CHOOSE  ("give me options",
                             "show me a few", "let me pick", "search for", "what are some")
          → get_video_summary — user wants a SUMMARY/TRANSCRIPT, not to watch
                             ("summarize", "recap", "what does this video say", "transcript of")

        When in doubt, use watch_youtube.

        :param query: Topic, search phrase, or direct YouTube URL
        """
        await _emit(__event_emitter__, f"🔍 Finding video for '{query[:60]}'…")

        conn = aiohttp.TCPConnector(ssl=False, limit=4)
        transcript = ""
        async with aiohttp.ClientSession(
            connector=conn, headers=_SESSION_HEADERS
        ) as session:

            # Direct URL / bare ID → skip search entirely
            video_id = _extract_video_id(query)
            seed_meta = {}

            if not video_id:
                videos = await self._search(session, query, limit=3)
                if not videos:
                    await _emit(__event_emitter__, "❌ No videos found", done=True)
                    return (
                        f"❌ No YouTube videos found for '{query}'. "
                        "Try rephrasing or use a more specific term."
                    )
                seed_meta = videos[0]
                video_id = seed_meta.get("videoId", "")

            if not video_id:
                await _emit(__event_emitter__, "❌ Invalid video", done=True)
                return "❌ Could not get a valid YouTube video ID."

            # Fetch transcript while the session is still open so the LLM can
            # answer follow-up questions about the video without a separate call.
            await _emit(__event_emitter__, "📖 Fetching transcript…")
            transcript = await _get_transcript(session, video_id, self._preferred())

        # Build player immediately from whatever metadata we already have.
        # Likes/dislikes are fetched client-side by JS — zero extra round-trips.
        title = seed_meta.get("title") or seed_meta.get("name") or "Unknown Title"
        channel = (
            seed_meta.get("author")
            or seed_meta.get("channelTitle")
            or "Unknown Channel"
        )
        view_count = int(seed_meta.get("viewCount", 0) or 0)
        published = (
            seed_meta.get("publishedText")
            or seed_meta.get("publishedAt", "")[:10]
            or ""
        )
        duration = _fmt_duration(int(seed_meta.get("lengthSeconds") or 0))
        description = seed_meta.get("description", "") or ""

        transcript_status = (
            f" · 📄 transcript loaded"
            if transcript and len(transcript) > 50
            else " · ⚠️ no transcript"
        )
        await _emit(
            __event_emitter__, f"✅ '{title[:50]}'{transcript_status}", done=True
        )

        # Emit the player HTML as a message event so it renders in the UI.
        html = _build_player_html(
            video_id=video_id,
            title=title,
            channel=channel,
            view_count=view_count,
            published=published,
            description=description,
            duration=duration,
        )
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "embeds",
                    "data": {"embeds": [html]},
                }
            )

        # Return transcript + instructions to the LLM.
        # The LLM should respond with a single casual sentence hinting at the
        # video — like someone who's seen it and is ready to discuss, not a host
        # introducing it. No "your video is above", no bullet points, no spoilers.
        yt_url = YT_WATCH.format(video_id)
        if transcript and len(transcript) > 50:
            word_count = len(transcript.split())
            truncated = transcript[:14000]
            tail = (
                "\n\n[Transcript truncated to 14,000 characters]"
                if len(transcript) > 14000
                else ""
            )
            return (
                f"[INTERNAL — do not repeat this block to the user]\n"
                f"Video: {title} by {channel} | {yt_url}\n"
                f"Transcript (~{word_count:,} words):\n{truncated}{tail}\n\n"
                f"[YOUR RESPONSE INSTRUCTIONS]\n"
                f"Write ONE short, casual sentence — as if you've just watched this and "
                f"want to say something interesting without spoiling it. "
                f"Do NOT say 'your video is above', do NOT list features or metadata, "
                f"do NOT use bullet points. Just a natural, human aside. "
                f"If the user asks follow-up questions, answer using the transcript above."
            )
        else:
            return (
                f"[INTERNAL — do not repeat this block to the user]\n"
                f"Video: {title} by {channel} | {yt_url}\n"
                f"No transcript available.\n\n"
                f"[YOUR RESPONSE INSTRUCTIONS]\n"
                f"Write ONE short, casual sentence acknowledging the video is ready. "
                f"Do NOT say 'your video is above' or describe the player."
            )

    # ── Tool 2: search_youtube ────────────────────────────────────────────────

    async def search_youtube(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Show a browsable grid of YouTube results. Use ONLY when the user explicitly
        wants to browse and pick — NOT just to watch something.

        Triggers: "give me some options", "show me a few videos", "let me choose",
        "search YouTube for", "what are some videos on X", "compare videos about X".

        For everything else use watch_youtube (plays the best match immediately).
        Never call both tools for the same request.

        :param query: Search query
        """
        await _emit(__event_emitter__, f"🔎 Searching YouTube for '{query[:60]}'…")

        conn = aiohttp.TCPConnector(ssl=False, limit=4)
        async with aiohttp.ClientSession(
            connector=conn, headers=_SESSION_HEADERS
        ) as session:
            videos = await self._search(session, query, limit=8)

        if not videos:
            await _emit(__event_emitter__, "❌ No results found", done=True)
            return f"❌ No YouTube videos found for '{query}'."

        html = _build_search_html(videos, query)
        await _emit(
            __event_emitter__, f"✅ {len(videos)} results for '{query[:50]}'", done=True
        )
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ── Tool 3: get_video_summary ─────────────────────────────────────────────

    async def get_video_summary(
        self,
        video_url_or_query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        Fetch a video's transcript so the AI can produce a detailed summary or
        return the raw transcript text. Use when the user wants to READ about a
        video, not watch it.

        Triggers: "summarize", "recap", "what does this video cover", "explain this
        video", "give me the transcript of", "what is [url] about".

        Do NOT use this just because a URL was shared — if the user wants to watch,
        use watch_youtube (it also loads the transcript silently for follow-ups).

        :param video_url_or_query: YouTube URL, video ID, or a topic to search and summarize
        """
        await _emit(__event_emitter__, "🔍 Finding video…")

        conn = aiohttp.TCPConnector(ssl=False, limit=6)
        async with aiohttp.ClientSession(
            connector=conn, headers=_SESSION_HEADERS
        ) as session:

            video_id = _extract_video_id(video_url_or_query)
            title = ""
            channel = ""

            if not video_id:
                # Treat as a search query; take the top result
                await _emit(
                    __event_emitter__, f"🔎 Searching for '{video_url_or_query[:50]}'…"
                )
                videos = await self._search(session, video_url_or_query, limit=1)
                if not videos:
                    await _emit(__event_emitter__, "❌ No video found", done=True)
                    return (
                        f"❌ Could not find a YouTube video for '{video_url_or_query}'. "
                        "Try providing a direct YouTube URL instead."
                    )
                video_id = videos[0].get("videoId", "")
                title = videos[0].get("title", "")
                channel = videos[0].get("author", "")

            if not video_id:
                return "❌ Could not extract a valid YouTube video ID from the input."

            # Fetch transcript and metadata concurrently — transcript via
            # youtube-transcript-api is fast, no need to serialize these.
            async def _maybe_fetch_stats():
                if title:
                    return {}
                await _emit(__event_emitter__, "📊 Fetching video metadata…")
                return await self._video_stats(session, video_id)

            await _emit(__event_emitter__, "📖 Fetching transcript…")
            stats_task = asyncio.create_task(_maybe_fetch_stats())
            transcript = await _get_transcript(session, video_id, self._preferred())
            stats = await stats_task

            nonlocal_title = title or stats.get("title", f"Video {video_id}")
            nonlocal_channel = channel or stats.get("author", "Unknown Channel")

        yt_url = YT_WATCH.format(video_id)
        title = nonlocal_title
        channel = nonlocal_channel

        if not transcript or len(transcript) < 50:
            await _emit(__event_emitter__, "⚠️ No transcript available", done=True)
            return (
                f"⚠️ Could not retrieve a transcript for this video.\n\n"
                f"**{title}**  |  {channel}\n"
                f"URL: {yt_url}\n\n"
                "This usually means auto-captions are disabled, the video is very new, "
                "it's in a non-English language without subtitles, or it's a live stream. "
                "You can still ask me to embed it so you can watch directly."
            )

        word_count = len(transcript.split())
        await _emit(
            __event_emitter__,
            f"✅ Transcript ready ({word_count:,} words) — generating summary",
            done=True,
        )

        # Return structured context for the LLM to write the summary
        truncated = transcript[:12000]
        note = (
            "\n\n[Transcript truncated to 12,000 characters for context window]"
            if len(transcript) > 12000
            else ""
        )

        return (
            f"Below is the full transcript of the YouTube video titled **'{title}'** "
            f"by **{channel}**.\n"
            f"URL: {yt_url}\n"
            f"Transcript length: ~{word_count:,} words\n\n"
            f"Please write a comprehensive, well-structured summary that covers:\n"
            f"- The main subject, purpose, and overall thesis of the video\n"
            f"- All major points, steps, findings, tips, or arguments (in order)\n"
            f"- Notable insights, quotes, or examples worth highlighting\n"
            f"- The conclusion or key takeaway\n\n"
            f"Write in clear flowing paragraphs (not just bullets). Group related content "
            f"into labelled sections. Mention the title and channel at the top.\n\n"
            f"{'━' * 40} TRANSCRIPT {'━' * 40}\n"
            f"{truncated}{note}"
        )
