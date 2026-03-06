"""
title: Jellyfin Media Player
description: >
  Cinematic Jellyfin media player for Open WebUI.
  Supports movies, TV shows (SxxExx), music, subtitles, quality selection, and download.

  Setup:
    1. Set JELLYFIN_HOST to your server URL (e.g. http://192.168.1.100:8096)
    2. Either set JELLYFIN_API_KEY (recommended: Dashboard → API Keys → +)
       OR set JELLYFIN_USERNAME + JELLYFIN_PASSWORD

  Commands:
    - "play Shrek"               → plays the movie
    - "play Breaking Bad S02E05" → plays that episode
    - "play music Bohemian Rhapsody" → music player
    - "random movie"             → random film
    - "search [query]"           → search library

author: ichrist
version: 6.3.0
license: MIT
"""

import aiohttp
import logging
import re
import random
import json as _json
from typing import Any, Optional, Callable, Awaitable
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BROWSER_SAFE_VIDEO = {"h264", "avc", "avc1"}
BROWSER_SAFE_AUDIO = {"aac", "mp3", "opus", "vorbis"}
BROWSER_SAFE_CONTAINERS = {"mp4", "m4v", "webm"}

RESOLUTION_PRESETS = {
    "Original": {"bitrate": 80_000_000},
    "4K": {"bitrate": 40_000_000},
    "1080p": {"bitrate": 20_000_000},
    "720p": {"bitrate": 8_000_000},
    "480p": {"bitrate": 3_000_000},
    "360p": {"bitrate": 1_500_000},
}

SUNO_HUE_FAMILIES = [
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
    families = random.sample(SUNO_HUE_FAMILIES, 5)
    hues = [random.randint(lo, hi) for lo, hi in families]
    sats = [random.randint(96, 100) for _ in range(5)]
    lits = [random.randint(60, 70) for _ in range(5)]
    solid = [f"hsl({h},{s}%,{l}%)" for h, s, l in zip(hues, sats, lits)]
    faint = [f"hsla({h},{s}%,{l}%,0.09)" for h, s, l in zip(hues, sats, lits)]
    mid = [f"hsla({h},{s}%,{l}%,0.26)" for h, s, l in zip(hues, sats, lits)]
    glow = [f"hsla({h},{s}%,{l}%,0.55)" for h, s, l in zip(hues, sats, lits)]
    return solid, faint, mid, glow


async def _emit(emitter, desc, done=False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


class Tools:
    class Valves(BaseModel):
        JELLYFIN_HOST: str = Field(
            default="http://your-jellyfin-server:8096",
            description="Jellyfin server URL — no trailing slash. Example: http://192.168.1.100:8096 or https://jellyfin.yourdomain.com",
        )
        JELLYFIN_USERNAME: str = Field(
            default="",
            description="Jellyfin username (used to obtain a session token on each request). Leave blank if using API_KEY.",
        )
        JELLYFIN_PASSWORD: str = Field(
            default="",
            description="Jellyfin password. Leave blank if using API_KEY.",
            json_schema_extra={"__type__": "password"},
        )
        JELLYFIN_API_KEY: str = Field(
            default="",
            description=(
                "Optional: Jellyfin API key (Dashboard → API Keys → +). "
                "If set, username/password are ignored and this key is used directly. "
                "Recommended for production — avoids storing your password."
            ),
            json_schema_extra={"__type__": "password"},
        )
        MAX_STREAMING_BITRATE: int = Field(
            default=20_000_000,
            description="Default max streaming bitrate in bps (e.g. 20000000 = 20 Mbps for 1080p).",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def _get_token(self, session):
        host = self.valves.JELLYFIN_HOST.rstrip("/")

        # ── Option 1: Direct API key (preferred) ──────────────────────────────
        if self.valves.JELLYFIN_API_KEY.strip():
            api_key = self.valves.JELLYFIN_API_KEY.strip()
            # Resolve the user ID for the API key owner
            headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
            async with session.get(f"{host}/Users/Me", headers=headers) as resp:
                if resp.status == 200:
                    d = await resp.json()
                    return api_key, d["Id"]
                # Fallback: list users and pick first admin/active user
            async with session.get(f"{host}/Users", headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"API key validation failed: HTTP {resp.status}")
                users = await resp.json()
                if not users:
                    raise RuntimeError("No users found on this Jellyfin server.")
                return api_key, users[0]["Id"]

        # ── Option 2: Username + Password ─────────────────────────────────────
        if not self.valves.JELLYFIN_USERNAME.strip():
            raise RuntimeError(
                "Jellyfin not configured. Set JELLYFIN_API_KEY (recommended) "
                "or JELLYFIN_USERNAME + JELLYFIN_PASSWORD in the tool valves."
            )
        headers = {
            "Authorization": (
                'MediaBrowser Client="OpenWebUI", Device="OpenWebUI-Tool", '
                'DeviceId="openwebui-jellyfin-tool", Version="6.2.0"'
            ),
            "Content-Type": "application/json",
        }
        async with session.post(
            f"{host}/Users/AuthenticateByName",
            json={
                "Username": self.valves.JELLYFIN_USERNAME.strip(),
                "Pw": self.valves.JELLYFIN_PASSWORD,
            },
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Auth failed: HTTP {resp.status}")
            d = await resp.json()
            return d["AccessToken"], d["User"]["Id"]

    async def _get_playback_data(
        self, session, host, item_id, user_id, token, max_bitrate=None
    ):
        if max_bitrate is None:
            max_bitrate = self.valves.MAX_STREAMING_BITRATE

        url = (
            f"{host}/Items/{item_id}/PlaybackInfo"
            f"?UserId={user_id}&StartTimeTicks=0&IsPlayback=true"
            f"&AutoOpenLiveStream=true&MaxStreamingBitrate={max_bitrate}"
        )
        auth = {
            "Authorization": f'MediaBrowser Token="{token}"',
            "Content-Type": "application/json",
        }
        device_profile = {
            "DeviceProfile": {
                "MaxStreamingBitrate": max_bitrate,
                "DirectPlayProfiles": [
                    {
                        "Container": "mp4,m4v",
                        "Type": "Video",
                        "VideoCodec": "h264",
                        "AudioCodec": "aac,mp3,opus",
                    },
                    {
                        "Container": "webm",
                        "Type": "Video",
                        "VideoCodec": "vp8,vp9",
                        "AudioCodec": "vorbis,opus",
                    },
                ],
                "TranscodingProfiles": [
                    {
                        "Container": "ts",
                        "Type": "Video",
                        "VideoCodec": "h264",
                        "AudioCodec": "aac",
                        "Context": "Streaming",
                        "Protocol": "hls",
                        "MaxAudioChannels": "2",
                        "MinSegments": 1,
                    },
                ],
                "ContainerProfiles": [],
                "CodecProfiles": [],
                "SubtitleProfiles": [
                    {"Format": "srt", "Method": "External"},
                    {"Format": "ass", "Method": "External"},
                    {"Format": "vtt", "Method": "External"},
                ],
            }
        }

        async with session.post(url, json=device_profile, headers=auth) as resp:
            if resp.status != 200:
                raise RuntimeError(f"PlaybackInfo failed: HTTP {resp.status}")
            data = await resp.json()

        sources = data.get("MediaSources", [])
        if not sources:
            raise RuntimeError("No media sources returned")

        src = sources[0]
        media_source_id = src.get("Id", item_id)
        container = src.get("Container", "").lower().split(",")[0]
        transcode_url = src.get("TranscodingUrl", "")
        tag = src.get("ETag", "")

        streams = src.get("MediaStreams", [])
        video_codec = next(
            (s.get("Codec", "").lower() for s in streams if s.get("Type") == "Video"),
            "",
        )
        audio_codec = next(
            (s.get("Codec", "").lower() for s in streams if s.get("Type") == "Audio"),
            "",
        )
        channels = next(
            (s.get("Channels", 2) for s in streams if s.get("Type") == "Audio"), 2
        )

        bitmap_codecs = {
            "pgssub",
            "dvdsub",
            "dvbsub",
            "hdmv_pgs_subtitle",
            "dvd_subtitle",
        }
        subtitle_tracks = []
        for s in streams:
            if s.get("Type") != "Subtitle":
                continue
            if s.get("Codec", "").lower() in bitmap_codecs:
                continue
            idx = s.get("Index", 0)
            lang = s.get("Language") or ""
            disp = s.get("DisplayTitle") or s.get("Title") or lang or f"Track {idx}"
            vtt = (
                f"{host}/Videos/{item_id}/{media_source_id}"
                f"/Subtitles/{idx}/0/Stream.vtt?api_key={token}"
            )
            subtitle_tracks.append(
                {"index": idx, "label": disp, "language": lang, "url": vtt}
            )

        needs_transcode = (
            bool(transcode_url)
            or container not in BROWSER_SAFE_CONTAINERS
            or video_codec not in BROWSER_SAFE_VIDEO
            or audio_codec not in BROWSER_SAFE_AUDIO
            or channels > 2
        )

        # Use the server-provided transcode URL if available (most reliable)
        if transcode_url:
            hls_server = (
                f"{host}{transcode_url}"
                if transcode_url.startswith("/")
                else transcode_url
            )
            # Ensure api_key is in the URL (not just a header) for iframe use
            if "api_key" not in hls_server:
                sep = "&" if "?" in hls_server else "?"
                hls_server += f"{sep}api_key={token}"
        else:
            hls_server = ""

        # Generate a stable PlaySessionId so Jellyfin keeps the transcode alive
        play_session_id = re.sub(r"[^a-zA-Z0-9]", "", item_id)[:24] + "jftool"

        # Fallback HLS URL with all required params including PlaySessionId
        hls_base = (
            f"{host}/Videos/{item_id}/master.m3u8"
            f"?MediaSourceId={media_source_id}"
            f"&VideoCodec=h264&AudioCodec=aac&AudioStreamIndex=1"
            f"&TranscodingMaxAudioChannels=2&SegmentContainer=ts"
            f"&MinSegments=1&RequireAvc=true"
            f"&PlaySessionId={play_session_id}"
            f"&api_key={token}"
        )

        direct_url = (
            f"{host}/Videos/{item_id}/stream.mp4"
            f"?MediaSourceId={media_source_id}&Static=true&api_key={token}"
            + (f"&Tag={tag}" if tag else "")
        )
        download_url = f"{host}/Items/{item_id}/Download?api_key={token}"

        return {
            "needs_transcode": needs_transcode,
            "direct_url": direct_url,
            "hls_server": hls_server,
            "hls_base": hls_base,
            "download_url": download_url,
            "media_source_id": media_source_id,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "container": container,
            "channels": channels,
            "tag": tag,
            "subtitle_tracks": subtitle_tracks,
            "token": token,
            "play_session_id": play_session_id,
        }

    def _parse_episode_query(self, query):
        m = re.search(r"(?i)\bs(\d{1,2})\s*e(\d{1,2})\b", query)
        if m:
            return (
                query[: m.start()].strip().rstrip("-—:· "),
                int(m.group(1)),
                int(m.group(2)),
            )
        m = re.search(r"\b(\d{1,2})x(\d{1,2})\b", query)
        if m:
            return (
                query[: m.start()].strip().rstrip("-—:· "),
                int(m.group(1)),
                int(m.group(2)),
            )
        return query, None, None

    async def _find_episode(
        self, session, host, user_id, token, series_name, season, episode
    ):
        auth = {"Authorization": f'MediaBrowser Token="{token}"'}
        async with session.get(
            f"{host}/Users/{user_id}/Items?searchTerm={series_name}"
            f"&IncludeItemTypes=Series&Recursive=true&Limit=5",
            headers=auth,
        ) as r:
            if r.status != 200:
                return None
            d = await r.json()
        series = d.get("Items", [])
        if not series:
            return None
        sid = series[0]["Id"]
        async with session.get(
            f"{host}/Shows/{sid}/Episodes?Season={season}&UserId={user_id}"
            f"&Fields=Overview,RunTimeTicks,SeriesId,SeriesName,SeasonName,"
            f"CommunityRating,OfficialRating,Genres,People,Taglines,Studios",
            headers=auth,
        ) as r:
            if r.status != 200:
                return None
            d = await r.json()
        eps = d.get("Items", [])
        for ep in eps:
            if ep.get("IndexNumber") == episode:
                return ep
        if 0 < episode <= len(eps):
            return eps[episode - 1]
        return None

    async def _build_player(self, host, item, token, user_id):
        item_id = item["Id"]
        title = item.get("Name", "Unknown")
        year = item.get("ProductionYear", "")
        overview = item.get("Overview", "")
        taglines = item.get("Taglines") or []
        item_type = item.get("Type", "")
        comm_rating = item.get("CommunityRating")
        crit_rating = item.get("CriticRating")
        off_rating = item.get("OfficialRating", "")
        genres = item.get("Genres") or []
        studios = item.get("Studios") or []
        studio_name = studios[0].get("Name", "") if studios else ""
        people = item.get("People") or []
        directors = [p["Name"] for p in people if p.get("Type") == "Director"][:2]
        cast = [p["Name"] for p in people if p.get("Type") == "Actor"][:6]

        ticks = item.get("RunTimeTicks", 0)
        rm = round(ticks / 600_000_000) if ticks else None
        runtime_str = (
            (f"{rm//60}h {rm%60}m" if rm and rm >= 60 else f"{rm}m") if rm else ""
        )

        series_id = item.get("SeriesId", "")
        series_label = ""
        season_ep_label = ""
        if item_type == "Episode":
            series_label = item.get("SeriesName", "")
            sn = item.get("ParentIndexNumber")
            en = item.get("IndexNumber", "")
            s_str = f"S{sn:02d}" if isinstance(sn, int) else ""
            e_str = f"E{en:02d}" if isinstance(en, int) else ""
            season_ep_label = " · ".join(x for x in [s_str, e_str] if x)

        if item_type == "Episode" and series_id:
            poster_url = (
                f"{host}/Items/{series_id}/Images/Primary?api_key={token}&maxHeight=600"
            )
            backdrop_url = f"{host}/Items/{series_id}/Images/Backdrop?api_key={token}&maxWidth=1280"
        else:
            poster_url = (
                f"{host}/Items/{item_id}/Images/Primary?api_key={token}&maxHeight=600"
            )
            backdrop_url = (
                f"{host}/Items/{item_id}/Images/Backdrop?api_key={token}&maxWidth=1280"
            )

        p, pa, pm, pg = _vivid_palette()

        async with aiohttp.ClientSession() as session:
            try:
                pb = await self._get_playback_data(
                    session, host, item_id, user_id, token
                )
            except Exception as exc:
                logger.error(f"PlaybackData error: {exc}")
                play_session_id = re.sub(r"[^a-zA-Z0-9]", "", item_id)[:24] + "jftool"
                pb = {
                    "needs_transcode": True,
                    "direct_url": "",
                    "hls_server": "",
                    "hls_base": (
                        f"{host}/Videos/{item_id}/master.m3u8"
                        f"?MediaSourceId={item_id}&VideoCodec=h264&AudioCodec=aac"
                        f"&AudioStreamIndex=1&TranscodingMaxAudioChannels=2"
                        f"&SegmentContainer=ts&MinSegments=1&RequireAvc=true"
                        f"&PlaySessionId={play_session_id}&api_key={token}"
                    ),
                    "download_url": f"{host}/Items/{item_id}/Download?api_key={token}",
                    "media_source_id": item_id,
                    "video_codec": "?",
                    "audio_codec": "?",
                    "container": "?",
                    "channels": 2,
                    "tag": "",
                    "subtitle_tracks": [],
                    "token": token,
                    "play_session_id": play_session_id,
                }

        needs_tc = pb["needs_transcode"]
        direct_url = pb["direct_url"]
        hls_server = pb["hls_server"]
        hls_base = pb["hls_base"]
        download_url = pb["download_url"]
        vc = pb["video_codec"]
        ac = pb["audio_codec"]
        ct = pb["container"].upper()
        ch = pb["channels"]
        sub_tracks = pb["subtitle_tracks"]
        play_session_id = pb.get("play_session_id", "jftool")

        ch_str = f" {ch}ch" if ch and ch > 2 else ""
        strategy = "HLS" if needs_tc else "Direct"
        # Build badge_text as a plain Python string (not injected into JS template)
        badge_text = f"{strategy} · {ct} · {vc}/{ac}{ch_str}"
        # Store these for JS use as JSON strings to avoid f-string/JS collision
        badge_text_js = _json.dumps(badge_text)

        pid = "jfp" + re.sub(r"[^a-zA-Z0-9]", "", item_id)[:12]

        sub_tracks_js = _json.dumps(sub_tracks)
        res_presets_js = _json.dumps(
            {k: v["bitrate"] for k, v in RESOLUTION_PRESETS.items()}
        )

        meta_parts = [str(year) if year else "", runtime_str]
        if off_rating:
            meta_parts.append(off_rating)
        meta_str = "  ·  ".join(x for x in meta_parts if x)

        def chip(text, ci):
            return (
                f'<span style="background:{pa[ci]};color:{p[ci]};'
                f"border:1.5px solid {pm[ci]};"
                f"box-shadow:0 0 12px {pa[ci]};"
                f"font-size:10px;font-weight:900;letter-spacing:.5px;"
                f'padding:3px 11px;border-radius:20px;white-space:nowrap;">'
                f"{text}</span>"
            )

        chips_html = ""
        if comm_rating:
            chips_html += chip(f"★ {comm_rating:.1f}", 1)
        if crit_rating is not None:
            col = (
                "#4eff7a"
                if crit_rating >= 60
                else "#ffb730" if crit_rating >= 40 else "#ff4f4f"
            )
            chips_html += (
                f'<span style="color:{col};border:1.5px solid {col}55;'
                f"font-size:10px;font-weight:900;letter-spacing:.5px;"
                f'padding:3px 11px;border-radius:20px;white-space:nowrap;">🍅 {int(crit_rating)}%</span>'
            )
        for i, g in enumerate(genres[:4]):
            chips_html += chip(g, (i + 2) % 5)

        people_rows = []
        if directors:
            people_rows.append(
                f'<span style="color:{p[2]};font-size:9px;font-weight:900;letter-spacing:.8px;'
                f'text-transform:uppercase;margin-right:6px;">Dir</span>'
                f'<span style="color:#bbb;font-size:11px;">{" & ".join(directors)}</span>'
            )
        if cast:
            people_rows.append(
                f'<span style="color:{p[3]};font-size:9px;font-weight:900;letter-spacing:.8px;'
                f'text-transform:uppercase;margin-right:6px;">Cast</span>'
                f'<span style="color:#888;font-size:11px;">{", ".join(cast)}</span>'
            )
        people_html = ""
        if people_rows:
            people_html = (
                f'<div style="margin-top:11px;padding-top:11px;'
                f'border-top:1px solid {pa[1]};display:flex;flex-direction:column;gap:5px;">'
                + "".join(f"<div>{r}</div>" for r in people_rows)
                + "</div>"
            )

        overview_html = ""
        if overview:
            overview_html = (
                f'<p style="font-size:12px;color:#909090;line-height:1.7;margin-top:8px;'
                f'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">'
                f"{overview}</p>"
            )

        tagline_html = ""
        if taglines:
            tagline_html = (
                f'<p style="font-size:11.5px;color:{p[0]};font-style:italic;'
                f'margin-top:5px;opacity:.8;">&ldquo;{taglines[0]}&rdquo;</p>'
            )

        ep_header_html = ""
        if series_label:
            parts = " · ".join(x for x in [series_label, season_ep_label] if x)
            ep_header_html = (
                f'<div style="font-size:9.5px;font-weight:900;letter-spacing:2px;'
                f"text-transform:uppercase;color:{p[0]};margin-bottom:5px;"
                f'text-shadow:0 0 22px {pg[0]};">{parts}</div>'
            )

        res_opts_html = "".join(
            f'<option value="{k}"{"  selected" if k=="1080p" else ""}>{k}</option>'
            for k in RESOLUTION_PRESETS.keys()
        )

        css_vars = "\n".join(
            f"  --c{i}:{p[i]};--ca{i}:{pa[i]};--cm{i}:{pm[i]};--cg{i}:{pg[i]};"
            for i in range(5)
        )

        # FIX: needs_tc as JS bool, avoid Python True/False
        needs_tc_js = "true" if needs_tc else "false"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{{css_vars}}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{
  background:linear-gradient(135deg,#060608 0%,#0c0810 40%,#080c10 100%);
  font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;
  height:auto;overflow:hidden;
  padding:6px;
}}

.card{{
  border-radius:16px;overflow:hidden;
  background:linear-gradient(160deg,#0d0d12 0%,#0a0a0e 100%);
  border:1px solid {pm[0]};
  box-shadow:
    0 0 0 1px {pa[0]},
    0 0 60px {pa[1]},
    0 0 120px {pa[3]},
    inset 0 1px 0 {pm[0]},
    0 24px 60px rgba(0,0,0,.98);
}}

.stripe{{
  height:3px;
  background:linear-gradient(90deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[0]});
  background-size:300% 100%;
  animation:ss 3s linear infinite;
}}
@keyframes ss{{0%{{background-position:0%}}100%{{background-position:300%}}}}

.vid-wrap{{
  position:relative;background:#000;line-height:0;
  background:radial-gradient(ellipse at 50% 0%,{pa[0]} 0%,#000 70%);
}}
.vid-wrap video{{
  width:100%;display:block;
  max-height:420px;background:#000;
  border-bottom:1px solid {pa[0]};
}}
video::cue{{
  background:rgba(0,0,0,.85);color:#fff;
  font-size:1em;text-shadow:0 1px 8px #000;
  font-family:'Helvetica Neue',sans-serif;
}}

.badge{{
  position:absolute;top:12px;right:12px;z-index:30;
  font-family:'SF Mono','Fira Code',monospace;font-size:9.5px;letter-spacing:.3px;
  color:{p[2]};background:rgba(6,6,8,.93);
  border:1px solid {pm[2]};border-radius:8px;padding:5px 11px;
  box-shadow:0 0 20px {pa[2]};backdrop-filter:blur(16px);
  pointer-events:none;white-space:nowrap;max-width:55%;overflow:hidden;text-overflow:ellipsis;
}}
.badge.err{{color:#ff4444;border-color:#ff444455;}}

.ctrls{{
  display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:12px 16px;
  background:linear-gradient(180deg,{pa[0]} 0%,transparent 100%),
             linear-gradient(180deg,#0e0e14 0%,#0c0c10 100%);
  border-top:1px solid {pm[0]};
  border-bottom:1px solid {pa[1]};
  position:relative;
}}
.ctrls::before{{
  content:'';position:absolute;top:0;left:5%;right:5%;height:1px;
  background:linear-gradient(90deg,transparent,{pm[0]},transparent);
}}

.cg{{display:flex;align-items:center;gap:6px;}}
.cl{{
  font-size:9px;font-weight:900;letter-spacing:1.5px;text-transform:uppercase;
  color:{p[1]};text-shadow:0 0 14px {pg[1]};white-space:nowrap;
}}

select.sel{{
  -webkit-appearance:none;appearance:none;
  background:#111318 url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath fill='%23888' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E") no-repeat right 9px center;
  color:#f0f0f0;border:1.5px solid {pm[0]};border-radius:20px;
  font-size:11px;font-weight:700;padding:5px 26px 5px 12px;cursor:pointer;outline:none;
  box-shadow:0 0 14px {pa[0]};min-width:78px;
  transition:border-color .15s,box-shadow .15s;
}}
select.sel:hover,select.sel:focus{{border-color:{p[0]};box-shadow:0 0 22px {pm[0]};}}
select.sel option{{background:#111318;}}

.tog{{display:flex;align-items:center;gap:7px;cursor:pointer;user-select:none;}}
.tog input{{display:none;}}
.tog-t{{
  width:42px;height:23px;border-radius:12px;background:#1a1a22;
  border:1.5px solid {pm[4]};position:relative;flex-shrink:0;
  box-shadow:0 0 10px {pa[4]};transition:all .25s;
}}
.tog-k{{
  position:absolute;top:3px;left:3px;width:15px;height:15px;border-radius:50%;
  background:#444;transition:transform .25s cubic-bezier(.4,0,.2,1),background .25s,box-shadow .25s;
}}
.tog input:checked + .tog-t{{background:{pa[4]};border-color:{p[4]};box-shadow:0 0 24px {pm[4]};}}
.tog input:checked + .tog-t .tog-k{{
  transform:translateX(19px);background:{p[4]};box-shadow:0 0 14px {pg[4]};
}}

.dlbtn{{
  display:inline-flex;align-items:center;gap:6px;
  background:linear-gradient(135deg,{pa[3]},{pa[2]});
  color:{p[3]};border:1.5px solid {pm[3]};border-radius:20px;
  font-size:11px;font-weight:900;letter-spacing:.3px;
  padding:5px 15px;text-decoration:none;
  box-shadow:0 0 18px {pa[3]};transition:all .2s;white-space:nowrap;
}}
.dlbtn:hover{{
  background:linear-gradient(135deg,{pm[3]},{pm[2]});
  box-shadow:0 0 30px {pg[3]};color:#fff;transform:translateY(-1px);
}}

.sep{{width:1px;height:26px;background:{pa[2]};margin:0 1px;opacity:.7;flex-shrink:0;}}

.info{{
  display:flex;
  background:linear-gradient(160deg,#0d0d14 0%,#0a0a0e 100%);
  overflow:hidden;
}}

.poster-col{{
  flex-shrink:0;width:110px;
  position:relative;overflow:hidden;
  background:#000;
}}
.poster-col img{{
  width:100%;height:100%;object-fit:cover;display:block;
  min-height:180px;
  transition:transform .4s ease;
}}
.poster-col:hover img{{transform:scale(1.04);}}
.poster-col::after{{
  content:'';position:absolute;top:0;right:0;bottom:0;width:60px;
  background:linear-gradient(to right,transparent,#0d0d14);
}}
.poster-col::before{{
  content:'';position:absolute;top:0;left:0;bottom:0;width:3px;z-index:2;
  background:linear-gradient(180deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]});
  animation:ss 4s linear infinite;
  background-size:100% 300%;
}}

.meta-col{{
  flex:1;min-width:0;padding:14px 18px 14px 12px;position:relative;
  overflow:hidden;
}}
.meta-col::before{{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:
    radial-gradient(ellipse 70% 90% at 0% 0%,{pa[0]} 0%,transparent 60%),
    radial-gradient(ellipse 60% 70% at 100% 100%,{pa[2]} 0%,transparent 65%),
    radial-gradient(ellipse 40% 50% at 50% 50%,{pa[4]} 0%,transparent 70%);
}}
.meta-col > *{{position:relative;z-index:1;}}

.ttl{{
  font-size:22px;font-weight:900;color:#fff;line-height:1.1;letter-spacing:-.3px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  text-shadow:0 2px 20px {pa[0]};
}}
.sub-meta{{font-size:11px;color:#556;margin-top:3px;letter-spacing:.3px;}}
.chips{{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;}}
</style>
</head>
<body>
<div class="card">
  <div class="stripe"></div>

  <div class="vid-wrap">
    <div id="badge_{pid}" class="badge">{badge_text}</div>
    <video id="vid_{pid}" controls preload="metadata" poster="{backdrop_url}"></video>
  </div>

  <div class="ctrls">
    <div class="cg">
      <span class="cl">Quality</span>
      <select class="sel" id="res_{pid}">{res_opts_html}</select>
    </div>
    <div class="sep"></div>
    <div class="cg">
      <span class="cl">CC</span>
      <select class="sel" id="sub_{pid}" style="min-width:96px;"><option value="-1">Off</option></select>
    </div>
    <div class="sep"></div>
    <label class="tog" for="tc_{pid}">
      <input type="checkbox" id="tc_{pid}" checked>
      <div class="tog-t"><div class="tog-k"></div></div>
      <span class="cl">Transcode</span>
    </label>
    <div class="sep"></div>
    <a class="dlbtn" href="{download_url}" download>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>Download
    </a>
  </div>

  <div class="info">
    <div class="poster-col">
      <img src="{poster_url}" alt="" onerror="this.parentElement.style.display='none'">
    </div>
    <div class="meta-col">
      {ep_header_html}
      <div class="ttl">{title}</div>
      <div class="sub-meta">{meta_str}</div>
      <div class="chips">{chips_html}</div>
      {tagline_html}
      {overview_html}
      {people_html}
      {"" if not studio_name else f'<div style="font-size:9px;color:{p[4]};opacity:.5;margin-top:8px;letter-spacing:.8px;text-transform:uppercase;">{studio_name}</div>'}
    </div>
  </div>
</div>

<!-- FIX: hls.js loaded synchronously BEFORE the inline script runs -->
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js"></script>
<script>
(function() {{
  var TOKEN        = {_json.dumps(token)};
  var DIRECT_URL   = {_json.dumps(direct_url)};
  var HLS_SERVER   = {_json.dumps(hls_server)};
  var HLS_BASE     = {_json.dumps(hls_base)};
  var NEEDS_TC     = {needs_tc_js};
  var SUB_TRACKS   = {sub_tracks_js};
  var RES_BITS     = {res_presets_js};
  var PID          = {_json.dumps(pid)};
  var BADGE_BASE   = {badge_text_js};

  var vid    = document.getElementById("vid_"          + PID);
  var badge  = document.getElementById("badge_"        + PID);
  var resSel = document.getElementById("res_"          + PID);
  var subSel = document.getElementById("sub_"          + PID);
  var tcChk  = document.getElementById("tc_"           + PID);

  // FIX: start with transcode ON by default for maximum compatibility
  var currentRes   = "1080p";
  var forceTC      = true;
  var activeSubIdx = -1;
  var hlsInst      = null;
  var activeBlobUrl = null;

  function postHeight() {{
    try {{
      window.parent.postMessage(
        {{type:"iframe-resize", id:PID, height:document.documentElement.scrollHeight}},
        "*"
      );
    }} catch(e) {{}}
  }}

  function setBadge(msg, err) {{
    badge.textContent = msg;
    badge.className = err ? "badge err" : "badge";
  }}

  // FIX: auth is baked into HLS_BASE and HLS_SERVER URLs server-side now.
  // This function is only needed for direct MP4 URLs and subtitle VTT fetches.
  function addAuth(url) {{
    if (!url) return url;
    if (url.indexOf("api_key") !== -1) return url;
    var sep = url.indexOf("?") === -1 ? "?" : "&";
    return url + sep + "api_key=" + TOKEN;
  }}

  // FIX: Build HLS URL — prefer HLS_SERVER (server-provided) always, fallback to HLS_BASE
  function hlsUrl(res) {{
    var bits = RES_BITS[res] || RES_BITS["1080p"];
    // Always prefer the server-provided transcode URL — it's the most reliable
    if (HLS_SERVER) {{
      // Swap bitrate if user changed resolution
      var url = HLS_SERVER.replace(/MaxStreamingBitrate=\\d+/, "MaxStreamingBitrate=" + bits);
      if (url === HLS_SERVER) {{
        // param wasn't present, append it
        url += "&MaxStreamingBitrate=" + bits;
      }}
      return url;
    }}
    // Fallback: HLS_BASE already has api_key + PlaySessionId; just add bitrate
    var base = HLS_BASE;
    base = base.replace(/MaxStreamingBitrate=\\d+/, "MaxStreamingBitrate=" + bits);
    if (base === HLS_BASE) base += "&MaxStreamingBitrate=" + bits;
    return base;
  }}

  function killHls() {{
    if (hlsInst) {{
      try {{ hlsInst.destroy(); }} catch(e) {{}}
      hlsInst = null;
    }}
  }}

  // ── Subtitle system — native <track> via Blob URL ──
  // We fetch VTT with api_key auth, convert to a Blob URL (same-origin),
  // then inject a <track default> element. Blob URL bypasses CORS/iframe sandbox.
  function clearSubTracks() {{
    // Remove all existing text tracks
    var tracks = vid.querySelectorAll('track');
    tracks.forEach(function(t) {{ vid.removeChild(t); }});
    if (activeBlobUrl) {{ URL.revokeObjectURL(activeBlobUrl); activeBlobUrl = null; }}
    // Also disable any lingering TextTrack
    for (var i = 0; i < vid.textTracks.length; i++) {{
      vid.textTracks[i].mode = 'disabled';
    }}
  }}

  function loadSubTrack() {{
    clearSubTracks();
    if (activeSubIdx === -1) return;
    var info = SUB_TRACKS.find(function(t) {{ return t.index === activeSubIdx; }});
    if (!info) return;
    var url = info.url.indexOf('api_key') !== -1 ? info.url : info.url + '&api_key=' + TOKEN;
    fetch(url)
      .then(function(r) {{
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      }})
      .then(function(vttText) {{
        // Ensure it starts with WEBVTT header (Jellyfin sometimes omits it)
        if (vttText.trim().indexOf('WEBVTT') !== 0) {{
          vttText = 'WEBVTT\\n\\n' + vttText;
        }}
        var blob = new Blob([vttText], {{type: 'text/vtt'}});
        activeBlobUrl = URL.createObjectURL(blob);
        var track = document.createElement('track');
        track.kind = 'subtitles';
        track.label = info.label || ('Track ' + activeSubIdx);
        track.srclang = info.language || 'und';
        track.src = activeBlobUrl;
        track.default = true;
        vid.appendChild(track);
        // Force the track to showing mode after a short delay
        setTimeout(function() {{
          for (var i = 0; i < vid.textTracks.length; i++) {{
            if (vid.textTracks[i].label === track.label) {{
              vid.textTracks[i].mode = 'showing';
            }}
          }}
        }}, 200);
      }})
      .catch(function(e) {{ console.warn('Subtitle load error:', e); }});
  }}

  // ── Core playback ──
  function loadUrl(url, useHls) {{
    var wasPlaying = !vid.paused;
    var pos = vid.currentTime || 0;
    killHls();

    if (!useHls) {{
      vid.src = url;
      vid.load();
      vid.addEventListener("loadedmetadata", function h() {{
        vid.removeEventListener("loadedmetadata", h);
        if (pos > 1) vid.currentTime = pos;
        if (wasPlaying) vid.play().catch(function() {{}});
        setTimeout(loadSubTrack, 400);
      }});
      return;
    }}

    // FIX: Check Hls is actually available (cdn may be blocked in some envs)
    if (typeof Hls === 'undefined') {{
      setBadge("⚠ hls.js failed to load — trying direct", true);
      if (vid.canPlayType("application/vnd.apple.mpegurl")) {{
        vid.src = url;
        if (pos > 1) vid.currentTime = pos;
        if (wasPlaying) vid.play().catch(function() {{}});
      }}
      return;
    }}

    if (!Hls.isSupported()) {{
      if (vid.canPlayType("application/vnd.apple.mpegurl")) {{
        // Safari native HLS
        vid.src = url;
        if (pos > 1) vid.currentTime = pos;
        if (wasPlaying) vid.play().catch(function() {{}});
        setTimeout(loadSubTrack, 400);
      }} else {{
        setBadge("⚠ HLS not supported in this browser", true);
      }}
      return;
    }}

    // FIX: No xhrSetup/fetchSetup — auth is already in the URL.
    // xhrSetup was being stripped by OpenWebUI's CSP/DOMPurify sandbox.
    hlsInst = new Hls({{
      maxBufferLength: 30,
      maxMaxBufferLength: 90,
      startLevel: -1,
      autoStartLoad: true,
      enableWorker: true,
      lowLatencyMode: false,
    }});

    hlsInst.loadSource(url);
    hlsInst.attachMedia(vid);

    hlsInst.on(Hls.Events.MANIFEST_PARSED, function() {{
      if (pos > 1) vid.currentTime = pos;
      vid.play().catch(function() {{}});
      setTimeout(loadSubTrack, 400);
      postHeight();
    }});

    var mRec = false, nRec = false;
    hlsInst.on(Hls.Events.ERROR, function(e, d) {{
      if (!d.fatal) return;
      if (d.type === Hls.ErrorTypes.MEDIA_ERROR && !mRec) {{
        mRec = true; hlsInst.recoverMediaError(); return;
      }}
      if (d.type === Hls.ErrorTypes.NETWORK_ERROR && !nRec) {{
        nRec = true; hlsInst.startLoad(); return;
      }}
      setBadge("⚠ " + (d.details || "stream error"), true);
      killHls();
    }});
  }}

  function refresh() {{
    var useHls = NEEDS_TC || forceTC || currentRes !== "Original";
    var url = useHls ? hlsUrl(currentRes) : addAuth(DIRECT_URL);
    setBadge(BADGE_BASE + (currentRes !== "Original" ? " · " + currentRes : ""));
    loadUrl(url, useHls);
  }}

  // ── Controls ──
  resSel.addEventListener("change", function() {{
    currentRes = this.value;
    refresh();
  }});

  subSel.addEventListener("change", function() {{
    activeSubIdx = this.value === "-1" ? -1 : parseInt(this.value, 10);
    loadSubTrack();
  }});

  tcChk.addEventListener("change", function() {{
    forceTC = this.checked;
    refresh();
  }});

  // Populate subtitle dropdown
  SUB_TRACKS.forEach(function(t) {{
    var o = document.createElement("option");
    o.value = t.index;
    o.textContent = t.label + (t.language ? " [" + t.language + "]" : "");
    subSel.appendChild(o);
  }});

  // Boot — hls.js is already loaded synchronously above
  refresh();
  vid.addEventListener("loadedmetadata", postHeight);
  window.addEventListener("load", function() {{ setTimeout(postHeight, 300); }});
}})();
</script>
</body>
</html>""".strip()

        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    async def _build_music_player(self, host, item, token, user_id):
        """Build a beautiful music player UI for an audio track."""
        item_id = item["Id"]
        title = item.get("Name", "Unknown")
        album = item.get("Album", "")
        artists = item.get("Artists") or item.get("AlbumArtists") or []
        artist_str = ", ".join(
            a if isinstance(a, str) else a.get("Name", "") for a in artists[:3]
        )
        year = item.get("ProductionYear", "")
        genres = item.get("Genres") or []
        comm_rating = item.get("CommunityRating")

        ticks = item.get("RunTimeTicks", 0)
        rm = round(ticks / 10_000_000) if ticks else 0
        dur_str = f"{rm//60}:{rm%60:02d}" if rm else "–:––"

        album_id = item.get("AlbumId", "")
        if album_id:
            art_url = (
                f"{host}/Items/{album_id}/Images/Primary?api_key={token}&maxHeight=500"
            )
        else:
            art_url = (
                f"{host}/Items/{item_id}/Images/Primary?api_key={token}&maxHeight=500"
            )

        audio_url = (
            f"{host}/Audio/{item_id}/universal"
            f"?UserId={user_id}&api_key={token}"
            f"&MaxStreamingBitrate=320000&Container=mp3,aac,ogg,opus,flac"
            f"&TranscodingContainer=mp3&TranscodingProtocol=http"
            f"&AudioCodec=mp3&PlaySessionId=jftool{re.sub(chr(45), '', item_id)[:16]}"
        )
        download_url = f"{host}/Items/{item_id}/Download?api_key={token}"

        p, pa, pm, pg = _vivid_palette()
        pid = "jfm" + re.sub(r"[^a-zA-Z0-9]", "", item_id)[:12]

        duration_s = rm

        def chip(text, ci):
            return (
                f'<span style="background:{pa[ci]};color:{p[ci]};'
                f"border:1.5px solid {pm[ci]};"
                f"font-size:10px;font-weight:900;letter-spacing:.5px;"
                f"padding:3px 11px;border-radius:20px;white-space:nowrap;"
                f'box-shadow:0 0 10px {pa[ci]};">'
                f"{text}</span>"
            )

        chips_html = ""
        if comm_rating:
            chips_html += chip(f"★ {comm_rating:.1f}", 1)
        for i, g in enumerate(genres[:3]):
            chips_html += chip(g, (i + 2) % 5)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{
  background:linear-gradient(135deg,#060608 0%,#0c0810 40%,#080c10 100%);
  font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;
  height:auto;overflow:hidden;padding:6px;
}}

.card{{
  border-radius:24px;overflow:hidden;
  background:linear-gradient(160deg,#0d0d14 0%,#0a0a0e 100%);
  border:1px solid {pm[0]};
  box-shadow:0 0 0 1px {pa[0]},0 0 80px {pa[1]},0 0 160px {pa[3]},0 30px 80px rgba(0,0,0,.95);
}}

.stripe{{
  height:3px;
  background:linear-gradient(90deg,{p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[0]});
  background-size:300% 100%;
  animation:ss 3s linear infinite;
}}
@keyframes ss{{0%{{background-position:0%}}100%{{background-position:300%}}}}

.hero{{
  display:flex;
  background:linear-gradient(160deg,#0e0e16 0%,#0a0a10 100%);
  position:relative;overflow:hidden;min-height:200px;
  padding:28px 28px 24px;gap:24px;align-items:flex-start;
}}
.hero::before{{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:
    radial-gradient(ellipse 80% 100% at 0% 0%,{pa[0]} 0%,transparent 55%),
    radial-gradient(ellipse 60% 80% at 100% 100%,{pa[2]} 0%,transparent 60%),
    radial-gradient(ellipse 50% 60% at 50% 50%,{pa[4]} 0%,transparent 65%);
}}

.art-wrap{{
  flex-shrink:0;width:140px;height:140px;border-radius:16px;overflow:hidden;
  position:relative;z-index:1;
  box-shadow:0 0 0 2px {pm[0]},0 0 40px {pa[1]},0 8px 30px rgba(0,0,0,.8);
  transition:transform .3s;
}}
.art-wrap:hover{{transform:scale(1.03) rotate(-1deg);}}
.art-wrap img{{width:100%;height:100%;object-fit:cover;display:block;}}
.art-wrap .art-fallback{{
  width:100%;height:100%;background:linear-gradient(135deg,{pa[0]},{pa[2]},{pa[4]});
  display:flex;align-items:center;justify-content:center;font-size:48px;
}}
.art-ring{{
  position:absolute;inset:-3px;border-radius:19px;
  background:conic-gradient({p[0]},{p[1]},{p[2]},{p[3]},{p[4]},{p[0]});
  animation:spin 4s linear infinite;z-index:0;
}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.art-outer{{position:relative;flex-shrink:0;width:140px;height:140px;z-index:1;}}

.meta{{flex:1;min-width:0;position:relative;z-index:1;padding-top:4px;}}
.track-num{{
  font-size:9px;font-weight:900;letter-spacing:2px;text-transform:uppercase;
  color:{p[4]};opacity:.7;margin-bottom:6px;
}}
.track-title{{
  font-size:26px;font-weight:900;color:#fff;line-height:1.1;
  letter-spacing:-.4px;margin-bottom:6px;
  text-shadow:0 2px 20px {pa[0]};
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}}
.track-artist{{
  font-size:14px;color:{p[1]};font-weight:700;margin-bottom:3px;
  text-shadow:0 0 16px {pa[1]};
}}
.track-album{{
  font-size:12px;color:#555;margin-bottom:12px;
}}
.chips{{display:flex;flex-wrap:wrap;gap:5px;}}

.player{{
  padding:20px 24px 24px;
  background:linear-gradient(180deg,{pa[0]} 0%,transparent 40%),
             linear-gradient(180deg,#0d0d14 0%,#0a0a0e 100%);
  border-top:1px solid {pm[0]};
  position:relative;
}}
.player::before{{
  content:'';position:absolute;top:0;left:10%;right:10%;height:1px;
  background:linear-gradient(90deg,transparent,{pm[1]},transparent);
}}

.waveform-wrap{{position:relative;margin-bottom:14px;cursor:pointer;}}
canvas#wv_{pid}{{
  width:100%;height:60px;display:block;border-radius:8px;
  background:rgba(0,0,0,.3);
}}
.progress-line{{
  position:absolute;top:0;bottom:0;width:2px;
  background:linear-gradient(180deg,{p[0]},{p[2]});
  box-shadow:0 0 8px {pg[0]};
  pointer-events:none;border-radius:2px;
  transition:left .1s linear;
}}

.time-row{{
  display:flex;justify-content:space-between;
  font-size:11px;color:#444;font-family:'SF Mono','Fira Code',monospace;
  margin-bottom:14px;letter-spacing:.5px;
}}

.transport{{
  display:flex;align-items:center;justify-content:center;gap:18px;margin-bottom:18px;
}}
.btn-play{{
  width:56px;height:56px;border-radius:50%;border:none;cursor:pointer;
  background:linear-gradient(135deg,{p[0]},{p[2]});
  color:#000;display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 30px {pg[0]};transition:all .2s;flex-shrink:0;
}}
.btn-play:hover{{transform:scale(1.08);box-shadow:0 0 50px {pg[0]};}}
.btn-play svg{{margin-left:2px;}}
.btn-skip{{
  width:38px;height:38px;border-radius:50%;border:1.5px solid {pm[2]};cursor:pointer;
  background:{pa[2]};color:{p[2]};
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 16px {pa[2]};transition:all .2s;flex-shrink:0;
}}
.btn-skip:hover{{border-color:{p[2]};box-shadow:0 0 28px {pm[2]};background:{pm[2]};color:#000;}}

.bottom-row{{
  display:flex;align-items:center;gap:12px;
  border-top:1px solid {pa[1]};padding-top:14px;flex-wrap:wrap;
}}
.vol-wrap{{display:flex;align-items:center;gap:8px;flex:1;min-width:120px;}}
.vol-icon{{color:{p[3]};flex-shrink:0;}}
input[type=range].vol-slider{{
  -webkit-appearance:none;appearance:none;
  flex:1;height:4px;border-radius:2px;outline:none;cursor:pointer;
  background:linear-gradient(to right,{p[3]} var(--vol,70%),#2a2a35 var(--vol,70%));
}}
input[type=range].vol-slider::-webkit-slider-thumb{{
  -webkit-appearance:none;width:14px;height:14px;border-radius:50%;
  background:{p[3]};box-shadow:0 0 10px {pg[3]};cursor:pointer;
}}

.dl-btn{{
  display:inline-flex;align-items:center;gap:6px;
  background:linear-gradient(135deg,{pa[3]},{pa[2]});
  color:{p[3]};border:1.5px solid {pm[3]};border-radius:20px;
  font-size:11px;font-weight:900;padding:5px 14px;text-decoration:none;
  box-shadow:0 0 16px {pa[3]};transition:all .2s;white-space:nowrap;
}}
.dl-btn:hover{{background:linear-gradient(135deg,{pm[3]},{pm[2]});color:#fff;transform:translateY(-1px);}}

.eq-badge{{
  display:flex;align-items:flex-end;gap:2px;height:18px;margin-left:4px;
}}
.eq-bar{{
  width:3px;border-radius:2px;
  background:linear-gradient(180deg,{p[0]},{p[2]});
  animation:eq var(--d,.6s) ease-in-out infinite alternate;
}}
@keyframes eq{{from{{height:4px}}to{{height:var(--h,14px)}}}}
</style>
</head>
<body>
<div class="card">
  <div class="stripe"></div>

  <div class="hero">
    <div class="art-outer">
      <div class="art-ring"></div>
      <div class="art-wrap">
        <img id="art_{pid}" src="{art_url}" alt=""
             onerror="this.style.display='none';document.getElementById('art_fb_{pid}').style.display='flex'">
        <div class="art-fallback" id="art_fb_{pid}" style="display:none;">🎵</div>
      </div>
    </div>
    <div class="meta">
      <div class="track-num">Now Playing</div>
      <div class="track-title">{title}</div>
      {"" if not artist_str else f'<div class="track-artist">{artist_str}</div>'}
      {"" if not album else f'<div class="track-album">{album}{" · " + str(year) if year else ""}</div>'}
      <div class="chips">{chips_html}</div>
    </div>
  </div>

  <div class="player">
    <div class="waveform-wrap" id="ww_{pid}">
      <canvas id="wv_{pid}" height="60"></canvas>
      <div class="progress-line" id="pl_{pid}" style="left:0%"></div>
    </div>

    <div class="time-row">
      <span id="ct_{pid}">0:00</span>
      <span id="dt_{pid}">{dur_str}</span>
    </div>

    <div class="transport">
      <button class="btn-skip" id="bk_{pid}" title="Seek -10s">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.54"/>
          <text x="7" y="16" font-size="7" fill="currentColor" stroke="none" font-weight="bold">10</text>
        </svg>
      </button>
      <button class="btn-play" id="bp_{pid}" title="Play/Pause">
        <svg id="bpi_{pid}" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5,3 19,12 5,21"/>
        </svg>
      </button>
      <button class="btn-skip" id="fw_{pid}" title="Seek +10s">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-.49-3.54"/>
          <text x="7" y="16" font-size="7" fill="currentColor" stroke="none" font-weight="bold">10</text>
        </svg>
      </button>
    </div>

    <div class="bottom-row">
      <div class="vol-wrap">
        <svg class="vol-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
        <input type="range" class="vol-slider" id="vol_{pid}" min="0" max="100" value="80">
      </div>
      <div class="eq-badge" id="eq_{pid}" style="display:none;">
        <div class="eq-bar" style="--d:.5s;--h:10px;"></div>
        <div class="eq-bar" style="--d:.3s;--h:16px;animation-delay:.1s"></div>
        <div class="eq-bar" style="--d:.4s;--h:12px;animation-delay:.2s"></div>
        <div class="eq-bar" style="--d:.6s;--h:8px; animation-delay:.05s"></div>
        <div class="eq-bar" style="--d:.35s;--h:14px;animation-delay:.15s"></div>
      </div>
      <a class="dl-btn" href="{download_url}" download>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>Download
      </a>
    </div>
  </div>
</div>

<audio id="aud_{pid}" preload="metadata" src="{audio_url}"></audio>

<script>
(function() {{
  var PID  = {_json.dumps(pid)};
  var DUR  = {duration_s};
  var aud  = document.getElementById("aud_"  + PID);
  var bp   = document.getElementById("bp_"   + PID);
  var bpi  = document.getElementById("bpi_"  + PID);
  var bk   = document.getElementById("bk_"   + PID);
  var fw   = document.getElementById("fw_"   + PID);
  var ct   = document.getElementById("ct_"   + PID);
  var dt   = document.getElementById("dt_"   + PID);
  var pl   = document.getElementById("pl_"   + PID);
  var ww   = document.getElementById("ww_"   + PID);
  var wvc  = document.getElementById("wv_"   + PID);
  var vol  = document.getElementById("vol_"  + PID);
  var eq   = document.getElementById("eq_"   + PID);
  var ctx2 = wvc ? wvc.getContext("2d") : null;
  var bars = [];
  var BAR_COUNT = 80;
  var COLORS = [{_json.dumps(p[0])},{_json.dumps(p[1])},{_json.dumps(p[2])},{_json.dumps(p[3])},{_json.dumps(p[4])}];

  (function genBars() {{
    for (var i=0; i<BAR_COUNT; i++) {{
      var base = 0.2 + Math.random()*0.5;
      var spk  = Math.random() < 0.12 ? 0.7+Math.random()*0.3 : base;
      bars.push(spk);
    }}
    for (var s=0; s<3; s++) {{
      for (var i=1; i<bars.length-1; i++) bars[i]=(bars[i-1]+bars[i]*2+bars[i+1])/4;
    }}
  }})();

  function fmtTime(s) {{
    s = Math.floor(s||0);
    return Math.floor(s/60) + ':' + String(s%60).padStart(2,'0');
  }}

  function drawWaveform(progress) {{
    if (!ctx2 || !wvc) return;
    var W = (wvc.offsetWidth || 400) * (window.devicePixelRatio||1);
    var H = 60 * (window.devicePixelRatio||1);
    if (wvc.width !== W) {{ wvc.width = W; wvc.height = H; }}
    ctx2.clearRect(0,0,W,H);
    var bw = W / BAR_COUNT;
    var gap = Math.max(1, bw * 0.25);
    for (var i=0; i<BAR_COUNT; i++) {{
      var x = i * bw + gap/2;
      var bh = bars[i] * H * 0.85;
      var y = (H - bh) / 2;
      var frac = i / BAR_COUNT;
      var col = frac < progress ? COLORS[Math.floor(frac * COLORS.length)] : 'rgba(255,255,255,0.12)';
      ctx2.fillStyle = col;
      ctx2.fillRect(x, y, Math.max(1, bw-gap), bh);
    }}
  }}

  function updateProgress() {{
    var dur = aud.duration || DUR || 1;
    var prog = (aud.currentTime || 0) / dur;
    pl.style.left = (prog * 100).toFixed(2) + '%';
    ct.textContent = fmtTime(aud.currentTime);
    if (aud.duration) dt.textContent = fmtTime(aud.duration);
    drawWaveform(prog);
  }}

  ww.addEventListener("click", function(e) {{
    var rect = ww.getBoundingClientRect();
    var frac = (e.clientX - rect.left) / rect.width;
    var dur  = aud.duration || DUR || 1;
    aud.currentTime = frac * dur;
    updateProgress();
  }});

  bp.addEventListener("click", function() {{
    if (aud.paused) {{ aud.play(); }} else {{ aud.pause(); }}
  }});
  bk.addEventListener("click", function() {{ aud.currentTime = Math.max(0, aud.currentTime-10); }});
  fw.addEventListener("click", function() {{ aud.currentTime = Math.min(aud.duration||9999, aud.currentTime+10); }});

  aud.volume = 0.8;
  vol.addEventListener("input", function() {{
    aud.volume = this.value / 100;
    vol.style.setProperty('--vol', this.value + '%');
  }});
  vol.style.setProperty('--vol', '80%');

  aud.addEventListener("play", function() {{
    bpi.innerHTML = '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>';
    eq.style.display = 'flex';
  }});
  aud.addEventListener("pause", function() {{
    bpi.innerHTML = '<polygon points="5,3 19,12 5,21"/>';
    eq.style.display = 'none';
  }});
  aud.addEventListener("timeupdate", updateProgress);
  aud.addEventListener("loadedmetadata", function() {{
    dt.textContent = fmtTime(aud.duration);
    drawWaveform(0);
  }});
  aud.addEventListener("ended", function() {{
    bpi.innerHTML = '<polygon points="5,3 19,12 5,21"/>';
    eq.style.display = 'none';
    pl.style.left = '0%';
    drawWaveform(0);
  }});

  setTimeout(function() {{
    drawWaveform(0);
    try {{
      window.parent.postMessage(
        {{type:"iframe-resize", id:PID, height:document.documentElement.scrollHeight}},
        "*"
      );
    }} catch(e) {{}}
  }}, 0);
  window.addEventListener("resize", function() {{ setTimeout(updateProgress, 50); }});
}})();
</script>
</body>
</html>""".strip()

        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    # ══ Public tools ══════════════════════════════════════════════════════════

    async def search_and_play(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Search Jellyfin and embed an interactive video player.
        Supports movies, episodes (SxxExx / NxNN), and loose title searches.
        :param query: e.g. "Shrek", "South Park S02E03", "Breaking Bad s3e10"
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        clean, sn, en = self._parse_episode_query(query)
        is_ep = sn is not None and en is not None
        await _emit(__event_emitter__, f"🔍 Searching for '{query}'…")

        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ Jellyfin auth failed: {exc}"

            item = None
            if is_ep:
                await _emit(
                    __event_emitter__, f"📺 Resolving {clean} S{sn:02d}E{en:02d}…"
                )
                item = await self._find_episode(
                    session, host, user_id, token, clean, sn, en
                )
                if not item:
                    await _emit(__event_emitter__, "❌ Episode not found", done=True)
                    return f"❌ Could not find **{clean}** S{sn:02d}E{en:02d}."
            else:
                auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
                async with session.get(
                    f"{host}/Users/{user_id}/Items?searchTerm={query}"
                    f"&IncludeItemTypes=Movie,Episode,Video&Recursive=true&Limit=5"
                    f"&Fields=Overview,ProductionYear,RunTimeTicks,SeriesId,SeriesName,"
                    f"SeasonName,CommunityRating,CriticRating,OfficialRating,Genres,"
                    f"People,Taglines,Studios",
                    headers=auth_h,
                ) as resp:
                    if resp.status != 200:
                        await _emit(__event_emitter__, "❌ Search failed", done=True)
                        return f"❌ Search failed: HTTP {resp.status}"
                    d = await resp.json()
                items = d.get("Items", [])
                if not items:
                    await _emit(__event_emitter__, "❌ No results", done=True)
                    return f"❌ No results for '{query}'."
                item = items[0]

        title = item.get("Name", "Unknown")
        await _emit(__event_emitter__, f"⚙ Preparing '{title}'…")
        player = await self._build_player(host, item, token, user_id)
        await _emit(__event_emitter__, f"▶ Now playing: {title}", done=True)
        return player

    async def search_and_play_music(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Search Jellyfin music library and embed a beautiful audio player.
        :param query: Song title, artist, or album name e.g. "Bohemian Rhapsody", "Drake", "Thriller"
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        await _emit(__event_emitter__, f"🎵 Searching music for '{query}'…")

        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ Jellyfin auth failed: {exc}"

            auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
            async with session.get(
                f"{host}/Users/{user_id}/Items?searchTerm={query}"
                f"&IncludeItemTypes=Audio&Recursive=true&Limit=5"
                f"&Fields=Overview,ProductionYear,RunTimeTicks,Artists,AlbumArtists,"
                f"Album,AlbumId,CommunityRating,Genres,IndexNumber,ParentIndexNumber",
                headers=auth_h,
            ) as resp:
                if resp.status != 200:
                    await _emit(__event_emitter__, "❌ Search failed", done=True)
                    return f"❌ Search failed: HTTP {resp.status}"
                d = await resp.json()

        items = d.get("Items", [])
        if not items:
            await _emit(__event_emitter__, "❌ No music found", done=True)
            return f"❌ No music found for '{query}'."

        item = items[0]
        title = item.get("Name", "Unknown")
        await _emit(__event_emitter__, f"🎶 Loading: {title}…")
        player = await self._build_music_player(host, item, token, user_id)
        await _emit(__event_emitter__, f"▶ Now playing: {title}", done=True)
        return player

    async def random_movie(
        self,
        genre: str = "",
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Pick and play a random movie from Jellyfin.
        :param genre: Optional genre filter e.g. "Comedy". Leave blank for any.
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        await _emit(
            __event_emitter__, f"🎲 Picking random {genre+' ' if genre else ''}movie…"
        )
        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ {exc}"
            auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
            gp = f"&Genres={genre}" if genre else ""
            async with session.get(
                f"{host}/Users/{user_id}/Items?IncludeItemTypes=Movie&Recursive=true"
                f"&Limit=300&SortBy=Random"
                f"&Fields=Overview,ProductionYear,RunTimeTicks,CommunityRating,CriticRating,"
                f"OfficialRating,Genres,People,Taglines,Studios{gp}",
                headers=auth_h,
            ) as resp:
                if resp.status != 200:
                    await _emit(__event_emitter__, "❌ Failed", done=True)
                    return f"❌ HTTP {resp.status}"
                d = await resp.json()
        items = d.get("Items", [])
        if not items:
            await _emit(__event_emitter__, "No movies found", done=True)
            return f"❌ No movies found{' for genre: '+genre if genre else ''}."
        item = random.choice(items)
        title = item.get("Name", "?")
        await _emit(__event_emitter__, f"🎬 Picked: {title}")
        player = await self._build_player(host, item, token, user_id)
        await _emit(__event_emitter__, f"▶ Now playing: {title}", done=True)
        return player

    async def random_song(
        self,
        genre: str = "",
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Pick and play a random song from Jellyfin music library.
        :param genre: Optional genre filter e.g. "Rock". Leave blank for any.
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        await _emit(
            __event_emitter__, f"🎲 Picking random {genre+' ' if genre else ''}song…"
        )
        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ {exc}"
            auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
            gp = f"&Genres={genre}" if genre else ""
            async with session.get(
                f"{host}/Users/{user_id}/Items?IncludeItemTypes=Audio&Recursive=true"
                f"&Limit=300&SortBy=Random"
                f"&Fields=Overview,ProductionYear,RunTimeTicks,Artists,AlbumArtists,"
                f"Album,AlbumId,CommunityRating,Genres,IndexNumber{gp}",
                headers=auth_h,
            ) as resp:
                if resp.status != 200:
                    await _emit(__event_emitter__, "❌ Failed", done=True)
                    return f"❌ HTTP {resp.status}"
                d = await resp.json()
        items = d.get("Items", [])
        if not items:
            await _emit(__event_emitter__, "No songs found", done=True)
            return f"❌ No songs found{' for genre: '+genre if genre else ''}."
        item = random.choice(items)
        title = item.get("Name", "?")
        await _emit(__event_emitter__, f"🎵 Picked: {title}")
        player = await self._build_music_player(host, item, token, user_id)
        await _emit(__event_emitter__, f"▶ Now playing: {title}", done=True)
        return player

    async def random_episode(
        self,
        series_name: str = "",
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Pick and play a random TV episode from Jellyfin.
        :param series_name: Optional filter e.g. "South Park". Blank = any show.
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        await _emit(
            __event_emitter__,
            f"🎲 Picking random episode{' of '+series_name if series_name else ''}…",
        )
        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ {exc}"
            auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
            if series_name:
                async with session.get(
                    f"{host}/Users/{user_id}/Items?searchTerm={series_name}"
                    f"&IncludeItemTypes=Series&Recursive=true&Limit=5",
                    headers=auth_h,
                ) as r:
                    d = await r.json()
                series = d.get("Items", [])
                if not series:
                    await _emit(__event_emitter__, "❌ Not found", done=True)
                    return f"❌ Series '{series_name}' not found."
                sid = series[0]["Id"]
                ep_url = (
                    f"{host}/Users/{user_id}/Items?ParentId={sid}"
                    f"&IncludeItemTypes=Episode&Recursive=true&Limit=500&SortBy=Random"
                    f"&Fields=Overview,RunTimeTicks,SeriesId,SeriesName,SeasonName,"
                    f"CommunityRating,OfficialRating,Genres,People,Taglines,Studios"
                )
            else:
                ep_url = (
                    f"{host}/Users/{user_id}/Items?IncludeItemTypes=Episode"
                    f"&Recursive=true&Limit=300&SortBy=Random"
                    f"&Fields=Overview,RunTimeTicks,SeriesId,SeriesName,SeasonName,"
                    f"CommunityRating,OfficialRating,Genres,People,Taglines,Studios"
                )
            async with session.get(ep_url, headers=auth_h) as r:
                if r.status != 200:
                    await _emit(__event_emitter__, "❌ Failed", done=True)
                    return f"❌ HTTP {r.status}"
                d = await r.json()
        eps = d.get("Items", [])
        if not eps:
            await _emit(__event_emitter__, "No episodes found", done=True)
            return "❌ No episodes found."
        item = random.choice(eps)
        sname = item.get("SeriesName", "")
        en = item.get("IndexNumber", "")
        e_str = f"E{en:02d}" if isinstance(en, int) else ""
        display = (
            f"{sname} {e_str} · {item.get('Name','')}"
            if sname
            else item.get("Name", "")
        )
        await _emit(__event_emitter__, f"🎬 Picked: {display}")
        player = await self._build_player(host, item, token, user_id)
        await _emit(__event_emitter__, f"▶ Now playing: {display}", done=True)
        return player

    async def get_item_info(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        Fetch metadata about a movie/show/episode WITHOUT opening a player.
        :param query: Title, optionally with SxxExx notation.
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        clean, sn, en = self._parse_episode_query(query)
        is_ep = sn is not None and en is not None
        await _emit(__event_emitter__, f"🔍 Fetching info for '{query}'…")
        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ {exc}"
            item = None
            if is_ep:
                item = await self._find_episode(
                    session, host, user_id, token, clean, sn, en
                )
            else:
                auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
                async with session.get(
                    f"{host}/Users/{user_id}/Items?searchTerm={query}"
                    f"&IncludeItemTypes=Movie,Series,Episode&Recursive=true&Limit=5"
                    f"&Fields=Overview,ProductionYear,RunTimeTicks,SeriesName,SeasonName,"
                    f"CommunityRating,CriticRating,OfficialRating,Genres,People,Taglines,"
                    f"Studios,ProviderIds,PremiereDate,EndDate,Status",
                    headers=auth_h,
                ) as resp:
                    if resp.status != 200:
                        await _emit(__event_emitter__, "❌ Failed", done=True)
                        return f"❌ HTTP {resp.status}"
                    d = await resp.json()
                items = d.get("Items", [])
                if not items:
                    await _emit(__event_emitter__, "❌ Not found", done=True)
                    return f"❌ Not found: '{query}'"
                item = items[0]
                if item.get("Type") == "Series":
                    sid = item["Id"]
                    async with session.get(
                        f"{host}/Shows/{sid}/Seasons?UserId={user_id}",
                        headers=auth_h,
                    ) as r2:
                        if r2.status == 200:
                            item["_seasons"] = (await r2.json()).get("Items", [])
        if not item:
            await _emit(__event_emitter__, "❌ Not found", done=True)
            return f"❌ Could not find '{query}'."
        L = []
        itype = item.get("Type", "")
        title = item.get("Name", "?")
        year = item.get("ProductionYear", "")
        ticks = item.get("RunTimeTicks", 0)
        rm = round(ticks / 600_000_000) if ticks else None
        rt_str = (f"{rm//60}h {rm%60}m" if rm and rm >= 60 else f"{rm}m") if rm else ""
        hdr = f"[{itype}] {title}"
        if itype == "Episode":
            sname = item.get("SeriesName", "")
            _sn = item.get("ParentIndexNumber")
            _en = item.get("IndexNumber")
            ep_lbl = (
                f"S{_sn:02d}E{_en:02d}"
                if isinstance(_sn, int) and isinstance(_en, int)
                else ""
            )
            hdr = f"[Episode] {sname} — {ep_lbl} · {title}"
        L += [hdr, "=" * len(hdr)]
        for k, v in [
            ("Year", str(year) if year else ""),
            (
                "Premiere",
                (item.get("PremiereDate", "")[:10] if item.get("PremiereDate") else ""),
            ),
            ("Status", item.get("Status", "")),
            ("Rating", item.get("OfficialRating", "")),
            ("Runtime", rt_str),
            (
                "Community Score",
                (
                    f"{item.get('CommunityRating'):.1f}/10"
                    if item.get("CommunityRating")
                    else ""
                ),
            ),
            (
                "Critic Score (RT)",
                (
                    f"{int(item.get('CriticRating'))}%"
                    if item.get("CriticRating") is not None
                    else ""
                ),
            ),
            ("Genres", ", ".join(item.get("Genres") or [])),
            (
                "Studios",
                ", ".join(s.get("Name", "") for s in (item.get("Studios") or [])),
            ),
        ]:
            if v:
                L.append(f"{k}: {v}")
        tgs = item.get("Taglines") or []
        if tgs:
            L += [f'\nTagline: "{tgs[0]}"']
        ov = item.get("Overview", "")
        if ov:
            L += [f"\nPlot:\n{ov}"]
        people = item.get("People") or []
        dirs = [p["Name"] for p in people if p.get("Type") == "Director"]
        wri = [p["Name"] for p in people if p.get("Type") == "Writer"]
        cast = [p["Name"] for p in people if p.get("Type") == "Actor"][:10]
        if dirs:
            L.append(f"\nDirector(s): {', '.join(dirs)}")
        if wri:
            L.append(f"Writer(s): {', '.join(wri)}")
        if cast:
            L.append(f"Cast: {', '.join(cast)}")
        seasons = item.get("_seasons", [])
        if seasons:
            L.append(f"\nSeasons: {len(seasons)}")
            for s in seasons:
                L.append(f"  • {s.get('Name','')} ({s.get('ProductionYear','?')})")
        pids = item.get("ProviderIds") or {}
        links = []
        if "Imdb" in pids:
            links.append(f"IMDb: https://www.imdb.com/title/{pids['Imdb']}/")
        if "Tmdb" in pids:
            links.append(f"TMDb: {pids['Tmdb']}")
        if links:
            L += ["\nExternal Links:"] + [f"  • {x}" for x in links]
        await _emit(__event_emitter__, f"✅ Info: {title}", done=True)
        return "\n".join(L)

    async def list_recent(
        self,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """Show the 12 most recently added items in Jellyfin."""
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        await _emit(__event_emitter__, "📂 Fetching recently added…")
        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ {exc}"
            auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
            async with session.get(
                f"{host}/Users/{user_id}/Items/Latest?Limit=12"
                f"&Fields=ProductionYear,RunTimeTicks,SeriesName",
                headers=auth_h,
            ) as resp:
                if resp.status != 200:
                    await _emit(__event_emitter__, "❌ Failed", done=True)
                    return f"❌ HTTP {resp.status}"
                items = await resp.json()
        if not items:
            await _emit(__event_emitter__, "Empty", done=True)
            return "No recently added items."
        p, pa, pm, pg = _vivid_palette()

        def _disp(it):
            n = it.get("Name", "?")
            if it.get("Type") == "Episode":
                s = it.get("SeriesName", "")
                e = it.get("IndexNumber", "")
                ep = f"E{e:02d} · " if isinstance(e, int) else ""
                return f"{s} — {ep}{n}" if s else n
            return n

        rows = "".join(
            f"<tr><td style='padding:8px 14px;color:#e0e0e0;border-bottom:1px solid #161618;'>{_disp(it)}</td>"
            f"<td style='padding:8px 14px;color:#444;border-bottom:1px solid #161618;font-size:11px;'>{it.get('ProductionYear','')}</td>"
            f"<td style='padding:8px 14px;border-bottom:1px solid #161618;'>"
            f"<span style='font-size:9px;font-weight:900;background:{pa[2]};color:{p[2]};padding:2px 9px;border-radius:20px;border:1px solid {pm[2]};'>{it.get('Type','')}</span>"
            f"</td></tr>"
            for it in items
        )
        html = (
            f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{background:transparent;font-family:-apple-system,sans-serif;padding:4px;}}"
            f"table{{width:100%;border-collapse:collapse;background:#0a0a0d;border-radius:12px;overflow:hidden;box-shadow:0 0 0 1px {pa[0]},0 0 40px {pa[1]};}}"
            f"th{{padding:10px 14px;text-align:left;color:{p[0]};font-weight:900;font-size:9px;letter-spacing:1px;text-transform:uppercase;border-bottom:2px solid {pm[0]};background:#0e0e12;text-shadow:0 0 14px {pa[0]};}}"
            f"tr:last-child td{{border-bottom:none!important;}}.foot{{font-size:11px;color:#333;margin-top:8px;text-align:center;}}</style></head>"
            f"<body><table><thead><tr><th>Title</th><th>Year</th><th>Type</th></tr></thead><tbody>{rows}</tbody></table>"
            f'<p class="foot">Say "play [title]" to watch.</p></body></html>'
        )
        await _emit(__event_emitter__, "✅ Done", done=True)
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})

    async def search_library(
        self,
        query: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Search Jellyfin and return results table without auto-playing.
        :param query: Search term — title, actor, genre, etc.
        """
        host = self.valves.JELLYFIN_HOST.rstrip("/")
        await _emit(__event_emitter__, f"🔎 Searching '{query}'…")
        async with aiohttp.ClientSession() as session:
            try:
                token, user_id = await self._get_token(session)
            except Exception as exc:
                await _emit(__event_emitter__, "❌ Auth failed", done=True)
                return f"❌ {exc}"
            auth_h = {"Authorization": f'MediaBrowser Token="{token}"'}
            async with session.get(
                f"{host}/Users/{user_id}/Items?searchTerm={query}"
                f"&IncludeItemTypes=Movie,Series,Episode,Audio&Recursive=true&Limit=10"
                f"&Fields=ProductionYear,RunTimeTicks,SeriesName,CommunityRating,OfficialRating,Genres,Artists",
                headers=auth_h,
            ) as resp:
                if resp.status != 200:
                    await _emit(__event_emitter__, "❌ Failed", done=True)
                    return f"❌ HTTP {resp.status}"
                d = await resp.json()
        items = d.get("Items", [])
        if not items:
            await _emit(__event_emitter__, "No results", done=True)
            return f"No results for '{query}'."
        p, pa, pm, pg = _vivid_palette()

        def _row(it):
            n = it.get("Name", "?")
            itype = it.get("Type", "")
            year = it.get("ProductionYear", "")
            rat = it.get("CommunityRating")
            ticks = it.get("RunTimeTicks", 0)
            rt = f"{round(ticks/600_000_000)}m" if ticks else ""
            stars = f"★{rat:.1f}" if rat else ""
            sub = " · ".join(x for x in [str(year), rt, stars] if x)
            if itype == "Episode":
                s = it.get("SeriesName", "")
                e = it.get("IndexNumber", "")
                ep = f"E{e:02d} · " if isinstance(e, int) else ""
                n = f"{s} — {ep}{n}" if s else n
            elif itype == "Audio":
                artists = it.get("Artists") or []
                a = ", ".join(artists[:2])
                n = f"{n}" + (f" — {a}" if a else "")
            ci = {"Movie": 0, "Series": 1, "Episode": 2, "Audio": 3}.get(itype, 4)
            return (
                f"<tr><td style='padding:8px 14px;color:#e0e0e0;border-bottom:1px solid #161618;'>{n}</td>"
                f"<td style='padding:8px 14px;color:#444;border-bottom:1px solid #161618;font-size:11px;'>{sub}</td>"
                f"<td style='padding:8px 14px;border-bottom:1px solid #161618;'>"
                f"<span style='font-size:9px;font-weight:900;background:{pa[ci%5]};color:{p[ci%5]};padding:2px 9px;border-radius:20px;border:1px solid {pm[ci%5]};'>{itype}</span></td></tr>"
            )

        rows = "".join(_row(i) for i in items)
        count = d.get("TotalRecordCount", len(items))
        html = (
            f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{background:transparent;font-family:-apple-system,sans-serif;padding:4px;}}"
            f".hd{{font-size:13px;font-weight:900;color:#fff;margin-bottom:8px;}}.ct{{font-size:11px;color:#444;font-weight:400;}}"
            f"table{{width:100%;border-collapse:collapse;background:#0a0a0d;border-radius:12px;overflow:hidden;box-shadow:0 0 0 1px {pa[0]},0 0 40px {pa[1]};}}"
            f"th{{padding:10px 14px;text-align:left;color:{p[0]};font-weight:900;font-size:9px;letter-spacing:1px;text-transform:uppercase;border-bottom:2px solid {pm[0]};background:#0e0e12;text-shadow:0 0 14px {pa[0]};}}"
            f"tr:last-child td{{border-bottom:none!important;}}.foot{{font-size:11px;color:#333;margin-top:8px;text-align:center;}}</style></head>"
            f'<body><div class="hd">🔎 &ldquo;{query}&rdquo; <span class="ct">({count} results)</span></div>'
            f"<table><thead><tr><th>Title</th><th>Info</th><th>Type</th></tr></thead><tbody>{rows}</tbody></table>"
            f'<p class="foot">Say "play [title]" to watch, or "play music [song]" to listen.</p></body></html>'
        )
        await _emit(__event_emitter__, f"✅ {len(items)} results", done=True)
        return HTMLResponse(content=html, headers={"content-disposition": "inline"})
