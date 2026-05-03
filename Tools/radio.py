"""
title: Radio Tool
author: ichrist
author_url: https://openwebui.com/u/ichrist
version: 3.1.0
license: MIT
description: Stream any radio station worldwide — search by name, country, or genre with a polished dark-mode player and full scrollable station list. Powered by Radio Browser API. Full HLS/.m3u8 support via hls.js. BBC stations use verified worldwide stream URLs. Zero config, zero API keys.
requirements: requests
"""

import re
import requests
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────────────
# Verified worldwide BBC HLS stream URLs (updated Jan 2025+).
# These replace the broken/geo-restricted URLs returned by Radio Browser.
# Ordered longest-match-first so "Radio 1Xtra" is matched before "Radio 1".
# ──────────────────────────────────────────────────────────────────────────────
BBC_STREAM_OVERRIDES = [
    ("1xtra", "https://lstn.lv/bbcradio.m3u8?station=bbc_1xtra&bitrate=320000"),
    (
        "radio 1",
        "https://as-hls-ww-live.akamaized.net/pool_01505109/live/ww/bbc_radio_one/bbc_radio_one.isml/bbc_radio_one-audio=96000.norewind.m3u8",
    ),
    ("radio 2", "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_two&bitrate=320000"),
    ("radio 3", "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_three&bitrate=320000"),
    (
        "radio 4 extra",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_four_extra&bitrate=320000",
    ),
    (
        "radio 4",
        "https://as-hls-ww-live.akamaized.net/pool_904/live/ww/bbc_radio_fourfm/bbc_radio_fourfm.isml/bbc_radio_fourfm-audio=320000.m3u8",
    ),
    (
        "5 live sports extra",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_five_live_sports_extra&bitrate=320000",
    ),
    (
        "radio 5",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_five_live&bitrate=320000",
    ),
    (
        "5 live",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_five_live&bitrate=320000",
    ),
    ("6 music", "https://lstn.lv/bbcradio.m3u8?station=bbc_6music&bitrate=320000"),
    ("6music", "https://lstn.lv/bbcradio.m3u8?station=bbc_6music&bitrate=320000"),
    ("radio 6", "https://lstn.lv/bbcradio.m3u8?station=bbc_6music&bitrate=320000"),
    (
        "asian network",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_asian_network&bitrate=320000",
    ),
    (
        "world service",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_world_service&bitrate=320000",
    ),
    (
        "scotland",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_scotland_fm&bitrate=320000",
    ),
    (
        "wales",
        "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_wales_fm&bitrate=320000",
    ),
    ("ulster", "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_ulster&bitrate=320000"),
    ("cymru", "https://lstn.lv/bbcradio.m3u8?station=bbc_radio_cymru&bitrate=320000"),
    ("london", "https://lstn.lv/bbcradio.m3u8?station=bbc_london&bitrate=320000"),
    ("news", "https://lstn.lv/bbcradio.m3u8?station=bbc_world_service&bitrate=320000"),
]


def _patch_bbc_url(station: dict) -> dict:
    """
    If this station is a BBC station, replace its stream URL with a verified
    worldwide HLS URL. Returns a shallow copy so the original is not mutated.
    """
    name = (station.get("name") or "").lower()
    if "bbc" not in name:
        return station
    for keyword, hls_url in BBC_STREAM_OVERRIDES:
        if keyword in name:
            patched = dict(station)
            patched["url_resolved"] = hls_url
            patched["url"] = hls_url
            return patched
    return station


class Tools:
    class Valves(BaseModel):
        max_stations: int = Field(
            default=100,
            description="Max stations to fetch from API (bump up for larger countries)",
        )
        default_country: str = Field(
            default="",
            description="Default country code fallback (e.g. US, GB, DE, IL)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.headers = {
            "User-Agent": "OpenWebUI-RadioTool/3.1",
            "Accept": "application/json",
        }
        self._fallback_servers = [
            "https://de1.api.radio-browser.info/json",
            "https://nl1.api.radio-browser.info/json",
            "https://at1.api.radio-browser.info/json",
        ]

    def _api_get(self, path: str, params: dict = None) -> list:
        for server in self._fallback_servers:
            try:
                r = requests.get(
                    f"{server}/{path}",
                    params=params or {},
                    headers=self.headers,
                    timeout=15,
                )
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
        return []

    def _flag(self, code: str) -> str:
        code = (code or "").upper().strip()
        if len(code) != 2:
            return ""
        return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)

    def _build_stations_list(self, pool: list, active_uuid: str) -> str:
        """Build the scrollable station list HTML."""
        items_html = ""
        for s in pool:
            s = _patch_bbc_url(s)
            sname = (s.get("name") or "Unknown").strip()
            surl = (s.get("url_resolved") or s.get("url") or "").replace("'", "&#39;")
            sfav = (s.get("favicon") or "").replace("'", "&#39;")
            sname_safe = sname.replace("'", "&#39;")
            sflag = self._flag(s.get("countrycode") or "")
            suuid = s.get("stationuuid") or ""
            stags = s.get("tags") or ""
            sgenre_parts = [t.strip().title() for t in stags.split(",") if t.strip()][
                :1
            ]
            sgenre_str = sgenre_parts[0] if sgenre_parts else "Radio"
            is_active = suuid == active_uuid

            if sfav:
                favicon_block = f'<img src="{sfav}" onerror="this.style.display=\'none\'" class="s-fav">'
            else:
                favicon_block = '<span class="s-fav s-fav-placeholder">📻</span>'

            items_html += f"""
            <div onclick="switchStation('{surl}','{sname_safe}','{sfav}','{sflag}')"
                 class="s-item{' s-active' if is_active else ''}"
                 data-uuid="{suuid}">
                {favicon_block}
                <div class="s-info">
                    <div class="s-name">{sflag} {sname}</div>
                    <div class="s-meta">{sgenre_str}</div>
                </div>
                <div class="s-arrow">▶</div>
            </div>"""
        return items_html

    def _render(self, station: dict, pool: list = None) -> str:
        station = _patch_bbc_url(station)

        name = (station.get("name") or "Unknown Station").strip()
        stream_url = (station.get("url_resolved") or station.get("url") or "").strip()
        favicon = (station.get("favicon") or "").strip()
        country = (station.get("country") or "").strip()
        cc = (station.get("countrycode") or "").upper().strip()
        tags = station.get("tags") or ""
        bitrate = station.get("bitrate") or 0
        codec = (station.get("codec") or "").strip()
        language = (station.get("language") or "").strip()
        votes = station.get("votes") or 0
        homepage = (station.get("homepage") or "").strip()
        uuid = station.get("stationuuid") or ""

        flag = self._flag(cc)
        genre_list = [t.strip().title() for t in tags.split(",") if t.strip()][:3]
        genre_str = " · ".join(genre_list) if genre_list else "Radio"
        quality = f"{bitrate}kbps" if bitrate else ""

        favicon_html = ""
        icon_display = "flex"
        if favicon:
            favicon_html = f'<img id="r-fav" src="{favicon}" onerror="this.style.display=\'none\';document.getElementById(\'r-ico\').style.display=\'flex\'" class="main-fav">'
            icon_display = "none"

        bitrate_badge = ""
        lang_badge = ""
        vote_badge = ""
        site_badge = ""
        if quality:
            bitrate_badge = f'<span class="badge badge-green">{quality} {codec}</span>'
        elif codec:
            bitrate_badge = f'<span class="badge badge-green">{codec}</span>'
        if language:
            lang_badge = f'<span class="badge badge-blue">{language.title()}</span>'
        if votes:
            vote_badge = f'<span class="badge badge-amber">♥ {votes:,}</span>'
        if homepage:
            site_badge = f'<a href="{homepage}" target="_blank" class="badge badge-slate">🌐 Website</a>'
        badges = bitrate_badge + lang_badge + vote_badge + site_badge

        stations_html = self._build_stations_list(pool or [], uuid)
        station_count = len(pool or [])
        stream_url_repr = repr(stream_url)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.7/hls.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:transparent;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden;}}

:root{{--bg0:#0b0e14;--bg1:#111827;--bg2:#1e293b;--bg3:#273549;--line:rgba(255,255,255,0.06);--text:#e5e7eb;--text2:#9ca3af;--text3:#6b7280;--accent:#818cf8;--accent2:#6366f1;--pink:#f472b6;--green:#34d399;--amber:#fbbf24;--red:#f87171}}

.card{{max-width:640px;width:100%;background:linear-gradient(160deg,#0b0e14 0%,#111827 50%,#0f172a 100%);border-radius:20px;border:1px solid rgba(244,114,182,0.15);overflow:hidden;display:flex;flex-direction:column;max-height:580px;position:relative;}}
.card::before{{content:'';position:absolute;top:-80px;left:-80px;width:260px;height:260px;background:radial-gradient(circle,rgba(99,102,241,0.12) 0%,transparent 70%);border-radius:50%;pointer-events:none}}
.card::after{{content:'';position:absolute;bottom:-60px;right:-60px;width:220px;height:220px;background:radial-gradient(circle,rgba(244,114,182,0.08) 0%,transparent 70%);border-radius:50%;pointer-events:none}}

.player{{padding:22px 24px 18px;flex-shrink:0;background:rgba(0,0,0,0.2);border-bottom:1px solid var(--line);position:relative;z-index:1}}
.p-header{{display:flex;align-items:center;gap:16px;margin-bottom:16px}}
.main-fav{{width:64px;height:64px;border-radius:14px;object-fit:cover;box-shadow:0 4px 20px rgba(0,0,0,0.5);flex-shrink:0}}
.r-ico{{width:64px;height:64px;border-radius:14px;background:linear-gradient(135deg,#1e1b4b,#1e293b);border:1px solid rgba(129,140,248,0.3);display:flex;align-items:center;justify-content:center;font-size:28px;box-shadow:0 4px 20px rgba(0,0,0,0.5);flex-shrink:0}}
.live-badge{{position:absolute;top:16px;right:24px;background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;font-size:8px;font-weight:800;padding:3px 8px;border-radius:6px;letter-spacing:.12em;box-shadow:0 0 10px rgba(239,68,68,0.5);animation:livepulse 1.8s ease-in-out infinite}}
.p-info{{flex:1;min-width:0}}
.p-name{{font-size:17px;font-weight:700;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3}}
.p-country{{font-size:12px;color:var(--text2);margin-top:3px}}
.p-genre{{font-size:11px;color:var(--accent);margin-top:3px;font-weight:600}}

.wave{{display:flex;align-items:flex-end;justify-content:center;gap:2px;height:32px;margin-bottom:14px;padding:0 8px}}
.wb{{width:3px;border-radius:2px;background:linear-gradient(to top,var(--accent2),var(--pink));transform-origin:bottom}}
.wb.on{{animation:rwave .6s ease-in-out infinite}}

.controls{{display:flex;align-items:center;gap:14px}}
.play-btn{{width:50px;height:50px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--pink));border:none;cursor:pointer;font-size:18px;color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(99,102,241,0.4);transition:all .15s;flex-shrink:0}}
.play-btn:hover{{transform:scale(1.08);box-shadow:0 6px 28px rgba(99,102,241,0.6)}}
.vol-wrap{{flex:1}}
.vol-bar{{width:100%;height:4px;-webkit-appearance:none;appearance:none;border-radius:4px;background:var(--bg3);outline:none;cursor:pointer;accent-color:var(--accent)}}
.vol-labels{{display:flex;justify-content:space-between;margin-top:4px}}
.vol-labels span{{font-size:10px;color:var(--text3)}}
.status{{font-size:11px;color:var(--text3);font-weight:600;text-align:center;transition:color .3s}}

.badges{{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}}
.badge{{padding:3px 9px;border-radius:16px;font-size:10px;font-weight:600;text-decoration:none;}}
.badge-green{{background:rgba(52,211,153,0.1);color:var(--green);border:1px solid rgba(52,211,153,0.2)}}
.badge-blue{{background:rgba(96,165,250,0.1);color:#60a5fa;border:1px solid rgba(96,165,250,0.2)}}
.badge-amber{{background:rgba(251,191,36,0.1);color:var(--amber);border:1px solid rgba(251,191,36,0.2)}}
.badge-slate{{background:rgba(148,163,184,0.08);color:var(--text2);border:1px solid rgba(148,163,184,0.15)}}

.search-bar{{padding:12px 16px;flex-shrink:0;border-bottom:1px solid var(--line);position:relative;z-index:1}}
.search-bar input{{width:100%;padding:10px 14px 10px 38px;border-radius:12px;border:1px solid var(--line);background:var(--bg2);color:var(--text);font-size:13px;font-family:inherit;outline:none;transition:border-color .2s}}
.search-bar input:focus{{border-color:var(--accent)}}
.search-bar input::placeholder{{color:var(--text3)}}
.search-bar .search-icon{{position:absolute;left:28px;top:50%;transform:translateY(-50%);font-size:14px;color:var(--text3)}}
.search-bar .count{{position:absolute;right:20px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--text3);font-weight:600}}

.stations{{flex:1;overflow-y:auto;position:relative;z-index:1}}
.stations::-webkit-scrollbar{{width:5px}}
.stations::-webkit-scrollbar-track{{background:transparent}}
.stations::-webkit-scrollbar-thumb{{background:var(--bg3);border-radius:4px}}
.stations::-webkit-scrollbar-thumb:hover{{background:var(--text3)}}

.s-item{{display:flex;align-items:center;gap:10px;padding:9px 16px;cursor:pointer;transition:all .15s;border-bottom:1px solid rgba(255,255,255,0.03)}}
.s-item:hover{{background:rgba(99,102,241,0.08)}}
.s-item.s-active{{background:rgba(99,102,241,0.12);border-left:3px solid var(--accent);padding-left:13px}}
.s-item.s-active .s-arrow{{color:var(--accent)}}
.s-fav{{width:34px;height:34px;border-radius:8px;object-fit:cover;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.4)}}
.s-fav-placeholder{{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;background:var(--bg2)}}
.s-info{{flex:1;min-width:0}}
.s-name{{font-size:12.5px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.s-meta{{font-size:10px;color:var(--text3);margin-top:1px}}
.s-arrow{{font-size:9px;color:var(--text3);flex-shrink:0}}
.no-results{{padding:30px 16px;text-align:center;color:var(--text3);font-size:13px}}

@keyframes rwave{{0%,100%{{transform:scaleY(0.2)}}50%{{transform:scaleY(1)}}}}
@keyframes livepulse{{0%,100%{{opacity:1;box-shadow:0 0 10px rgba(239,68,68,0.5)}}50%{{opacity:.75;box-shadow:0 0 16px rgba(239,68,68,0.8)}}}}

audio{{display:none}}
</style>
</head>
<body>
<div class="card">

  <div class="player">
    <div class="live-badge" id="live-badge">LIVE</div>
    <div class="p-header">
      <div style="position:relative">
        {favicon_html}
        <div id="r-ico" class="r-ico" style="display:{icon_display}">📻</div>
      </div>
      <div class="p-info">
        <div id="r-name" class="p-name">{name}</div>
        <div class="p-country">{flag} {country}</div>
        <div class="p-genre">{genre_str}</div>
      </div>
    </div>

    <div class="wave" id="r-wave">
      {"".join(f'<div class="wb" style="height:{h}px;animation-delay:{i*0.06:.2f}s"></div>' for i,h in enumerate([10,22,16,30,8,26,18,34,12,28,20,14,32,8,24,16,30,10,26,18,34,12,22,8,28,14,20,8]))}
    </div>

    <audio id="r-audio" preload="none"></audio>

    <div class="controls">
      <button onclick="rToggle()" id="r-btn" class="play-btn">▶</button>
      <div class="vol-wrap">
        <input type="range" id="r-vol" class="vol-bar" min="0" max="1" step="0.01" value="0.8" oninput="rVol(this.value)">
        <div class="vol-labels">
          <span>🔇</span>
          <div id="r-status" class="status">Connecting…</div>
          <span>🔊</span>
        </div>
      </div>
    </div>

    <div class="badges">{badges}</div>
  </div>

  <div class="search-bar">
    <span class="search-icon">🔍</span>
    <input type="text" id="s-search" placeholder="Filter stations…" oninput="filterStations()">
    <span class="count" id="s-count">{station_count} stations</span>
  </div>

  <div class="stations" id="s-list">
    {stations_html}
  </div>

</div>

<script>
(function(){{
  var audio = document.getElementById('r-audio');
  var btn   = document.getElementById('r-btn');
  var stat  = document.getElementById('r-status');
  var bars  = document.querySelectorAll('.wb');
  var playing = false;
  var url = {stream_url_repr};
  var hlsInstance = null;

  /* ── helpers ── */
  function wave(on) {{ bars.forEach(function(b){{ on ? b.classList.add('on') : b.classList.remove('on'); }}); }}

  function setPlaying(v) {{
    playing = v;
    btn.textContent = v ? '⏸' : '▶';
    if(v) {{ stat.style.color='var(--accent)'; stat.textContent='● On Air'; wave(true); }}
    else  {{ stat.style.color='var(--text3)';  stat.textContent='Paused';   wave(false); }}
  }}

  function destroyHls() {{
    if(hlsInstance) {{ try{{ hlsInstance.destroy(); }}catch(e){{}} hlsInstance = null; }}
  }}

  /* ── core stream starter — handles HLS (.m3u8) and plain streams ── */
  function startStream(streamUrl) {{
    destroyHls();
    audio.pause();
    audio.removeAttribute('src');
    audio.load();

    stat.style.color = 'var(--text2)';
    stat.textContent = 'Connecting…';

    var isHls = streamUrl.indexOf('.m3u8') !== -1 || streamUrl.indexOf('lstn.lv') !== -1;

    if(isHls && typeof Hls !== 'undefined' && Hls.isSupported()) {{
      /* Modern browsers: use hls.js */
      hlsInstance = new Hls({{ enableWorker: false, lowLatencyMode: true }});
      hlsInstance.loadSource(streamUrl);
      hlsInstance.attachMedia(audio);
      hlsInstance.on(Hls.Events.MANIFEST_PARSED, function() {{
        audio.volume = parseFloat(document.getElementById('r-vol').value);
        audio.play()
          .then(function() {{ setPlaying(true); }})
          .catch(function() {{ stat.style.color='var(--text3)'; stat.textContent='Tap ▶ to tune in'; }});
      }});
      hlsInstance.on(Hls.Events.ERROR, function(ev, data) {{
        if(data.fatal) {{
          stat.style.color = 'var(--red)';
          stat.textContent = 'Stream error — tap ▶ to retry';
          playing = false; btn.textContent = '▶'; wave(false);
          destroyHls();
        }}
      }});
    }} else if(isHls && audio.canPlayType('application/vnd.apple.mpegurl')) {{
      /* Safari: native HLS support */
      audio.src = streamUrl;
      audio.load();
      audio.volume = parseFloat(document.getElementById('r-vol').value);
      audio.play()
        .then(function() {{ setPlaying(true); }})
        .catch(function() {{ stat.style.color='var(--text3)'; stat.textContent='Tap ▶ to tune in'; }});
    }} else {{
      /* Plain MP3 / AAC / ICY streams */
      audio.src = streamUrl;
      audio.load();
      audio.volume = parseFloat(document.getElementById('r-vol').value);
      audio.play()
        .then(function() {{ setPlaying(true); }})
        .catch(function() {{ stat.style.color='var(--text3)'; stat.textContent='Tap ▶ to tune in'; }});
    }}
  }}

  /* ── play / pause toggle ── */
  window.rToggle = function() {{
    if(playing) {{
      audio.pause();
      destroyHls();
      audio.removeAttribute('src');
      audio.load();
      setPlaying(false);
    }} else {{
      startStream(url);
    }}
  }};

  window.rVol = function(v) {{ audio.volume = parseFloat(v); }};

  /* ── switch station from list ── */
  window.switchStation = function(newUrl, newName, newFav, newFlag) {{
    url = newUrl;
    var wasPlaying = playing;

    /* stop current stream cleanly */
    if(playing) {{ audio.pause(); destroyHls(); audio.removeAttribute('src'); audio.load(); playing = false; wave(false); }}

    /* update UI */
    document.getElementById('r-name').textContent = newFlag + ' ' + newName;
    var img = document.getElementById('r-fav');
    var ico = document.getElementById('r-ico');
    if(newFav && img) {{ img.src = newFav; img.style.display = 'block'; if(ico) ico.style.display = 'none'; }}
    else if(ico)      {{ ico.style.display = 'flex'; if(img) img.style.display = 'none'; }}
    btn.textContent = '▶';
    stat.style.color = 'var(--text3)'; stat.textContent = 'Tap ▶ to tune in';

    /* highlight active item */
    var items = document.querySelectorAll('.s-item');
    for(var i = 0; i < items.length; i++) items[i].classList.remove('s-active');
    for(var i = 0; i < items.length; i++) {{
      var nm = items[i].querySelector('.s-name');
      if(nm && nm.textContent.indexOf(newName) !== -1) items[i].classList.add('s-active');
    }}

    if(wasPlaying) setTimeout(function(){{ startStream(url); }}, 150);
  }};

  /* ── filter station list ── */
  window.filterStations = function() {{
    var q = document.getElementById('s-search').value.toLowerCase();
    var items = document.querySelectorAll('.s-item');
    var visible = 0;
    for(var i = 0; i < items.length; i++) {{
      var txt = items[i].querySelector('.s-name').textContent.toLowerCase();
      if(txt.indexOf(q) !== -1) {{ items[i].style.display = 'flex'; visible++; }}
      else {{ items[i].style.display = 'none'; }}
    }}
    document.getElementById('s-count').textContent = visible + ' station' + (visible !== 1 ? 's' : '');
    if(visible === 0 && items.length > 0) {{
      var list = document.getElementById('s-list');
      if(!list.querySelector('.no-results')) {{
        var nd = document.createElement('div');
        nd.className = 'no-results'; nd.id = 'no-results';
        nd.textContent = 'No stations match your search';
        list.appendChild(nd);
      }}
    }} else if(document.getElementById('no-results')) {{
      document.getElementById('no-results').remove();
    }}
  }};

  /* ── generic audio error (for plain streams) ── */
  audio.addEventListener('error', function() {{
    if(!hlsInstance) {{
      stat.style.color = 'var(--red)'; stat.textContent = 'Stream error';
      playing = false; btn.textContent = '▶'; wave(false);
    }}
  }});

  /* ── auto-start ── */
  audio.volume = 0.8;
  startStream(url);

  /* ── report height to parent iframe ── */
  function reportHeight() {{
    var h = document.documentElement.scrollHeight;
    parent.postMessage({{type: 'iframe:height', height: h}}, '*');
  }}
  window.addEventListener('load', reportHeight);
  if(typeof ResizeObserver !== 'undefined') {{
    new ResizeObserver(reportHeight).observe(document.body);
  }}
}})();
</script>
</body>
</html>"""

    # ──────────────────────────────────────────────
    # PUBLIC TOOL METHODS
    # ──────────────────────────────────────────────

    def search_radio(self, query: str) -> tuple:
        """
        Search for a radio station by name and play it.
        USE THIS when the user asks to search for a radio station by name, like "BBC Radio 1", "NPR", "Absolute Radio", "Classic FM", etc.
        DO NOT use for country or genre requests — use radio_by_country or radio_by_genre instead.
        :param query: Station name to search for
        :return: Embedded radio player with the best match and nearby stations
        """
        stations = self._api_get(
            "stations/search",
            {
                "name": query,
                "limit": self.valves.max_stations,
                "hidebroken": "true",
                "order": "votes",
                "reverse": "true",
            },
        )
        valid = [s for s in stations if s.get("url_resolved") or s.get("url")]
        if not valid:
            return f"❌ No stations found for **'{query}'**. Try a different name, or ask for stations by country or genre instead."
        s = valid[0]
        return (
            HTMLResponse(
                content=self._render(s, valid),
                headers={"Content-Disposition": "inline"},
            ),
            f"Now playing {s.get('name', '')} — {s.get('country', '')} — {s.get('tags', '')}",
        )

    def radio_by_country(self, country_code: str) -> tuple:
        """
        Get the top radio stations for a given country. Fetches ALL available stations (up to the configured limit) so the user can scroll through the complete list and pick any station.
        USE THIS when the user asks for radio stations from a specific country.
        :param country_code: ISO 3166-1 alpha-2 country code (e.g. US, GB, DE, IL, FR, JP, BR, AU)
        :return: Embedded radio player with top stations for that country
        """
        cc = country_code.upper().strip()
        stations = self._api_get(
            f"stations/bycountrycodeexact/{cc}",
            {
                "limit": self.valves.max_stations,
                "hidebroken": "true",
                "order": "votes",
                "reverse": "true",
            },
        )
        valid = [s for s in stations if s.get("url_resolved") or s.get("url")]
        if not valid:
            return f"❌ No stations found for country code **'{cc}'**. Check the code (e.g. US, GB, DE, IL) and try again."
        s = valid[0]
        return (
            HTMLResponse(
                content=self._render(s, valid),
                headers={"Content-Disposition": "inline"},
            ),
            f"Showing top stations for {cc} ({len(valid)} found). Playing {s.get('name', '')} first.",
        )

    def radio_by_genre(self, genre: str) -> tuple:
        """
        Get radio stations by genre or music style.
        USE THIS when the user asks for a specific music genre or style.
        :param genre: Genre or tag (e.g. jazz, rock, classical, lofi, news, electronic, ambient, metal, pop, reggae, hip-hop)
        :return: Embedded radio player with top stations for that genre
        """
        tag = genre.lower().replace(" ", "")
        stations = self._api_get(
            f"stations/bytag/{tag}",
            {
                "limit": self.valves.max_stations,
                "hidebroken": "true",
                "order": "votes",
                "reverse": "true",
            },
        )
        valid = [s for s in stations if s.get("url_resolved") or s.get("url")]
        if not valid:
            stations = self._api_get(
                "stations/search",
                {
                    "tag": genre,
                    "limit": self.valves.max_stations,
                    "hidebroken": "true",
                    "order": "votes",
                    "reverse": "true",
                },
            )
            valid = [s for s in stations if s.get("url_resolved") or s.get("url")]
        if not valid:
            return f"❌ No stations found for genre **'{genre}'**. Try a different genre name."
        s = valid[0]
        return (
            HTMLResponse(
                content=self._render(s, valid),
                headers={"Content-Disposition": "inline"},
            ),
            f"Showing top {genre} stations ({len(valid)} found). Playing {s.get('name', '')} first.",
        )

    def radio_top_global(self) -> tuple:
        """
        Get the most popular radio stations globally right now.
        USE THIS when the user asks for top, popular, or trending radio stations worldwide.
        :return: Embedded radio player with the world's most popular stations
        """
        stations = self._api_get(
            "stations/topvote",
            {"limit": self.valves.max_stations, "hidebroken": "true"},
        )
        valid = [s for s in stations if s.get("url_resolved") or s.get("url")]
        if not valid:
            return "❌ Could not fetch top stations. Try searching by name or genre."
        s = valid[0]
        return (
            HTMLResponse(
                content=self._render(s, valid),
                headers={"Content-Disposition": "inline"},
            ),
            f"Showing top global stations by votes ({len(valid)} found). Playing {s.get('name', '')} first.",
        )
