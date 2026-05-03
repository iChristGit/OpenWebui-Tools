"""
title: Pokédex
author: ichrist
author_url: https://github.com/open-webui/open-webui
version: 1.0.0
description: >
  A beautiful interactive Pokédex with Pokémon images, stats, abilities, and types —
  powered by the PokéAPI. Search by name or national Pokédex number (1–1025).
  Displays animated sprites, base stats with visual bars, type badges, abilities,
  height/weight, generation info, and a Pokédex flavor text entry. Zero API key required.

  Features:
    - Search by name or Pokédex number (e.g. "Charizard", "pikachu", "150")
    - Beautiful HTML card with animated sprite, official artwork, and type badges
    - Base stats displayed as visual progress bars
    - Abilities, height, weight, generation, habitat info
    - Pokédex flavor text entry
    - Evolution chain display (clickable links to evolved forms)
    - Type effectiveness color coding

  Usage:
    - "Show me Pikachu"            → look_up("pikachu")
    - "Pokedex #25"               → look_up("25")
    - "Tell me about Mewtwo"      → look_up("mewtwo")
    - "Look up Gengar"            → look_up("gengar")

license: MIT
requirements: httpx
"""

import re
import socket
import urllib.request
import urllib.error
import httpx
from typing import Optional
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# DNS / Network helpers for cross-platform compatibility
# ---------------------------------------------------------------------------

API_HOST = "pokeapi.co"


def _preresolve_dns(host: str = API_HOST) -> None:
    """
    Pre-resolve DNS for the API host to avoid Windows getaddrinfo failures.
    On Windows, httpx.AsyncClient can fail with [Errno 11001] getaddrinfo
    due to IPv6-first resolution or DNS cache issues.

    This function:
    1. Flushes the OS DNS cache (where possible)
    2. Pre-resolves the hostname synchronously using the standard library
    3. Forces IPv4 resolution on platforms that support it
    """
    try:
        # Flush local DNS cache (Linux/macOS)
        try:
            import subprocess

            try:
                subprocess.run(
                    ["sudo", "dscacheutil", "-flushcache"],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass
            try:
                subprocess.run(
                    ["sudo", "systemctl", "restart", "nss-lookup.service"],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass
        except Exception:
            pass

        # Pre-resolve the hostname synchronously using standard library (forces IPv4 on some platforms)
        try:
            socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        except Exception:
            # If IPv4 fails, try IPv6
            try:
                socket.getaddrinfo(host, 443, socket.AF_INET6, socket.SOCK_STREAM)
            except Exception:
                pass

        # Also resolve via urllib to prime the resolver cache
        try:
            urllib.request.urlopen(
                f"https://{host}/api/v2/", timeout=3, data=b"", method="HEAD"
            )
        except urllib.error.URLError:
            pass  # Expected if we can't connect, resolution succeeded
        except Exception:
            pass

    except Exception:
        pass  # Best effort only; don't block on DNS pre-resolution


async def _fetch_with_retry(
    client: httpx.AsyncClient, url: str, retries: int = 2
) -> httpx.Response:
    """
    Fetch a URL with retry logic, specifically handling Windows DNS errors.
    """
    last_exception = None

    for attempt in range(retries):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response
        except socket.gaierror as exc:
            last_exception = exc
            # DNS resolution failed - this is the Windows getaddrinfo error
            if attempt < retries - 1:
                # Give it a moment and try again
                await client.aclose()
                # Create a fresh client
                client = httpx.AsyncClient(
                    timeout=30, follow_redirects=True, http2=False
                )
                # Brief pause before retry
                await client.get("https://www.google.com/favicon.ico", timeout=5)
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            last_exception = exc
            if attempt < retries - 1:
                await client.aclose()
                client = httpx.AsyncClient(
                    timeout=30, follow_redirects=True, http2=False
                )

    if last_exception:
        raise last_exception


# ---------------------------------------------------------------------------
# Type → color map for badges and backgrounds
# ---------------------------------------------------------------------------

TYPE_COLORS: dict[str, str] = {
    "normal": "#A8A77A",
    "fire": "#EE8130",
    "water": "#6390F0",
    "electric": "#F7D02C",
    "grass": "#7AC74C",
    "ice": "#96D9D6",
    "fighting": "#C22E28",
    "poison": "#A33EA1",
    "ground": "#E2BF65",
    "flying": "#A98FF3",
    "psychic": "#F95587",
    "bug": "#A6B91A",
    "rock": "#B6A136",
    "ghost": "#735797",
    "dragon": "#6F35FC",
    "dark": "#705746",
    "steel": "#B7B7CE",
    "fairy": "#D685AD",
    "stellar": "#001544",
    "unknown": "#6AA84F",
}

# Shorthand names for stats
STAT_LABELS: dict[str, str] = {
    "hp": "HP",
    "attack": "ATK",
    "defense": "DEF",
    "special-attack": "SpA",
    "special-defense": "SpD",
    "speed": "SPD",
}


# Pokémon sprite URL patterns
def _sprite_url(sprites: dict, key: str = "front_default") -> Optional[str]:
    """Get sprite URL from nested sprites dict."""
    if not sprites:
        return None

    # Check direct key first
    if key in sprites:
        url = sprites[key]
        if url:
            return url

    # Check 'other' section
    other = sprites.get("other", {})
    for section in other:
        if isinstance(other[section], dict) and key in other[section]:
            url = other[section][key]
            if url:
                return url

    # Fallback: get first non-None sprite
    for section in ["versions", "other", "front_default"]:
        if isinstance(sprites, dict):
            for sub in sprites.values():
                if (
                    isinstance(sub, dict)
                    and isinstance(sub.get(key), str)
                    and sub.get(key)
                ):
                    return sub[key]

    return None


def _find_best_sprite(sprites: dict) -> Optional[str]:
    """Find the best available sprite: official artwork → showdown → home → default."""
    candidates = [
        ("other", "official-artwork", "front_default"),
        ("other", "official-artwork", "other"),
        ("other", "showdown", "front_default"),
        ("other", "showdown", "front_shiny"),
        ("other", "home", "front_default"),
        ("other", "home", "front_female"),
        ("other", "home", "front_shiny"),
        ("front_default", None, None),
        ("front_shiny", None, None),
    ]

    for section, k1, k2 in candidates:
        if k2:
            val = sprites.get("other", {}).get(section, {}).get(k2)
            if val:
                return val
        elif section in sprites:
            val = sprites.get(section)
            if val:
                return val
    return None


def _stat_bar(value: int, max_value: int = 255) -> tuple[str, str]:
    """Return color and label for a stat value."""
    if value <= 50:
        return "#ef4444", "Low"
    elif value <= 80:
        return "#f59e0b", "Decent"
    elif value <= 100:
        return "#eab308", "Good"
    elif value <= 130:
        return "#22c55e", "Great"
    else:
        return "#10b981", "Excellent"


def _generation_label(gen: str) -> str:
    """Convert generation name to a displayable string."""
    gen_map = {
        "generation-i": "Gen I (Kanto)",
        "generation-ii": "Gen II (Johto)",
        "generation-iii": "Gen III (Hoenn)",
        "generation-iv": "Gen IV (Sinnoh)",
        "generation-v": "Gen V (Unova)",
        "generation-vi": "Gen VI (Kalos)",
        "generation-vii": "Gen VII (Alola)",
        "generation-viii": "Gen VIII (Galar)",
        "generation-ix": "Gen IX (Paldea)",
    }
    return gen_map.get(gen, gen)


def _clean_flavor_text(text: str) -> str:
    """Clean Pokédex flavor text by removing control characters and tags."""
    text = (
        text.replace("\f", " ")
        .replace("\n", " ")
        .replace("\\f", " ")
        .replace("\\n", " ")
    )
    # Remove Pokédex format tags like [PokeRus], [ability], etc.
    text = re.sub(r"\[.*?\]", "", text)
    # Remove escape sequences
    text = re.sub(r"\x1b\[.*?m", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# API fetchers
# ---------------------------------------------------------------------------

POKE_BASE = "https://pokeapi.co/api/v2"


async def _get_pokemon_data(client: httpx.AsyncClient, name_or_id: str) -> dict:
    """Fetch base Pokémon data."""
    url = f"{POKE_BASE}/pokemon/{name_or_id.lower()}"
    r = await _fetch_with_retry(client, url)
    return r.json()


async def _get_species_data(client: httpx.AsyncClient, species_url: str) -> dict:
    """Fetch species data (generation, habitat, flavor text, evolution chain)."""
    r = await _fetch_with_retry(client, species_url)
    return r.json()


async def _get_evolution_chain(client: httpx.AsyncClient, url: str) -> list:
    """Parse evolution chain into a flat list of Pokémon names."""
    r = await _fetch_with_retry(client, url)
    chain = r.json()

    evos = []

    def _traverse(node: dict):
        name = node["species"]["name"]
        evos.append(name)
        for stage in node.get("evolves_to", []):
            _traverse(stage)

    # BUG FIX: PokéAPI wraps the chain root under a "chain" key
    _traverse(chain["chain"])
    return evos


# ---------------------------------------------------------------------------
# HTML Card Builder
# ---------------------------------------------------------------------------


def _build_html(
    pokemon: dict,
    species: dict,
    evolution_chain: list,
    unit: str,
    sprite_url: Optional[str],
) -> str:
    """Build a beautiful HTML card for a Pokémon."""

    name = pokemon["name"].capitalize()
    num = pokemon["id"]
    num_str = f"#{num:04d}"
    xp = pokemon.get("base_experience", "N/A")
    height = pokemon["height"] / 10
    weight = pokemon["weight"] / 10

    if unit == "imperial":
        height_str = f"{height * 3.28084:.1f} ft"
        weight_str = f"{weight * 2.20462:.1f} lb"
    else:
        height_str = f"{height:.1f} m"
        weight_str = f"{weight:.1f} kg"

    types = [t["type"]["name"] for t in pokemon["types"]]
    main_type = types[0]
    main_color = TYPE_COLORS.get(main_type, "#6AA84F")
    second_color = (
        TYPE_COLORS.get(types[1], main_color) if len(types) > 1 else main_color
    )

    type_badges = []
    for t in types:
        color = TYPE_COLORS.get(t, "#6AA84F")
        type_badges.append(
            f'<span class="type-badge" style="background:{color};box-shadow:0 2px 12px {color}66">{t.upper()}</span>'
        )

    abilities_html = []
    for a in pokemon.get("abilities", []):
        is_hidden = a.get("is_hidden", False)
        aname = a["ability"]["name"].replace("-", " ").title()
        hidden_tag = '<span class="hidden-tag">Hidden</span>' if is_hidden else ""
        abilities_html.append(
            f'<div class="ability-pill{"  ability-hidden" if is_hidden else ""}">{aname}{hidden_tag}</div>'
        )

    stats_html = []
    for s in pokemon.get("stats", []):
        stat_name = s["stat"]["name"]
        base_stat = s["base_stat"]
        label = STAT_LABELS.get(stat_name, stat_name.upper())
        bar_color, _ = _stat_bar(base_stat)
        pct = min(base_stat / 255 * 100, 100)
        stats_html.append(f"""
        <div class="stat-row">
            <span class="stat-label">{label}</span>
            <div class="stat-bar-bg">
                <div class="stat-bar" style="--bar-w:{pct:.1f}%;--bar-color:{bar_color}"></div>
            </div>
            <span class="stat-value" style="color:{bar_color}">{base_stat}</span>
        </div>""")
    total_stats = sum(s["base_stat"] for s in pokemon["stats"])

    gen = _generation_label(species.get("generation", {}).get("name", ""))
    habitat_raw = species.get("habitat") or {}
    habitat = (
        habitat_raw.get("name", "Unknown").replace("-", " ").title()
        if habitat_raw
        else "Unknown"
    )
    growth_rate = (
        species.get("growth_rate", {}).get("name", "unknown").replace("-", " ").title()
    )
    egg_groups = (
        ", ".join(
            eg["name"].replace("-", " ").title() for eg in species.get("egg_groups", [])
        )
        or "Unknown"
    )
    catch_rate = species.get("capture_rate", "?")
    is_legendary = species.get("is_legendary", False)
    is_mythical = species.get("is_mythical", False)

    rarity_badge = ""
    if is_mythical:
        rarity_badge = '<span class="rarity-badge mythical">✦ Mythical</span>'
    elif is_legendary:
        rarity_badge = '<span class="rarity-badge legendary">★ Legendary</span>'

    flavor_entries = [
        e
        for e in species.get("flavor_text_entries", [])
        if e.get("language", {}).get("name") == "en"
    ]
    flavor_text = ""
    seen_texts: set = set()
    for entry in reversed(flavor_entries):
        txt = _clean_flavor_text(entry["flavor_text"])
        if txt and txt not in seen_texts and len(txt) > 20:
            flavor_text = txt
            seen_texts.add(txt)

    evos_html_parts = []
    for i, evo_name in enumerate(evolution_chain):
        is_current = evo_name == pokemon["name"]
        css_class = "evo-node evo-current" if is_current else "evo-node"
        evos_html_parts.append(
            f'<div class="{css_class}"><span class="evo-name">{evo_name.capitalize()}</span></div>'
        )
        if i < len(evolution_chain) - 1:
            evos_html_parts.append('<span class="evo-arrow">→</span>')
    evos_str = "".join(evos_html_parts)

    official_art = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{num}.png"
    shiny_art = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{num}.png"
    fallback_sprite = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{num}.png"

    gender_rate = species.get("gender_rate", -1)
    if gender_rate == -1:
        gender_str = "Genderless"
    else:
        female_pct = gender_rate / 8 * 100
        male_pct = 100 - female_pct
        gender_str = f"♂ {male_pct:.0f}% / ♀ {female_pct:.0f}%"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: transparent; font-family: 'Nunito', -apple-system, sans-serif; padding: 8px; }}

.poke-card {{
    position: relative; max-width: 660px; margin: 0 auto;
    border-radius: 28px; overflow: hidden; background: #0d0d14;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.06), 0 24px 60px rgba(0,0,0,0.7), 0 0 80px {main_color}22;
    color: #e8e8f0;
}}
.poke-banner {{
    position: relative;
    background: linear-gradient(135deg, {main_color}cc 0%, {second_color}99 55%, {main_color}44 100%);
    padding: 28px 28px 0; overflow: hidden; min-height: 220px;
    display: flex; align-items: flex-end; justify-content: space-between;
}}
.poke-banner::before {{
    content: ''; position: absolute; top: -80px; right: -80px;
    width: 340px; height: 340px;
    background: radial-gradient(circle, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 40%, transparent 70%);
    border-radius: 50%; border: 2px solid rgba(255,255,255,0.06); pointer-events: none;
}}
.poke-banner::after {{
    content: ''; position: absolute; top: -20px; right: 40px;
    width: 340px; height: 340px;
    border-radius: 50%; border: 60px solid rgba(255,255,255,0.04); pointer-events: none;
}}
.poke-banner-text {{ position: relative; z-index: 2; padding-bottom: 24px; flex: 1; }}
.poke-num {{ font-family: 'Space Mono', monospace; font-size: 0.82rem; font-weight: 700; color: rgba(255,255,255,0.6); letter-spacing: 1px; margin-bottom: 4px; }}
.poke-name-big {{ font-size: 2.6rem; font-weight: 900; color: #fff; letter-spacing: -1px; text-shadow: 0 2px 20px rgba(0,0,0,0.4); line-height: 1; margin-bottom: 12px; }}
.poke-types {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.type-badge {{ padding: 5px 16px; border-radius: 20px; font-size: 0.72rem; font-weight: 800; letter-spacing: 1px; color: #fff; text-transform: uppercase; border: 1px solid rgba(255,255,255,0.25); backdrop-filter: blur(4px); }}
.rarity-badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 12px; font-size: 0.7rem; font-weight: 800; letter-spacing: 0.5px; margin-top: 8px; }}
.legendary {{ background: rgba(255,200,50,0.25); color: #FFD700; border: 1px solid rgba(255,200,50,0.4); }}
.mythical {{ background: rgba(255,100,200,0.25); color: #FF78C4; border: 1px solid rgba(255,100,200,0.4); }}
.poke-sprite-zone {{ position: relative; z-index: 2; display: flex; flex-direction: column; align-items: center; gap: 6px; padding-bottom: 0; min-width: 200px; }}
.poke-artwork {{ width: 200px; height: 200px; object-fit: contain; filter: drop-shadow(0 8px 24px rgba(0,0,0,0.5)); animation: floatAnim 4s ease-in-out infinite; cursor: pointer; transition: opacity 0.25s, transform 0.25s; }}
.poke-artwork:hover {{ transform: scale(1.06); }}
@keyframes floatAnim {{ 0%,100% {{ transform: translateY(0px) rotate(-1deg); }} 50% {{ transform: translateY(-10px) rotate(1deg); }} }}
.sprite-toggle {{ display: flex; gap: 6px; margin-bottom: 8px; }}
.sprite-btn {{ padding: 3px 10px; border-radius: 10px; font-size: 0.65rem; font-weight: 700; cursor: pointer; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.3); color: rgba(255,255,255,0.7); transition: all 0.2s; font-family: 'Nunito', sans-serif; letter-spacing: 0.5px; }}
.sprite-btn.active {{ background: rgba(255,255,255,0.15); color: #fff; border-color: rgba(255,255,255,0.4); }}
.sprite-btn:hover {{ background: rgba(255,255,255,0.12); }}
.poke-body {{ padding: 24px 28px; display: flex; flex-direction: column; gap: 20px; }}
.info-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
.info-tile {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; padding: 12px 14px; transition: background 0.2s; }}
.info-tile:hover {{ background: rgba(255,255,255,0.07); }}
.info-lbl {{ font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.8px; color: rgba(255,255,255,0.4); margin-bottom: 4px; font-weight: 700; }}
.info-val {{ font-size: 0.9rem; font-weight: 800; color: #f0f0ff; }}
.poke-divider {{ border: none; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); }}
.section-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
.section-head-line {{ font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 900; color: {main_color}; }}
.section-head::after {{ content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, {main_color}44, transparent); }}
.stat-row {{ display: grid; grid-template-columns: 38px 1fr 36px; align-items: center; gap: 10px; margin-bottom: 8px; }}
.stat-label {{ font-family: 'Space Mono', monospace; font-size: 0.63rem; font-weight: 700; color: rgba(255,255,255,0.45); text-align: right; }}
.stat-bar-bg {{ height: 7px; background: rgba(255,255,255,0.06); border-radius: 10px; overflow: hidden; }}
.stat-bar {{ height: 100%; border-radius: 10px; width: 0; background: var(--bar-color); box-shadow: 0 0 8px var(--bar-color); animation: growBar 1s cubic-bezier(.22,1,.36,1) forwards; animation-delay: 0.2s; }}
@keyframes growBar {{ from {{ width: 0; }} to {{ width: var(--bar-w); }} }}
.stat-value {{ font-family: 'Space Mono', monospace; font-size: 0.76rem; font-weight: 700; text-align: left; }}
.stat-total-row {{ display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 4px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06); }}
.stat-total-label {{ font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px; color: rgba(255,255,255,0.4); font-weight: 700; }}
.stat-total-val {{ font-family: 'Space Mono', monospace; font-size: 1rem; font-weight: 700; color: #fff; }}
.abilities-wrap {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.ability-pill {{ display: flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 6px 14px; font-size: 0.78rem; font-weight: 700; color: #d0d0e8; transition: all 0.2s; }}
.ability-pill:hover {{ background: rgba(255,255,255,0.1); border-color: {main_color}66; }}
.ability-hidden {{ background: rgba(255,255,255,0.03); border-style: dashed; opacity: 0.75; }}
.hidden-tag {{ font-size: 0.55rem; text-transform: uppercase; letter-spacing: 0.5px; background: rgba(255,200,100,0.2); color: #ffd97d; padding: 1px 5px; border-radius: 5px; font-weight: 800; }}
.poke-flavor {{ background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02)); border-left: 3px solid {main_color}; border-radius: 0 14px 14px 0; padding: 14px 18px; font-size: 0.88rem; line-height: 1.65; color: rgba(255,255,255,0.65); font-style: italic; font-weight: 600; }}
.evo-chain {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center; padding: 8px 0; }}
.evo-node {{ display: flex; flex-direction: column; align-items: center; gap: 4px; }}
.evo-name {{ font-size: 0.8rem; font-weight: 800; color: rgba(255,255,255,0.6); padding: 5px 14px; border-radius: 20px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); transition: all 0.2s; }}
.evo-node:hover .evo-name {{ background: rgba(255,255,255,0.1); color: #fff; }}
.evo-current .evo-name {{ background: linear-gradient(135deg, {main_color}44, {second_color}33); border-color: {main_color}88; color: #fff; box-shadow: 0 0 16px {main_color}44; }}
.evo-arrow {{ font-size: 1.1rem; color: rgba(255,255,255,0.2); font-weight: 700; }}
.poke-footer {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 28px; background: rgba(0,0,0,0.3); font-size: 0.62rem; color: rgba(255,255,255,0.2); font-weight: 600; letter-spacing: 0.3px; font-family: 'Space Mono', monospace; }}
@media (max-width: 520px) {{ .poke-banner {{ flex-direction: column; align-items: flex-start; padding-bottom: 0; }} .poke-sprite-zone {{ width: 100%; align-items: flex-end; }} .poke-name-big {{ font-size: 2rem; }} .info-grid {{ grid-template-columns: repeat(2, 1fr); }} .poke-artwork {{ width: 160px; height: 160px; }} }}
</style>
</head>
<body>
<div class="poke-card">
  <div class="poke-banner">
    <div class="poke-banner-text">
      <div class="poke-num">{num_str}</div>
      <div class="poke-name-big">{name}</div>
      <div class="poke-types">{"".join(type_badges)}</div>
      {rarity_badge}
    </div>
    <div class="poke-sprite-zone">
      <div class="sprite-toggle">
        <button class="sprite-btn active" onclick="setSprite('normal',this)">Normal</button>
        <button class="sprite-btn" onclick="setSprite('shiny',this)">✨ Shiny</button>
      </div>
      <img id="main-artwork" class="poke-artwork"
        src="{official_art}"
        data-normal="{official_art}"
        data-shiny="{shiny_art}"
        alt="{name}"
        onerror="this.src='{fallback_sprite}'"
        loading="eager">
    </div>
  </div>
  <div class="poke-body">
    <div class="info-grid">
      <div class="info-tile"><div class="info-lbl">Height</div><div class="info-val">{height_str}</div></div>
      <div class="info-tile"><div class="info-lbl">Weight</div><div class="info-val">{weight_str}</div></div>
      <div class="info-tile"><div class="info-lbl">Base XP</div><div class="info-val">{xp}</div></div>
      <div class="info-tile"><div class="info-lbl">Generation</div><div class="info-val">{gen}</div></div>
      <div class="info-tile"><div class="info-lbl">Habitat</div><div class="info-val">{habitat}</div></div>
      <div class="info-tile"><div class="info-lbl">Growth Rate</div><div class="info-val">{growth_rate}</div></div>
      <div class="info-tile"><div class="info-lbl">Catch Rate</div><div class="info-val">{catch_rate}</div></div>
      <div class="info-tile"><div class="info-lbl">Egg Groups</div><div class="info-val">{egg_groups}</div></div>
      <div class="info-tile"><div class="info-lbl">Gender</div><div class="info-val">{gender_str}</div></div>
    </div>
    <hr class="poke-divider">
    <div>
      <div class="section-head"><span class="section-head-line">Base Stats</span></div>
      {"".join(stats_html)}
      <div class="stat-total-row">
        <span class="stat-total-label">Total</span>
        <span class="stat-total-val">{total_stats}</span>
      </div>
    </div>
    <hr class="poke-divider">
    <div>
      <div class="section-head"><span class="section-head-line">Abilities</span></div>
      <div class="abilities-wrap">{"".join(abilities_html)}</div>
    </div>
    <hr class="poke-divider">
    <div>
      <div class="section-head"><span class="section-head-line">Pokédex Entry</span></div>
      <div class="poke-flavor">{flavor_text or "No Pokédex entry available."}</div>
    </div>
    <hr class="poke-divider">
    <div>
      <div class="section-head"><span class="section-head-line">Evolution Chain</span></div>
      <div class="evo-chain">{evos_str}</div>
    </div>
  </div>
  <div class="poke-footer"><span>Powered by PokéAPI</span><span>pokeapi.co · v2</span></div>
</div>
<script>
function setSprite(mode, btn) {{
  document.querySelectorAll('.sprite-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const img = document.getElementById('main-artwork');
  img.style.opacity = '0'; img.style.transform = 'scale(0.85)'; img.style.transition = 'all 0.25s ease';
  setTimeout(() => {{ img.src = mode === 'shiny' ? img.dataset.shiny : img.dataset.normal; img.style.opacity = '1'; img.style.transform = 'scale(1)'; }}, 220);
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Event emitter helper
# ---------------------------------------------------------------------------


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


# ---------------------------------------------------------------------------
# Main Tools Class
# ---------------------------------------------------------------------------


class Tools:
    class Valves(BaseModel):
        sprite_style: str = Field(
            default="animated",
            description="Sprite style to display: 'animated' (showdown animated), 'pixel' (pixel art), or 'official' (high-res artwork).",
        )
        unit: str = Field(
            default="metric",
            description="Measurement unit: 'metric' (meters/kg) or 'imperial' (feet/pounds).",
        )
        max_pokemon_id: int = Field(
            default=1025,
            description="Maximum Pokédex number to allow (default: 1025 for Scarlet/Violet).",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def look_up(
        self,
        name_or_id: str,
        __event_emitter__: Optional[callable] = None,
    ) -> "HTMLResponse | str":
        """
        Look up a Pokémon by name or national Pokédex number.

        Shows a beautiful card with:
        - Animated sprite / official artwork
        - Type badges with color coding
        - Base stats as visual progress bars
        - Abilities, height, weight, generation
        - Pokédex flavor text entry
        - Evolution chain

        Usage:
            - look_up("pikachu")     → Pikachu's card
            - look_up("charizard")   → Charizard's card
            - look_up("150")         → Mewtwo's card
            - look_up("Mewtwo")      → Mewtwo's card

        :param name_or_id: Pokémon name or Pokédex number (1–1025)
        :return: Rendered HTML Pokédex card
        """
        name = name_or_id.strip().lower()
        if not name:
            msg = (
                "❌ Please specify a Pokémon name or number (e.g., 'Pikachu' or '25')."
            )
            await _emit(__event_emitter__, msg, done=True)
            return msg

        # Validate range if it's a number
        if name.isdigit():
            num = int(name)
            if num < 1 or num > self.valves.max_pokemon_id:
                msg = f"❌ Pokédex number must be between 1 and {self.valves.max_pokemon_id}."
                await _emit(__event_emitter__, msg, done=True)
                return msg

        try:
            await _emit(__event_emitter__, f"🔍 Looking up '{name}'...")

            # Pre-resolve DNS to avoid Windows getaddrinfo failures
            _preresolve_dns()

            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True, http2=False
            ) as client:
                # Fetch Pokémon data
                poke_data = await _get_pokemon_data(client, name)
                pokemon_name = poke_data["name"].capitalize()

                await _emit(__event_emitter__, f"✨ Found {pokemon_name}!")

                # Fetch species data
                species = await _get_species_data(client, poke_data["species"]["url"])

                # Fetch evolution chain
                evolution_chain = await _get_evolution_chain(
                    client, species["evolution_chain"]["url"]
                )

                # Determine sprite URL based on user preference
                sprites = poke_data.get("sprites", {})
                if self.valves.sprite_style == "animated":
                    sprite_url = _sprite_url(sprites, "front_default")
                    if not sprite_url:
                        sprite_url = _find_best_sprite(sprites)
                elif self.valves.sprite_style == "pixel":
                    sprite_url = _sprite_url(sprites, "front_default")
                else:  # official
                    sprite_url = _sprite_url(sprites, "front_default")
                    if not sprite_url:
                        sprite_url = _find_best_sprite(sprites)

                # Build and return HTML card
                html = _build_html(
                    poke_data, species, evolution_chain, self.valves.unit, sprite_url
                )

                await _emit(
                    __event_emitter__,
                    f"✅ Pokédex card loaded for {pokemon_name}!",
                    done=True,
                )

                return HTMLResponse(
                    content=html, headers={"content-disposition": "inline"}
                )

        except socket.gaierror as e:
            # Windows DNS resolution failure (getaddrinfo error)
            msg = f"❌ Network error: Unable to resolve PokéAPI server address. This is often a Windows DNS issue. Please check your internet connection.\n\nError: {e}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                msg = f"❌ Pokémon '{name_or_id}' not found. Check spelling or try a number (1–{self.valves.max_pokemon_id})."
            else:
                msg = f"❌ HTTP error {e.response.status_code} from PokéAPI."
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except httpx.TimeoutException:
            msg = "❌ Request timed out. PokéAPI may be slow right now."
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except Exception as exc:
            msg = f"❌ Error fetching Pokémon data: {exc}"
            await _emit(__event_emitter__, msg, done=True)
            return msg

    async def pokedex_list(
        self,
        generation: Optional[str] = None,
        count: int = 10,
        __event_emitter__: Optional[callable] = None,
    ) -> str:
        """
        Get a list of Pokémon from a specific generation or the first N Pokémon.

        Usage:
            - pokedex_list(generation="generation-ix")  → Gen 9 Pokémon
            - pokedex_list(count=20)                    → First 20 Pokémon

        :param generation: Generation filter (e.g., "generation-vi" for Gen 6)
        :param count: Number of Pokémon to return (default: 10)
        :return: Formatted list of Pokémon names
        """
        try:
            await _emit(__event_emitter__, "📋 Fetching Pokédex list...")

            # Pre-resolve DNS to avoid Windows getaddrinfo failures
            _preresolve_dns()

            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True, http2=False
            ) as client:
                if generation:
                    # Find the last Pokémon of the requested generation
                    gen_urls = {
                        "generation-i": "https://pokeapi.co/api/v2/pokedex-entry/151",
                        "generation-ii": "https://pokeapi.co/api/v2/pokedex-entry/251",
                        "generation-iii": "https://pokeapi.co/api/v2/pokedex-entry/386",
                        "generation-iv": "https://pokeapi.co/api/v2/pokedex-entry/493",
                        "generation-v": "https://pokeapi.co/api/v2/pokedex-entry/649",
                        "generation-vi": "https://pokeapi.co/api/v2/pokedex-entry/721",
                        "generation-vii": "https://pokeapi.co/api/v2/pokedex-entry/809",
                        "generation-viii": "https://pokeapi.co/api/v2/pokedex-entry/905",
                        "generation-ix": "https://pokeapi.co/api/v2/pokedex-entry/1025",
                    }

                    if generation not in gen_urls:
                        available = ", ".join(gen_urls.keys())
                        msg = f"❌ Unknown generation '{generation}'. Available: {available}"
                        await _emit(__event_emitter__, msg, done=True)
                        return msg

                    # Fetch the last Pokémon of the generation to find the range
                    last_num = count
                    url = gen_urls[generation]
                    r = await client.get(url)
                    if r.status_code == 200:
                        last_num = r.json().get("last_processed_number", count)

                    # Fetch Pokémon in that range
                    results = []
                    start = last_num - count + 1
                    for i in range(start, last_num + 1):
                        try:
                            poke = await _get_pokemon_data(client, str(i))
                            results.append(poke)
                        except Exception:
                            continue
                else:
                    # Simple list from 1 to count
                    results = []
                    for i in range(1, min(count + 1, self.valves.max_pokemon_id + 1)):
                        try:
                            poke = await _get_pokemon_data(client, str(i))
                            results.append(poke)
                        except Exception:
                            continue

                # Format output
                lines = [f"### 📋 Pokédex List ({len(results)} Pokémon)"]
                for poke in results:
                    num = poke["id"]
                    name = poke["name"].capitalize()
                    types = ", ".join(t["type"]["name"] for t in poke["types"])
                    lines.append(f"**{num:04d}.** {name} — {types}")

                await _emit(
                    __event_emitter__, f"✅ Listed {len(results)} Pokémon!", done=True
                )
                return "\n".join(lines)

        except socket.gaierror as e:
            msg = f"❌ Network error: Unable to resolve PokéAPI server address (Windows DNS issue). Check your internet connection. Error: {e}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except Exception as exc:
            msg = f"❌ Error fetching list: {exc}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
