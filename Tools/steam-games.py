"""
title: Steam Game Info (Rich UI)
description: Fetches Steam game info and renders a beautiful interactive card directly in chat — shows artwork, screenshot gallery, price, review score, tags, description, and a link to the store. No API key required.
author: ichrist
version: 2.0.0
requirements: requests, beautifulsoup4
"""

import json
import re
import urllib.parse
from typing import Awaitable, Callable, Optional

import requests
from bs4 import BeautifulSoup
from fastapi.responses import HTMLResponse

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
COOKIES = {"birthtime": "0", "lastagecheckage": "1-0-1990"}


def _search_steam(game_name: str) -> Optional[dict]:
    """Returns {app_id, url} or None."""
    url = (
        "https://store.steampowered.com/search/suggest"
        f"?term={urllib.parse.quote(game_name)}&f=games&cc=US&l=english"
    )
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.find("a")
    if not link:
        return None
    href = link.get("href", "").split("?")[0].rstrip("/")
    m = re.search(r"/app/(\d+)", href)
    return {"app_id": m.group(1), "url": href} if m else None


def _api_details(app_id: str) -> Optional[dict]:
    url = (
        f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=english"
    )
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    outer = resp.json().get(app_id, {})
    return outer.get("data") if outer.get("success") else None


def _scrape_review(app_id: str) -> str:
    url = f"https://store.steampowered.com/app/{app_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, cookies=COOKIES, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        spans = soup.find_all("span", class_="game_review_summary")
        return spans[-1].get_text(strip=True) if spans else "N/A"
    except Exception:
        return "N/A"


# ─────────────────────────────────────────────────────────────────────────────
#  HTML card builder
# ─────────────────────────────────────────────────────────────────────────────


def _gallery_html(screenshots):
    if not screenshots:
        return ""
    thumbs = "".join(
        '<div class="g-thumb{}" data-idx="{}"><img src="{}" loading="lazy" alt="Screenshot {}"/></div>'.format(
            " active" if i == 0 else "", i, s, i + 1
        )
        for i, s in enumerate(screenshots)
    )
    return (
        '<div class="gallery-wrap">'
        '<div class="gallery-main">'
        '<img id="gallery-main-img" src="{}" alt="Screenshot" loading="lazy"/>'
        "</div>"
        '<div class="gallery-thumbs">{}</div>'
        "</div>"
    ).format(screenshots[0], thumbs)


def _build_html(data: dict, review: str, store_url: str) -> str:
    title = data.get("name", "Unknown")
    short_desc = data.get("short_description", "")
    header_img = data.get("header_image", "")
    background = data.get("background", header_img)
    release = data.get("release_date", {}).get("date", "?")
    devs = ", ".join(data.get("developers", []))
    pubs = ", ".join(data.get("publishers", []))
    genres = [g["description"] for g in data.get("genres", [])]
    categories = [c["description"] for c in data.get("categories", [])][:6]
    tags = genres + categories

    metacritic = data.get("metacritic", {})
    meta_score = metacritic.get("score") if metacritic else None

    price_info = data.get("price_overview")
    if price_info:
        price_final = price_info.get("final_formatted", "?")
        price_original = price_info.get("initial_formatted", "")
        discount = price_info.get("discount_percent", 0)
    elif data.get("is_free"):
        price_final, price_original, discount = "Free to Play", "", 0
    else:
        price_final, price_original, discount = "Coming Soon", "", 0

    screenshots = [
        s.get("path_full", s.get("path_thumbnail", ""))
        for s in data.get("screenshots", [])[:8]
        if s.get("path_full") or s.get("path_thumbnail")
    ]

    review_lower = review.lower()
    if "overwhelmingly positive" in review_lower or "very positive" in review_lower:
        review_color = "#66c0f4"
    elif "positive" in review_lower or "mostly positive" in review_lower:
        review_color = "#a7d5a8"
    elif "mixed" in review_lower:
        review_color = "#c6b68e"
    else:
        review_color = "#e06b6b"

    ss_json = json.dumps(screenshots)
    tags_html = "".join('<span class="tag">{}</span>'.format(t) for t in tags[:8])

    discount_badge = (
        '<span class="discount-badge">-{}%</span>'.format(discount)
        if discount > 0
        else ""
    )
    price_original_html = (
        "<span class='price-original'>{}</span>".format(price_original)
        if price_original
        else ""
    )

    if discount > 0:
        price_bg = "background:var(--price-bg);"
        price_color = "color:var(--price-text);"
        price_padding = "padding:3px 8px;"
        price_radius = "border-radius:4px;"
    else:
        price_bg = price_padding = price_radius = ""
        price_color = "color:var(--accent);"

    meta_html = (
        '<div class="meta-score" title="Metacritic score">{}</div>'.format(meta_score)
        if meta_score
        else ""
    )

    publisher_html = "Publisher: {}".format(pubs) if pubs else ""
    dev_meta = "<span>Developer: {}</span>".format(devs) if devs else ""
    desc_html = "<div class='desc'>{}</div>".format(short_desc) if short_desc else ""
    tags_section = "<div class='tags'>{}</div>".format(tags_html) if tags_html else ""
    gallery_section = _gallery_html(screenshots)

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  :root {{
    --bg: #1b2838;
    --surface: #1e2d3d;
    --surface2: #16202c;
    --border: #2a475e;
    --text: #c6d4df;
    --text-dim: #7391a0;
    --accent: #66c0f4;
    --green: #a7d5a8;
    --price-bg: #4c6b22;
    --price-text: #beee11;
    --radius: 8px;
    --shadow: 0 4px 24px rgba(0,0,0,.55);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Arial", sans-serif;
    background: transparent;
    color: var(--text);
    padding: 8px;
  }}
  .card {{
    background: var(--bg);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: var(--shadow);
    border: 1px solid var(--border);
    max-width: 760px;
  }}
  .hero {{
    position: relative;
    height: 220px;
    background: var(--surface2);
    overflow: hidden;
  }}
  .hero-bg {{
    position: absolute; inset: 0;
    width: 100%; height: 100%;
    object-fit: cover;
    filter: brightness(.4) blur(3px);
    transform: scale(1.06);
  }}
  .hero-logo {{
    position: absolute; left: 50%; top: 50%;
    transform: translate(-50%,-50%);
    max-width: 340px; max-height: 160px;
    object-fit: contain;
    filter: drop-shadow(0 2px 16px rgba(0,0,0,.9));
    border-radius: 6px;
  }}
  .body {{ padding: 16px; display: flex; flex-direction: column; gap: 12px; }}
  .top {{ display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }}
  .thumb {{
    flex-shrink: 0; width: 116px; height: 54px;
    border-radius: var(--radius); overflow: hidden;
    border: 1px solid var(--border);
  }}
  .thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
  .info {{ flex: 1; min-width: 0; }}
  .title {{ font-size: 1.2rem; font-weight: 700; color: #fff; line-height: 1.2; margin-bottom: 4px; }}
  .meta-row {{ font-size: .75rem; color: var(--text-dim); }}
  .meta-row span + span::before {{ content: " · "; }}
  .stat-row {{
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 10px 14px;
    border: 1px solid var(--border);
  }}
  .review-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    font-size: .85rem; font-weight: 700;
    color: {review_color};
  }}
  .review-dot {{ width: 8px; height: 8px; border-radius: 50%; background: {review_color}; flex-shrink: 0; }}
  .meta-score {{
    background: #4a90d9; color: #fff; font-size: .82rem; font-weight: 900;
    width: 34px; height: 34px; border-radius: 4px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }}
  .spacer {{ flex: 1; }}
  .price-block {{ display: flex; align-items: center; gap: 8px; }}
  .discount-badge {{
    background: #4c6b22; color: #beee11;
    font-size: .78rem; font-weight: 700;
    padding: 3px 8px; border-radius: 4px;
  }}
  .price-original {{ font-size: .78rem; color: var(--text-dim); text-decoration: line-through; }}
  .price-final {{
    font-size: 1.05rem; font-weight: 700;
    {price_color}{price_bg}{price_padding}{price_radius}
  }}
  .desc {{ font-size: .83rem; line-height: 1.6; color: var(--text-dim); }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .tag {{
    font-size: .71rem; padding: 3px 10px;
    border-radius: 14px; border: 1px solid var(--border);
    color: var(--text-dim); background: var(--surface2);
  }}
  .gallery-wrap {{ display: flex; flex-direction: column; gap: 8px; }}
  .gallery-main {{
    width: 100%; aspect-ratio: 16/9;
    border-radius: var(--radius); overflow: hidden;
    background: var(--surface2); cursor: pointer;
    border: 1px solid var(--border);
  }}
  .gallery-main img {{ width: 100%; height: 100%; object-fit: cover; transition: opacity .2s; }}
  .gallery-thumbs {{ display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; }}
  .gallery-thumbs::-webkit-scrollbar {{ height: 4px; }}
  .gallery-thumbs::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
  .g-thumb {{
    flex-shrink: 0; width: 94px; height: 53px;
    border-radius: 4px; overflow: hidden;
    border: 2px solid transparent; cursor: pointer; transition: border-color .15s;
  }}
  .g-thumb.active {{ border-color: var(--accent); }}
  .g-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
  .footer {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 10px; flex-wrap: wrap;
    border-top: 1px solid var(--border);
    padding: 12px 16px;
    background: var(--surface2);
  }}
  .dev-info {{ font-size: .74rem; color: var(--text-dim); }}
  .store-btn {{
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--accent); color: #000; font-weight: 700;
    font-size: .82rem; padding: 7px 16px; border-radius: 5px;
    text-decoration: none; transition: opacity .15s;
  }}
  .store-btn:hover {{ opacity: .85; }}
</style>
</head>
<body>

<div class="card">
  <div class="hero">
    <img class="hero-bg" src="{background}" alt="" loading="lazy"/>
    <img class="hero-logo" src="{header_img}" alt="{title}" loading="lazy"/>
  </div>

  <div class="body">
    <div class="top">
      <div class="thumb"><img src="{header_img}" alt=""/></div>
      <div class="info">
        <div class="title">{title}</div>
        <div class="meta-row">
          <span>Released: {release}</span>
          {dev_meta}
        </div>
      </div>
    </div>

    <div class="stat-row">
      <div class="review-pill">
        <div class="review-dot"></div>
        {review}
      </div>
      {meta_html}
      <div class="spacer"></div>
      <div class="price-block">
        {discount_badge}
        {price_original_html}
        <span class="price-final">{price_final}</span>
      </div>
    </div>

    {desc_html}
    {tags_section}
    {gallery_section}
  </div>

  <div class="footer">
    <div class="dev-info">{publisher_html}</div>
    <a class="store-btn" href="{store_url}" target="_blank" rel="noopener">&#9654; View on Steam</a>
  </div>
</div>

<script>
  var screenshots = {ss_json};
  if (screenshots.length > 0) {{
    var mainImg = document.getElementById('gallery-main-img');
    var thumbs  = document.querySelectorAll('.g-thumb');
    var current = 0;
    function setSlide(idx) {{
      current = idx;
      if (mainImg) mainImg.src = screenshots[idx];
      thumbs.forEach(function(t,i){{ t.classList.toggle('active', i===idx); }});
    }}
    thumbs.forEach(function(t,i){{ t.addEventListener('click', function(){{ setSlide(i); }}); }});
    if (mainImg) mainImg.addEventListener('click', function(){{ setSlide((current+1) % screenshots.length); }});
  }}

  function reportHeight() {{
    var h = document.documentElement.scrollHeight;
    parent.postMessage({{ type: 'iframe:height', height: h }}, '*');
  }}
  window.addEventListener('load', reportHeight);
  if (typeof ResizeObserver !== 'undefined') {{
    new ResizeObserver(reportHeight).observe(document.body);
  }}
</script>
</body>
</html>""".format(
        review_color=review_color,
        price_color=price_color,
        price_bg=price_bg,
        price_padding=price_padding,
        price_radius=price_radius,
        background=background,
        header_img=header_img,
        title=title,
        release=release,
        dev_meta=dev_meta,
        review=review,
        meta_html=meta_html,
        discount_badge=discount_badge,
        price_original_html=price_original_html,
        price_final=price_final,
        desc_html=desc_html,
        tags_section=tags_section,
        gallery_section=gallery_section,
        store_url=store_url,
        publisher_html=publisher_html,
        ss_json=ss_json,
    )


def _error_html(msg: str) -> str:
    return (
        "<!DOCTYPE html><html><head><style>"
        "body{font-family:Arial,sans-serif;background:#1b2838;color:#c6d4df;"
        "display:flex;align-items:center;justify-content:center;"
        "height:80px;margin:0;padding:16px;}"
        "</style></head><body>&#9888; " + msg + "</body></html>"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Tool class
# ─────────────────────────────────────────────────────────────────────────────


class Tools:
    def __init__(self):
        self.citation = False

    async def get_steam_game_info(
        self,
        game_name: str,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        """
        Look up a game on Steam and display a rich interactive card in chat.
        The card shows the game's artwork, a scrollable screenshot gallery
        (click any thumbnail or the main image to browse), current price with
        any active discount, review score, genres, tags, description, and a
        direct link to the Steam store page. No API key is needed.

        Use this when the user asks about a game's price, cost, reviews, rating,
        screenshots, images, artwork, or general information about a Steam game.

        :param game_name: The name of the game to look up on Steam.
        :return: Interactive Steam card embedded directly in the chat.
        """

        async def status(msg: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": msg, "done": done}}
                )

        # Search
        await status("🔍 Searching Steam for '{}'…".format(game_name))
        try:
            result = _search_steam(game_name)
        except Exception as e:
            await status("❌ Search failed", done=True)
            return (
                HTMLResponse(
                    content=_error_html("Steam search failed: {}".format(e)),
                    headers={"Content-Disposition": "inline"},
                ),
                "Error: {}".format(e),
            )

        if not result:
            await status("❌ Game not found", done=True)
            return (
                HTMLResponse(
                    content=_error_html(
                        "No results for '{}' on Steam.".format(game_name)
                    ),
                    headers={"Content-Disposition": "inline"},
                ),
                "No results found for '{}'".format(game_name),
            )

        app_id = result["app_id"]
        store_url = "https://store.steampowered.com/app/{}/".format(app_id)

        # API details
        await status("📦 Fetching game details…")
        try:
            data = _api_details(app_id)
        except Exception as e:
            await status("❌ API error", done=True)
            return (
                HTMLResponse(
                    content=_error_html("Steam API error: {}".format(e)),
                    headers={"Content-Disposition": "inline"},
                ),
                "API error: {}".format(e),
            )

        if not data:
            await status("❌ No data returned", done=True)
            return (
                HTMLResponse(
                    content=_error_html("Steam returned no data for this game."),
                    headers={"Content-Disposition": "inline"},
                ),
                "No data found",
            )

        # Reviews
        await status("⭐ Fetching review summary…")
        review = _scrape_review(app_id)

        # Render card
        await status("🎨 Building game card…")
        html = _build_html(data, review, store_url)

        await status("✅ Done!", done=True)

        # Brief text context for the LLM
        price_info = data.get("price_overview")
        price_str = (
            price_info.get("final_formatted", "?")
            if price_info
            else ("Free to Play" if data.get("is_free") else "Coming Soon")
        )
        ctx = (
            "{name} is {price} on Steam. Reviews: {review}. "
            "Released: {date}. The card with screenshots and full details "
            "is now displayed in the chat."
        ).format(
            name=data.get("name", game_name),
            price=price_str,
            review=review,
            date=data.get("release_date", {}).get("date", "?"),
        )

        return (
            HTMLResponse(content=html, headers={"Content-Disposition": "inline"}),
            ctx,
        )
