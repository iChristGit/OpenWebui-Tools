"""
title: Pokédex Pro
author: ichrist
author_url: https://github.com/open-webui/open-webui
version: 2.0.0
description: >
  An enhanced, AI-powered Pokédex with rich data, stunning visuals, and LLM-generated
  narrative descriptions — powered by the PokéAPI and your local model.

  New in v2:
    - LLM-generated trainer narrative (battle tips, lore, strategy notes)
    - Type effectiveness chart (attack & defense multipliers)
    - Top learnable moves with power/accuracy/type breakdown
    - Encounter locations
    - Held items in the wild
    - Happiness & friendship data
    - Tabbed UI (Overview / Moves / Encounters / Lore)
    - Open-WebUI citation event for PokéAPI source
    - Open-WebUI notification event on success
    - Animated particle background in banner
    - Poké-Ball radar chart for stat shape

  Usage:
    - "Show me Gengar"         → look_up("gengar")
    - "Pokédex #384"           → look_up("384")
    - "Compare Pikachu"        → look_up("pikachu")
    - "List Gen 4 starters"    → pokedex_list(generation="generation-iv", count=8)

license: MIT
requirements: httpx
"""

import re
import json
import asyncio
import httpx
from datetime import datetime
from typing import Optional, Callable, Awaitable
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch(client: httpx.AsyncClient, url: str) -> httpx.Response:
    response = await client.get(url)
    response.raise_for_status()
    return response


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


async def _notify(emitter, content: str, level: str = "success"):
    if emitter:
        await emitter(
            {"type": "notification", "data": {"type": level, "content": content}}
        )


async def _cite(emitter, title: str, url: str, content: str):
    """Emit a PokéAPI citation chip in Open-WebUI."""
    if emitter:
        await emitter(
            {
                "type": "citation",
                "data": {
                    "document": [content],
                    "metadata": [
                        {
                            "date_accessed": datetime.now().isoformat(),
                            "source": title,
                            "url": url,
                        }
                    ],
                    "source": {"name": title, "url": url},
                },
            }
        )


# ---------------------------------------------------------------------------
# Type → color / effectiveness data
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

# Full type chart [attacker][defender] = multiplier
TYPE_CHART: dict[str, dict[str, float]] = {
    "normal": {"rock": 0.5, "ghost": 0, "steel": 0.5},
    "fire": {
        "fire": 0.5,
        "water": 0.5,
        "grass": 2,
        "ice": 2,
        "bug": 2,
        "rock": 0.5,
        "dragon": 0.5,
        "steel": 2,
    },
    "water": {
        "fire": 2,
        "water": 0.5,
        "grass": 0.5,
        "ground": 2,
        "rock": 2,
        "dragon": 0.5,
    },
    "electric": {
        "water": 2,
        "electric": 0.5,
        "grass": 0.5,
        "ground": 0,
        "flying": 2,
        "dragon": 0.5,
    },
    "grass": {
        "fire": 0.5,
        "water": 2,
        "grass": 0.5,
        "poison": 0.5,
        "ground": 2,
        "flying": 0.5,
        "bug": 0.5,
        "rock": 2,
        "dragon": 0.5,
        "steel": 0.5,
    },
    "ice": {
        "water": 0.5,
        "grass": 2,
        "ice": 0.5,
        "ground": 2,
        "flying": 2,
        "dragon": 2,
        "steel": 0.5,
    },
    "fighting": {
        "normal": 2,
        "ice": 2,
        "poison": 0.5,
        "flying": 0.5,
        "psychic": 0.5,
        "bug": 0.5,
        "rock": 2,
        "ghost": 0,
        "dark": 2,
        "steel": 2,
        "fairy": 0.5,
    },
    "poison": {
        "grass": 2,
        "poison": 0.5,
        "ground": 0.5,
        "rock": 0.5,
        "ghost": 0.5,
        "steel": 0,
        "fairy": 2,
    },
    "ground": {
        "fire": 2,
        "electric": 2,
        "grass": 0.5,
        "poison": 2,
        "flying": 0,
        "bug": 0.5,
        "rock": 2,
        "steel": 2,
    },
    "flying": {
        "electric": 0.5,
        "grass": 2,
        "fighting": 2,
        "bug": 2,
        "rock": 0.5,
        "steel": 0.5,
    },
    "psychic": {"fighting": 2, "poison": 2, "psychic": 0.5, "dark": 0, "steel": 0.5},
    "bug": {
        "fire": 0.5,
        "grass": 2,
        "fighting": 0.5,
        "flying": 0.5,
        "psychic": 2,
        "ghost": 0.5,
        "dark": 2,
        "steel": 0.5,
        "fairy": 0.5,
    },
    "rock": {
        "fire": 2,
        "ice": 2,
        "fighting": 0.5,
        "ground": 0.5,
        "flying": 2,
        "bug": 2,
        "steel": 0.5,
    },
    "ghost": {"normal": 0, "psychic": 2, "ghost": 2, "dark": 0.5},
    "dragon": {"steel": 0.5, "fairy": 0},
    "dark": {"fighting": 0.5, "psychic": 2, "ghost": 2, "dark": 0.5, "fairy": 0.5},
    "steel": {
        "fire": 0.5,
        "water": 0.5,
        "electric": 0.5,
        "ice": 2,
        "rock": 2,
        "steel": 0.5,
        "fairy": 2,
    },
    "fairy": {
        "fire": 0.5,
        "fighting": 2,
        "poison": 0.5,
        "dragon": 2,
        "dark": 2,
        "steel": 0.5,
    },
}

STAT_LABELS: dict[str, str] = {
    "hp": "HP",
    "attack": "ATK",
    "defense": "DEF",
    "special-attack": "SpA",
    "special-defense": "SpD",
    "speed": "SPD",
}

MOVE_CATEGORY_ICONS = {"physical": "⚔️", "special": "✨", "status": "🔄"}

DAMAGE_CLASS_COLORS = {"physical": "#ef4444", "special": "#818cf8", "status": "#94a3b8"}

GEN_MAP = {
    "generation-i": "Gen I · Kanto",
    "generation-ii": "Gen II · Johto",
    "generation-iii": "Gen III · Hoenn",
    "generation-iv": "Gen IV · Sinnoh",
    "generation-v": "Gen V · Unova",
    "generation-vi": "Gen VI · Kalos",
    "generation-vii": "Gen VII · Alola",
    "generation-viii": "Gen VIII · Galar",
    "generation-ix": "Gen IX · Paldea",
}

POKE_BASE = "https://pokeapi.co/api/v2"


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    text = (
        text.replace("\f", " ")
        .replace("\n", " ")
        .replace("\\f", " ")
        .replace("\\n", " ")
    )
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\x1b\[.*?m", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _generation_label(gen: str) -> str:
    return GEN_MAP.get(gen, gen.replace("-", " ").title())


def _stat_color(value: int) -> str:
    if value <= 50:
        return "#ef4444"
    if value <= 80:
        return "#f59e0b"
    if value <= 100:
        return "#eab308"
    if value <= 130:
        return "#22c55e"
    return "#10b981"


def _find_best_sprite(sprites: dict) -> Optional[str]:
    candidates = [
        ("other", "official-artwork", "front_default"),
        ("other", "showdown", "front_default"),
        ("other", "home", "front_default"),
        ("front_default", None, None),
    ]
    for section, k1, k2 in candidates:
        if k2:
            val = sprites.get("other", {}).get(section, {}).get(k2)
            if val:
                return val
        elif section in sprites and sprites[section]:
            return sprites[section]
    return None


def _compute_defense_chart(types: list[str]) -> dict[str, float]:
    """Compute combined defense multipliers for a given type combo."""
    result = {}
    all_types = list(TYPE_CHART.keys())
    for attacker in all_types:
        mult = 1.0
        for defender in types:
            mult *= TYPE_CHART.get(attacker, {}).get(defender, 1.0)
        if mult != 1.0:
            result[attacker] = mult
    return result


# ---------------------------------------------------------------------------
# API fetchers
# ---------------------------------------------------------------------------


async def _get_pokemon(client: httpx.AsyncClient, name_or_id: str) -> dict:
    r = await _fetch(client, f"{POKE_BASE}/pokemon/{name_or_id.lower()}")
    return r.json()


async def _get_species(client: httpx.AsyncClient, url: str) -> dict:
    r = await _fetch(client, url)
    return r.json()


async def _get_evolution_chain(client: httpx.AsyncClient, url: str) -> list[dict]:
    """Parse evolution chain into list of {name, min_level, trigger}."""
    r = await _fetch(client, url)
    chain = r.json()
    evos = []

    def _traverse(node: dict):
        name = node["species"]["name"]
        for next_node in node.get("evolves_to", []):
            detail = (
                next_node.get("evolution_details", [{}])[0]
                if next_node.get("evolution_details")
                else {}
            )
            trigger = detail.get("trigger", {}).get("name", "")
            min_lvl = detail.get("min_level")
            item = detail.get("item", {}).get("name", "") if detail.get("item") else ""
            evos.append(
                {
                    "from": name,
                    "to": next_node["species"]["name"],
                    "trigger": trigger,
                    "min_level": min_lvl,
                    "item": item,
                }
            )
            _traverse(next_node)

    _traverse(chain["chain"])
    if not evos:
        evos = [
            {
                "from": chain["chain"]["species"]["name"],
                "to": None,
                "trigger": "",
                "min_level": None,
                "item": "",
            }
        ]
    return evos


async def _get_move_details(client: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await _fetch(client, url)
        d = r.json()
        return {
            "power": d.get("power"),
            "accuracy": d.get("accuracy"),
            "pp": d.get("pp"),
            "damage_class": d.get("damage_class", {}).get("name", ""),
            "type": d.get("type", {}).get("name", ""),
        }
    except Exception:
        return {}


async def _get_encounters(client: httpx.AsyncClient, pokemon_id: int) -> list[str]:
    try:
        r = await client.get(f"{POKE_BASE}/pokemon/{pokemon_id}/encounters", timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        locations = []
        for enc in data[:8]:
            loc = enc.get("location_area", {}).get("name", "").replace("-", " ").title()
            if loc:
                locations.append(loc)
        return locations
    except Exception:
        return []


async def _get_ability_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await _fetch(client, url)
        d = r.json()
        for entry in d.get("effect_entries", []):
            if entry.get("language", {}).get("name") == "en":
                return entry.get("short_effect", "")
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# LLM narrative generator
# ---------------------------------------------------------------------------


async def _generate_llm_narrative(
    pokemon_name: str,
    types: list[str],
    total_stats: int,
    abilities: list[str],
    flavor_text: str,
    is_legendary: bool,
    is_mythical: bool,
    gen: str,
    __user__: Optional[dict] = None,
) -> str:
    """Call the local Open-WebUI model to generate a trainer-style narrative."""
    rarity = "Mythical" if is_mythical else ("Legendary" if is_legendary else "")
    rarity_note = f" It is a {rarity} Pokémon." if rarity else ""
    type_str = " / ".join(t.capitalize() for t in types)
    abilities_str = ", ".join(abilities)

    prompt = f"""You are a seasoned Pokémon professor writing a concise, vivid trainer's analysis.
Write 3–4 sentences about {pokemon_name} ({type_str} type, {gen}).{rarity_note}
Base stat total: {total_stats}. Abilities: {abilities_str}.
Pokédex hint: "{flavor_text[:180]}"

Cover: its battlefield role, what makes it unique, a key strength and weakness, and one memorable quirk or lore detail.
Be specific, enthusiastic, and helpful to a trainer. DO NOT repeat the Pokédex text verbatim."""

    try:
        import urllib.request

        payload = json.dumps(
            {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 220,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
            content = data.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block["text"].strip()
    except Exception:
        pass

    # Fallback: generate a decent static narrative
    role = (
        "balanced"
        if total_stats < 450
        else ("powerhouse" if total_stats >= 540 else "capable")
    )
    return (
        f"{pokemon_name} is a {type_str}-type {rarity.lower() + ' ' if rarity else ''}Pokémon from {gen}. "
        f"With a base stat total of {total_stats}, it is a {role} contender in battle. "
        f"Its {'abilities' if len(abilities) > 1 else 'ability'} — {abilities_str} — shape its playstyle significantly. "
        f"Trainers who appreciate its type combination will find it a rewarding partner."
    )


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------


def _build_html(
    pokemon: dict,
    species: dict,
    evo_chain: list,
    unit: str,
    sprite_url: Optional[str],
    moves_data: list[dict],
    encounter_locations: list[str],
    ability_descriptions: dict[str, str],
    llm_narrative: str,
) -> str:

    name = pokemon["name"].capitalize()
    num = pokemon["id"]
    num_str = f"#{num:04d}"
    xp = pokemon.get("base_experience", "—")
    height_m = pokemon["height"] / 10
    weight_kg = pokemon["weight"] / 10
    happiness = species.get("base_happiness", "—")
    capture_rate = species.get("capture_rate", "—")

    if unit == "imperial":
        height_str = f"{height_m * 3.28084:.1f} ft"
        weight_str = f"{weight_kg * 2.20462:.1f} lb"
    else:
        height_str = f"{height_m:.1f} m"
        weight_str = f"{weight_kg:.1f} kg"

    types = [t["type"]["name"] for t in pokemon["types"]]
    main_type = types[0]
    main_color = TYPE_COLORS.get(main_type, "#6AA84F")
    second_color = (
        TYPE_COLORS.get(types[1], main_color) if len(types) > 1 else main_color
    )

    def _type_badge(t: str, size="normal") -> str:
        color = TYPE_COLORS.get(t, "#6AA84F")
        fs = "0.68rem" if size == "small" else "0.72rem"
        pad = "3px 10px" if size == "small" else "5px 16px"
        return f'<span class="type-badge" style="background:{color};box-shadow:0 2px 12px {color}55;font-size:{fs};padding:{pad}">{t.upper()}</span>'

    type_badges_html = "".join(_type_badge(t) for t in types)

    # Abilities
    abilities_html = []
    for a in pokemon.get("abilities", []):
        is_hidden = a.get("is_hidden", False)
        aname = a["ability"]["name"].replace("-", " ").title()
        desc = ability_descriptions.get(a["ability"]["name"], "")
        hidden_tag = '<span class="hidden-tag">Hidden</span>' if is_hidden else ""
        tooltip = f'title="{desc}"' if desc else ""
        abilities_html.append(
            f'<div class="ability-pill{"  ability-hidden" if is_hidden else ""}" {tooltip}>'
            f"{aname}{hidden_tag}</div>"
        )

    # Stats
    stats_html = []
    stat_values = []
    for s in pokemon.get("stats", []):
        stat_name = s["stat"]["name"]
        base_stat = s["base_stat"]
        stat_values.append(base_stat)
        label = STAT_LABELS.get(stat_name, stat_name.upper())
        bar_color = _stat_color(base_stat)
        pct = min(base_stat / 255 * 100, 100)
        stats_html.append(f"""
        <div class="stat-row">
            <span class="stat-label">{label}</span>
            <div class="stat-bar-bg">
                <div class="stat-bar" style="--bar-w:{pct:.1f}%;--bar-color:{bar_color}"></div>
            </div>
            <span class="stat-value" style="color:{bar_color}">{base_stat}</span>
        </div>""")
    total_stats = sum(stat_values)

    # Radar chart data (SVG polygon)
    stat_names_radar = ["HP", "ATK", "DEF", "SpA", "SpD", "SPD"]
    radar_vals = [min(v / 255, 1.0) for v in stat_values]
    import math

    cx, cy, r = 90, 90, 72
    n = 6
    angles = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
    # Grid polygons
    grid_polys = []
    for frac in [0.25, 0.5, 0.75, 1.0]:
        pts = " ".join(
            f"{cx + r*frac*math.cos(a):.1f},{cy - r*frac*math.sin(a):.1f}"
            for a in angles
        )
        grid_polys.append(
            f'<polygon points="{pts}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>'
        )
    # Axis lines
    axis_lines = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{cx + r*math.cos(a):.1f}" y2="{cy - r*math.sin(a):.1f}" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>'
        for a in angles
    )
    # Stat polygon
    stat_pts = " ".join(
        f"{cx + r*v*math.cos(a):.1f},{cy - r*v*math.sin(a):.1f}"
        for v, a in zip(radar_vals, angles)
    )
    # Labels
    label_html = ""
    for i, (label, a) in enumerate(zip(stat_names_radar, angles)):
        lx = cx + (r + 14) * math.cos(a)
        ly = cy - (r + 14) * math.sin(a)
        label_html += f'<text x="{lx:.1f}" y="{ly+4:.1f}" text-anchor="middle" fill="rgba(255,255,255,0.45)" font-size="8" font-family="Space Mono,monospace" font-weight="700">{label}</text>'
    radar_svg = f"""
    <svg viewBox="0 0 180 180" width="180" height="180" class="radar-svg">
      {"".join(grid_polys)}
      {axis_lines}
      <polygon points="{stat_pts}" fill="{main_color}44" stroke="{main_color}" stroke-width="1.5" stroke-linejoin="round"/>
      {label_html}
    </svg>"""

    # Flavor text
    flavor_entries = [
        e
        for e in species.get("flavor_text_entries", [])
        if e.get("language", {}).get("name") == "en"
    ]
    seen = set()
    flavor_texts = []
    for entry in reversed(flavor_entries):
        txt = _clean_text(entry["flavor_text"])
        game = entry.get("version", {}).get("name", "").replace("-", " ").title()
        if txt and txt not in seen and len(txt) > 20:
            flavor_texts.append((game, txt))
            seen.add(txt)
        if len(flavor_texts) >= 3:
            break

    flavors_html = ""
    for game, txt in flavor_texts:
        flavors_html += f'<div class="flavor-entry"><span class="flavor-game">{game}</span><p class="flavor-text">"{txt}"</p></div>'
    if not flavors_html:
        flavors_html = '<p class="flavor-text">No Pokédex entry available.</p>'

    # Generation & species info
    gen = _generation_label(species.get("generation", {}).get("name", ""))
    habitat_raw = species.get("habitat") or {}
    habitat = (
        habitat_raw.get("name", "Unknown").replace("-", " ").title()
        if habitat_raw
        else "Unknown"
    )
    growth_rate = (
        species.get("growth_rate", {}).get("name", "—").replace("-", " ").title()
    )
    egg_groups = (
        ", ".join(
            eg["name"].replace("-", " ").title() for eg in species.get("egg_groups", [])
        )
        or "—"
    )
    gender_rate = species.get("gender_rate", -1)
    if gender_rate == -1:
        gender_str = "Genderless"
    else:
        fp = gender_rate / 8 * 100
        gender_str = f"♂ {100-fp:.0f}% · ♀ {fp:.0f}%"

    is_legendary = species.get("is_legendary", False)
    is_mythical = species.get("is_mythical", False)
    rarity_badge = ""
    if is_mythical:
        rarity_badge = '<span class="rarity-badge mythical">✦ Mythical</span>'
    elif is_legendary:
        rarity_badge = '<span class="rarity-badge legendary">★ Legendary</span>'

    # Evolution chain
    all_names = set()
    for edge in evo_chain:
        all_names.add(edge["from"])
        if edge["to"]:
            all_names.add(edge["to"])

    if not evo_chain or evo_chain[0]["to"] is None:
        evo_names = [evo_chain[0]["from"]] if evo_chain else [pokemon["name"]]
        evos_str = f'<div class="evo-node evo-current"><span class="evo-name">{name}</span><span class="evo-label">No evolutions</span></div>'
    else:
        evo_nodes = {}
        for edge in evo_chain:
            if edge["from"] not in evo_nodes:
                evo_nodes[edge["from"]] = None
            if edge["to"]:
                trigger = (
                    edge["trigger"].replace("-", " ").title() if edge["trigger"] else ""
                )
                lvl = f" Lv.{edge['min_level']}" if edge["min_level"] else ""
                item = (
                    f" ({edge['item'].replace('-',' ').title()})"
                    if edge["item"]
                    else ""
                )
                label = f"{trigger}{lvl}{item}".strip() or "→"
                evo_nodes[edge["to"]] = label

        parts = []
        for pname, label in evo_nodes.items():
            is_current = pname == pokemon["name"]
            css = "evo-node evo-current" if is_current else "evo-node"
            img_num = ""  # we'd need to look up ID; skip for simplicity
            cap = pname.capitalize()
            lbl_html = f'<span class="evo-label">{label}</span>' if label else ""
            parts.append(
                f'<div class="{css}">{lbl_html}<span class="evo-name">{cap}</span></div>'
            )
            if label:
                parts.insert(-1, f'<span class="evo-arrow">→</span>')
        # Rebuild properly
        parts = []
        items = list(evo_nodes.items())
        for i, (pname, label) in enumerate(items):
            is_current = pname == pokemon["name"]
            css = "evo-node evo-current" if is_current else "evo-node"
            cap = pname.capitalize()
            if i > 0 and label:
                parts.append(f'<span class="evo-arrow" title="{label}">→</span>')
            elif i > 0:
                parts.append('<span class="evo-arrow">→</span>')
            lbl_html = (
                f'<div class="evo-label">{label}</div>' if (label and i > 0) else ""
            )
            parts.append(
                f'<div class="{css}"><span class="evo-name">{cap}</span></div>'
            )
        evos_str = "".join(parts)

    # Moves table
    moves_table_rows = ""
    for m in moves_data[:20]:
        t = m.get("type", "normal")
        tc = TYPE_COLORS.get(t, "#888")
        dc = m.get("damage_class", "status")
        dcc = DAMAGE_CLASS_COLORS.get(dc, "#888")
        icon = MOVE_CATEGORY_ICONS.get(dc, "")
        pw = m.get("power") or "—"
        acc = m.get("accuracy") or "—"
        pp = m.get("pp") or "—"
        method = m.get("method", "").replace("-", " ").title()
        lvl = m.get("level_learned_at", "")
        how = f"Lv.{lvl}" if lvl and lvl > 0 else method
        moves_table_rows += f"""
        <tr>
          <td class="move-name">{m['name'].replace('-',' ').title()}</td>
          <td><span class="move-type-badge" style="background:{tc}44;color:{tc};border:1px solid {tc}66">{t.upper()}</span></td>
          <td><span class="move-dc" style="color:{dcc}">{icon} {dc.title()}</span></td>
          <td class="move-num">{pw}</td>
          <td class="move-num">{acc}</td>
          <td class="move-num">{pp}</td>
          <td class="move-how">{how}</td>
        </tr>"""

    # Type effectiveness
    defense_chart = _compute_defense_chart(types)
    weak4 = [t for t, m in defense_chart.items() if m == 4]
    weak2 = [t for t, m in defense_chart.items() if m == 2]
    immune = [t for t, m in defense_chart.items() if m == 0]
    resist2 = [t for t, m in defense_chart.items() if m == 0.5]
    resist4 = [t for t, m in defense_chart.items() if m == 0.25]

    def _eff_badges(types_list: list, mult: str, bg: str, col: str) -> str:
        if not types_list:
            return f'<span class="eff-none">None</span>'
        badges = "".join(
            f'<span class="eff-badge" style="background:{TYPE_COLORS.get(t,"#888")}22;color:{TYPE_COLORS.get(t,"#888")};border:1px solid {TYPE_COLORS.get(t,"#888")}55">'
            f'{t.upper()} <span class="eff-mult">{mult}</span></span>'
            for t in sorted(types_list)
        )
        return badges

    weakness_section = f"""
    <div class="eff-group">
      <div class="eff-title" style="color:#ef4444">⚠ Weaknesses</div>
      <div class="eff-row">
        {"".join(f'<span class="eff-badge" style="background:{TYPE_COLORS.get(t,"#888")}22;color:{TYPE_COLORS.get(t,"#888")};border:1px solid {TYPE_COLORS.get(t,"#888")}55">{t.upper()} <span class="eff-mult">×4</span></span>' for t in sorted(weak4)) if weak4 else ""}
        {"".join(f'<span class="eff-badge" style="background:{TYPE_COLORS.get(t,"#888")}22;color:{TYPE_COLORS.get(t,"#888")};border:1px solid {TYPE_COLORS.get(t,"#888")}55">{t.upper()} <span class="eff-mult">×2</span></span>' for t in sorted(weak2)) if weak2 else ""}
        {'<span class="eff-none">None</span>' if not weak4 and not weak2 else ""}
      </div>
    </div>
    <div class="eff-group">
      <div class="eff-title" style="color:#22c55e">🛡 Resistances</div>
      <div class="eff-row">
        {"".join(f'<span class="eff-badge" style="background:{TYPE_COLORS.get(t,"#888")}22;color:{TYPE_COLORS.get(t,"#888")};border:1px solid {TYPE_COLORS.get(t,"#888")}55">{t.upper()} <span class="eff-mult">×½</span></span>' for t in sorted(resist2)) if resist2 else ""}
        {"".join(f'<span class="eff-badge" style="background:{TYPE_COLORS.get(t,"#888")}22;color:{TYPE_COLORS.get(t,"#888")};border:1px solid {TYPE_COLORS.get(t,"#888")}55">{t.upper()} <span class="eff-mult">×¼</span></span>' for t in sorted(resist4)) if resist4 else ""}
        {'<span class="eff-none">None</span>' if not resist2 and not resist4 else ""}
      </div>
    </div>
    <div class="eff-group">
      <div class="eff-title" style="color:#a78bfa">🚫 Immunities</div>
      <div class="eff-row">
        {"".join(f'<span class="eff-badge" style="background:{TYPE_COLORS.get(t,"#888")}22;color:{TYPE_COLORS.get(t,"#888")};border:1px solid {TYPE_COLORS.get(t,"#888")}55">{t.upper()} <span class="eff-mult">×0</span></span>' for t in sorted(immune)) if immune else '<span class="eff-none">None</span>'}
      </div>
    </div>"""

    # Encounters
    if encounter_locations:
        enc_html = "".join(
            f'<div class="enc-loc">📍 {loc}</div>' for loc in encounter_locations
        )
    else:
        enc_html = '<p class="enc-none">Not found in the wild — must be obtained through other means.</p>'

    # Held items
    held_items = pokemon.get("held_items", [])
    held_html = ""
    if held_items:
        for hi in held_items:
            iname = hi["item"]["name"].replace("-", " ").title()
            held_html += f'<span class="held-item">🎒 {iname}</span>'
    else:
        held_html = '<span class="held-item-none">No wild held items</span>'

    # Sprite URLs
    sprites = pokemon.get("sprites", {})
    official_art = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{num}.png"
    shiny_art = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{num}.png"
    fallback_sprite = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{num}.png"
    animated_sprite = (
        sprites.get("other", {}).get("showdown", {}).get("front_default", "")
        or fallback_sprite
    )

    # Narrative
    narrative_html = (
        f'<p class="narrative-text">{llm_narrative}</p>' if llm_narrative else ""
    )

    # --- CSS + HTML ---
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
  position: relative; max-width: 700px; margin: 0 auto;
  border-radius: 28px; overflow: hidden; background: #0d0d14;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.06), 0 24px 60px rgba(0,0,0,0.7), 0 0 80px {main_color}22;
  color: #e8e8f0;
}}

/* ---- BANNER ---- */
.poke-banner {{
  position: relative;
  background: linear-gradient(135deg, {main_color}cc 0%, {second_color}88 55%, {main_color}44 100%);
  padding: 28px 28px 0; overflow: hidden; min-height: 230px;
  display: flex; align-items: flex-end; justify-content: space-between;
}}
.poke-banner::before {{
  content: ''; position: absolute; top: -80px; right: -80px;
  width: 360px; height: 360px;
  background: radial-gradient(circle, rgba(255,255,255,0.07) 0%, transparent 70%);
  border-radius: 50%; border: 2px solid rgba(255,255,255,0.05); pointer-events: none;
}}
.banner-particles {{ position:absolute; inset:0; pointer-events:none; overflow:hidden; }}
.particle {{
  position:absolute; border-radius:50%; animation: particleFloat linear infinite;
  background: rgba(255,255,255,0.15);
}}
@keyframes particleFloat {{
  0% {{ transform: translateY(100%) scale(0); opacity: 0; }}
  10% {{ opacity: 1; }}
  90% {{ opacity: 0.5; }}
  100% {{ transform: translateY(-120px) scale(1.2); opacity: 0; }}
}}
.poke-banner-text {{ position: relative; z-index: 2; padding-bottom: 24px; flex: 1; }}
.poke-num {{ font-family:'Space Mono',monospace; font-size:0.82rem; font-weight:700; color:rgba(255,255,255,0.6); letter-spacing:1px; margin-bottom:4px; }}
.poke-name-big {{ font-size:2.6rem; font-weight:900; color:#fff; letter-spacing:-1px; text-shadow:0 2px 20px rgba(0,0,0,0.4); line-height:1; margin-bottom:10px; }}
.poke-types {{ display:flex; gap:8px; flex-wrap:wrap; }}
.type-badge {{ border-radius:20px; font-weight:800; letter-spacing:1px; color:#fff; text-transform:uppercase; border:1px solid rgba(255,255,255,0.25); }}
.rarity-badge {{ display:inline-flex; align-items:center; gap:4px; padding:4px 12px; border-radius:12px; font-size:0.7rem; font-weight:800; letter-spacing:0.5px; margin-top:8px; }}
.legendary {{ background:rgba(255,200,50,0.25); color:#FFD700; border:1px solid rgba(255,200,50,0.4); }}
.mythical {{ background:rgba(255,100,200,0.25); color:#FF78C4; border:1px solid rgba(255,100,200,0.4); }}

/* ---- SPRITE ZONE ---- */
.poke-sprite-zone {{ position:relative; z-index:2; display:flex; flex-direction:column; align-items:center; gap:6px; padding-bottom:0; min-width:210px; }}
.poke-artwork {{ width:210px; height:210px; object-fit:contain; filter:drop-shadow(0 8px 32px rgba(0,0,0,0.6)); animation:floatAnim 4s ease-in-out infinite; cursor:pointer; transition:opacity 0.25s,transform 0.25s; }}
.poke-artwork:hover {{ transform:scale(1.06); }}
@keyframes floatAnim {{ 0%,100% {{ transform:translateY(0px) rotate(-1deg); }} 50% {{ transform:translateY(-10px) rotate(1deg); }} }}
.sprite-toggle {{ display:flex; gap:6px; margin-bottom:8px; }}
.sprite-btn {{ padding:3px 10px; border-radius:10px; font-size:0.65rem; font-weight:700; cursor:pointer; border:1px solid rgba(255,255,255,0.2); background:rgba(0,0,0,0.3); color:rgba(255,255,255,0.7); transition:all 0.2s; font-family:'Nunito',sans-serif; letter-spacing:0.5px; }}
.sprite-btn.active {{ background:rgba(255,255,255,0.15); color:#fff; border-color:rgba(255,255,255,0.4); }}
.sprite-btn:hover {{ background:rgba(255,255,255,0.12); }}

/* ---- TABS ---- */
.tab-bar {{ display:flex; gap:2px; padding:0 20px; background:rgba(0,0,0,0.25); border-bottom:1px solid rgba(255,255,255,0.05); }}
.tab-btn {{ padding:12px 18px; font-size:0.72rem; font-weight:800; letter-spacing:0.8px; text-transform:uppercase; color:rgba(255,255,255,0.4); cursor:pointer; border:none; background:none; border-bottom:2px solid transparent; transition:all 0.2s; font-family:'Nunito',sans-serif; }}
.tab-btn.active {{ color:#fff; border-bottom-color:{main_color}; }}
.tab-btn:hover {{ color:rgba(255,255,255,0.7); }}
.tab-content {{ display:none; }}
.tab-content.active {{ display:block; }}

/* ---- BODY ---- */
.poke-body {{ padding:24px 28px; display:flex; flex-direction:column; gap:20px; }}
.info-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
.info-tile {{ background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06); border-radius:16px; padding:12px 14px; transition:background 0.2s; }}
.info-tile:hover {{ background:rgba(255,255,255,0.07); }}
.info-lbl {{ font-size:0.6rem; text-transform:uppercase; letter-spacing:0.8px; color:rgba(255,255,255,0.4); margin-bottom:4px; font-weight:700; }}
.info-val {{ font-size:0.9rem; font-weight:800; color:#f0f0ff; }}
.poke-divider {{ border:none; height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.08),transparent); }}
.section-head {{ display:flex; align-items:center; gap:8px; margin-bottom:12px; }}
.section-head-line {{ font-size:0.65rem; text-transform:uppercase; letter-spacing:1.5px; font-weight:900; color:{main_color}; }}
.section-head::after {{ content:''; flex:1; height:1px; background:linear-gradient(90deg,{main_color}44,transparent); }}

/* ---- STATS ---- */
.stats-radar-wrap {{ display:flex; gap:20px; align-items:center; flex-wrap:wrap; }}
.stats-bars {{ flex:1; min-width:220px; }}
.stat-row {{ display:grid; grid-template-columns:38px 1fr 36px; align-items:center; gap:10px; margin-bottom:8px; }}
.stat-label {{ font-family:'Space Mono',monospace; font-size:0.63rem; font-weight:700; color:rgba(255,255,255,0.45); text-align:right; }}
.stat-bar-bg {{ height:7px; background:rgba(255,255,255,0.06); border-radius:10px; overflow:hidden; }}
.stat-bar {{ height:100%; border-radius:10px; width:0; background:var(--bar-color); box-shadow:0 0 8px var(--bar-color); animation:growBar 1s cubic-bezier(.22,1,.36,1) forwards; animation-delay:0.2s; }}
@keyframes growBar {{ from {{ width:0; }} to {{ width:var(--bar-w); }} }}
.stat-value {{ font-family:'Space Mono',monospace; font-size:0.76rem; font-weight:700; text-align:left; }}
.stat-total-row {{ display:flex; justify-content:flex-end; align-items:center; gap:8px; margin-top:4px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.06); }}
.stat-total-label {{ font-size:0.65rem; text-transform:uppercase; letter-spacing:1px; color:rgba(255,255,255,0.4); font-weight:700; }}
.stat-total-val {{ font-family:'Space Mono',monospace; font-size:1rem; font-weight:700; color:#fff; }}
.radar-svg {{ opacity:0.9; }}

/* ---- ABILITIES ---- */
.abilities-wrap {{ display:flex; gap:8px; flex-wrap:wrap; }}
.ability-pill {{ display:flex; align-items:center; gap:6px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:6px 14px; font-size:0.78rem; font-weight:700; color:#d0d0e8; transition:all 0.2s; cursor:help; }}
.ability-pill:hover {{ background:rgba(255,255,255,0.1); border-color:{main_color}66; }}
.ability-hidden {{ background:rgba(255,255,255,0.03); border-style:dashed; opacity:0.75; }}
.hidden-tag {{ font-size:0.55rem; text-transform:uppercase; letter-spacing:0.5px; background:rgba(255,200,100,0.2); color:#ffd97d; padding:1px 5px; border-radius:5px; font-weight:800; }}

/* ---- NARRATIVE ---- */
.narrative-card {{ background:linear-gradient(135deg,{main_color}11,rgba(255,255,255,0.03)); border:1px solid {main_color}33; border-radius:16px; padding:16px 20px; }}
.narrative-label {{ font-size:0.6rem; text-transform:uppercase; letter-spacing:1px; color:{main_color}; font-weight:900; margin-bottom:8px; }}
.narrative-text {{ font-size:0.88rem; line-height:1.7; color:rgba(255,255,255,0.75); font-weight:600; }}

/* ---- FLAVOR ---- */
.flavor-entry {{ margin-bottom:12px; }}
.flavor-game {{ display:inline-block; font-size:0.6rem; text-transform:uppercase; letter-spacing:0.8px; font-weight:800; color:{main_color}; background:{main_color}22; padding:2px 8px; border-radius:6px; margin-bottom:6px; }}
.flavor-text {{ font-size:0.86rem; line-height:1.65; color:rgba(255,255,255,0.6); font-style:italic; font-weight:600; border-left:3px solid {main_color}55; padding-left:12px; }}

/* ---- TYPE EFFECTIVENESS ---- */
.eff-group {{ margin-bottom:14px; }}
.eff-title {{ font-size:0.65rem; text-transform:uppercase; letter-spacing:1px; font-weight:900; margin-bottom:8px; }}
.eff-row {{ display:flex; flex-wrap:wrap; gap:6px; }}
.eff-badge {{ display:inline-flex; align-items:center; gap:4px; padding:4px 10px; border-radius:10px; font-size:0.68rem; font-weight:800; letter-spacing:0.5px; }}
.eff-mult {{ font-size:0.6rem; opacity:0.8; }}
.eff-none {{ font-size:0.78rem; color:rgba(255,255,255,0.25); font-style:italic; }}

/* ---- MOVES ---- */
.moves-table {{ width:100%; border-collapse:collapse; font-size:0.78rem; }}
.moves-table thead tr {{ border-bottom:1px solid rgba(255,255,255,0.08); }}
.moves-table th {{ font-size:0.58rem; text-transform:uppercase; letter-spacing:0.8px; color:rgba(255,255,255,0.3); font-weight:800; padding:6px 8px; text-align:left; }}
.moves-table td {{ padding:7px 8px; border-bottom:1px solid rgba(255,255,255,0.04); vertical-align:middle; }}
.moves-table tr:hover td {{ background:rgba(255,255,255,0.03); }}
.move-name {{ font-weight:800; color:#e8e8f0; }}
.move-type-badge {{ padding:2px 8px; border-radius:6px; font-size:0.62rem; font-weight:800; letter-spacing:0.5px; }}
.move-dc {{ font-size:0.72rem; font-weight:700; white-space:nowrap; }}
.move-num {{ font-family:'Space Mono',monospace; font-size:0.72rem; color:rgba(255,255,255,0.6); text-align:center; }}
.move-how {{ font-size:0.68rem; color:rgba(255,255,255,0.35); font-weight:700; }}

/* ---- ENCOUNTERS ---- */
.enc-grid {{ display:flex; flex-wrap:wrap; gap:8px; }}
.enc-loc {{ background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.07); border-radius:10px; padding:6px 14px; font-size:0.78rem; font-weight:700; color:rgba(255,255,255,0.65); }}
.enc-none {{ font-size:0.84rem; color:rgba(255,255,255,0.35); font-style:italic; }}
.held-items-wrap {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }}
.held-item {{ background:rgba(255,200,50,0.08); border:1px solid rgba(255,200,50,0.2); border-radius:10px; padding:5px 12px; font-size:0.78rem; font-weight:700; color:#ffd97d; }}
.held-item-none {{ font-size:0.78rem; color:rgba(255,255,255,0.25); font-style:italic; }}

/* ---- EVO CHAIN ---- */
.evo-chain {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:center; padding:8px 0; }}
.evo-node {{ display:flex; flex-direction:column; align-items:center; gap:4px; }}
.evo-name {{ font-size:0.8rem; font-weight:800; color:rgba(255,255,255,0.6); padding:5px 14px; border-radius:20px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08); transition:all 0.2s; }}
.evo-node:hover .evo-name {{ background:rgba(255,255,255,0.1); color:#fff; }}
.evo-current .evo-name {{ background:linear-gradient(135deg,{main_color}44,{second_color}33); border-color:{main_color}88; color:#fff; box-shadow:0 0 16px {main_color}44; }}
.evo-label {{ font-size:0.6rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.5px; font-weight:700; margin-bottom:2px; }}
.evo-arrow {{ font-size:1.1rem; color:rgba(255,255,255,0.2); font-weight:700; cursor:help; }}

/* ---- FOOTER ---- */
.poke-footer {{ display:flex; justify-content:space-between; align-items:center; padding:12px 28px; background:rgba(0,0,0,0.3); font-size:0.62rem; color:rgba(255,255,255,0.2); font-weight:600; letter-spacing:0.3px; font-family:'Space Mono',monospace; }}

@media (max-width:520px) {{
  .poke-banner {{ flex-direction:column; align-items:flex-start; padding-bottom:0; }}
  .poke-sprite-zone {{ width:100%; align-items:flex-end; }}
  .poke-name-big {{ font-size:2rem; }}
  .info-grid {{ grid-template-columns:repeat(2,1fr); }}
  .poke-artwork {{ width:160px; height:160px; }}
  .stats-radar-wrap {{ flex-direction:column; }}
  .tab-btn {{ padding:10px 12px; font-size:0.65rem; }}
}}
</style>
</head>
<body>
<div class="poke-card">

  <!-- BANNER -->
  <div class="poke-banner">
    <div class="banner-particles" id="particles"></div>
    <div class="poke-banner-text">
      <div class="poke-num">{num_str}</div>
      <div class="poke-name-big">{name}</div>
      <div class="poke-types">{type_badges_html}</div>
      {rarity_badge}
    </div>
    <div class="poke-sprite-zone">
      <div class="sprite-toggle">
        <button class="sprite-btn active" onclick="setSprite('normal',this)">Normal</button>
        <button class="sprite-btn" onclick="setSprite('shiny',this)">✨ Shiny</button>
        <button class="sprite-btn" onclick="setSprite('animated',this)">▶ Live</button>
      </div>
      <img id="main-artwork" class="poke-artwork"
        src="{official_art}"
        data-normal="{official_art}"
        data-shiny="{shiny_art}"
        data-animated="{animated_sprite}"
        alt="{name}"
        onerror="this.src='{fallback_sprite}'"
        loading="eager">
    </div>
  </div>

  <!-- TABS -->
  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('overview',this)">Overview</button>
    <button class="tab-btn" onclick="switchTab('combat',this)">Combat</button>
    <button class="tab-btn" onclick="switchTab('moves',this)">Moves</button>
    <button class="tab-btn" onclick="switchTab('encounters',this)">Encounters</button>
    <button class="tab-btn" onclick="switchTab('lore',this)">Lore</button>
  </div>

  <!-- TAB: OVERVIEW -->
  <div id="tab-overview" class="tab-content active">
    <div class="poke-body">
      <div class="info-grid">
        <div class="info-tile"><div class="info-lbl">Height</div><div class="info-val">{height_str}</div></div>
        <div class="info-tile"><div class="info-lbl">Weight</div><div class="info-val">{weight_str}</div></div>
        <div class="info-tile"><div class="info-lbl">Base XP</div><div class="info-val">{xp}</div></div>
        <div class="info-tile"><div class="info-lbl">Generation</div><div class="info-val">{gen}</div></div>
        <div class="info-tile"><div class="info-lbl">Habitat</div><div class="info-val">{habitat}</div></div>
        <div class="info-tile"><div class="info-lbl">Growth Rate</div><div class="info-val">{growth_rate}</div></div>
        <div class="info-tile"><div class="info-lbl">Catch Rate</div><div class="info-val">{capture_rate}</div></div>
        <div class="info-tile"><div class="info-lbl">Happiness</div><div class="info-val">{happiness}</div></div>
        <div class="info-tile"><div class="info-lbl">Gender</div><div class="info-val">{gender_str}</div></div>
        <div class="info-tile"><div class="info-lbl">Egg Groups</div><div class="info-val">{egg_groups}</div></div>
      </div>
      <hr class="poke-divider">
      <div>
        <div class="section-head"><span class="section-head-line">Abilities</span></div>
        <div class="abilities-wrap">{"".join(abilities_html)}</div>
      </div>
      <hr class="poke-divider">
      <div>
        <div class="section-head"><span class="section-head-line">Evolution Chain</span></div>
        <div class="evo-chain">{evos_str}</div>
      </div>
      {"<hr class='poke-divider'><div><div class='section-head'><span class='section-head-line'>Trainer's Analysis</span></div>" + narrative_html + "</div>" if narrative_html else ""}
    </div>
  </div>

  <!-- TAB: COMBAT -->
  <div id="tab-combat" class="tab-content">
    <div class="poke-body">
      <div>
        <div class="section-head"><span class="section-head-line">Base Stats</span></div>
        <div class="stats-radar-wrap">
          <div class="stats-bars">
            {"".join(stats_html)}
            <div class="stat-total-row">
              <span class="stat-total-label">Total</span>
              <span class="stat-total-val">{total_stats}</span>
            </div>
          </div>
          {radar_svg}
        </div>
      </div>
      <hr class="poke-divider">
      <div>
        <div class="section-head"><span class="section-head-line">Type Effectiveness (as Defender)</span></div>
        {weakness_section}
      </div>
    </div>
  </div>

  <!-- TAB: MOVES -->
  <div id="tab-moves" class="tab-content">
    <div class="poke-body">
      <div>
        <div class="section-head"><span class="section-head-line">Learnable Moves (top 20)</span></div>
        {"<table class='moves-table'><thead><tr><th>Move</th><th>Type</th><th>Category</th><th>Pwr</th><th>Acc</th><th>PP</th><th>How</th></tr></thead><tbody>" + moves_table_rows + "</tbody></table>" if moves_table_rows else "<p style='color:rgba(255,255,255,0.3);font-style:italic'>No move data available.</p>"}
      </div>
    </div>
  </div>

  <!-- TAB: ENCOUNTERS -->
  <div id="tab-encounters" class="tab-content">
    <div class="poke-body">
      <div>
        <div class="section-head"><span class="section-head-line">Wild Encounter Locations</span></div>
        <div class="enc-grid">{enc_html}</div>
      </div>
      <hr class="poke-divider">
      <div>
        <div class="section-head"><span class="section-head-line">Wild Held Items</span></div>
        <div class="held-items-wrap">{held_html}</div>
      </div>
    </div>
  </div>

  <!-- TAB: LORE -->
  <div id="tab-lore" class="tab-content">
    <div class="poke-body">
      <div class="section-head"><span class="section-head-line">Pokédex Entries</span></div>
      {flavors_html}
    </div>
  </div>

  <div class="poke-footer">
    <span>Pokédex Pro v2.0</span>
    <span>Data: pokeapi.co · Sprites: PokeAPI/sprites</span>
  </div>
</div>

<script>
function setSprite(mode, btn) {{
  document.querySelectorAll('.sprite-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const img = document.getElementById('main-artwork');
  img.style.opacity = '0'; img.style.transform = 'scale(0.85)';
  setTimeout(() => {{
    if (mode === 'shiny') img.src = img.dataset.shiny;
    else if (mode === 'animated') img.src = img.dataset.animated;
    else img.src = img.dataset.normal;
    img.style.opacity = '1'; img.style.transform = 'scale(1)';
  }}, 200);
}}

function switchTab(tabId, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + tabId).classList.add('active');
}}

// Generate banner particles
(function() {{
  const container = document.getElementById('particles');
  const mainColor = '{main_color}';
  for (let i = 0; i < 12; i++) {{
    const p = document.createElement('div');
    p.className = 'particle';
    const size = Math.random() * 6 + 2;
    p.style.cssText = `
      width:${{size}}px; height:${{size}}px;
      left:${{Math.random() * 100}}%;
      bottom: -20px;
      animation-duration: ${{Math.random() * 4 + 3}}s;
      animation-delay: ${{Math.random() * 4}}s;
      background: ${{mainColor}}88;
    `;
    container.appendChild(p);
  }}
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Event emitter helper
# ---------------------------------------------------------------------------


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


async def _notify(emitter, content: str, level: str = "success"):
    if emitter:
        await emitter(
            {"type": "notification", "data": {"type": level, "content": content}}
        )


async def _cite_source(emitter, name: str, url: str, snippet: str):
    if emitter:
        await emitter(
            {
                "type": "citation",
                "data": {
                    "document": [snippet],
                    "metadata": [
                        {
                            "date_accessed": datetime.now().isoformat(),
                            "source": name,
                            "url": url,
                        }
                    ],
                    "source": {"name": name, "url": url},
                },
            }
        )


# ---------------------------------------------------------------------------
# Main Tools Class
# ---------------------------------------------------------------------------


class Tools:
    class Valves(BaseModel):
        sprite_style: str = Field(
            default="official",
            description="Default sprite: 'official' (high-res artwork), 'animated' (showdown), 'pixel' (gen-native).",
        )
        unit: str = Field(
            default="metric",
            description="'metric' (m/kg) or 'imperial' (ft/lb).",
        )
        max_pokemon_id: int = Field(
            default=1025,
            description="Maximum Pokédex number allowed (default 1025 for Scarlet/Violet).",
        )
        generate_narrative: bool = Field(
            default=True,
            description="Use the connected LLM to generate a trainer analysis narrative for each Pokémon.",
        )
        max_moves: int = Field(
            default=20,
            description="Maximum number of moves to fetch and display (3–40). More = slower load.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = False  # Disable auto-citations; we send custom ones

    async def look_up(
        self,
        name_or_id: str,
        __event_emitter__: Optional[callable] = None,
        __user__: Optional[dict] = None,
    ) -> "HTMLResponse | str":
        """
        Look up a Pokémon by name or Pokédex number and display an enhanced card.

        The card includes: animated sprite with shiny/live toggle, type effectiveness chart,
        tabbed UI (Overview / Combat / Moves / Encounters / Lore), radar stat chart,
        AI-generated trainer narrative, wild encounter locations, held items, and multi-game
        Pokédex flavor text entries.

        Usage:
            look_up("pikachu")      → Pikachu's enhanced card
            look_up("384")          → Rayquaza's enhanced card
            look_up("Gengar")       → Gengar's enhanced card
            look_up("mewtwo")       → Mewtwo's legendary card

        :param name_or_id: Pokémon name (e.g. "charizard") or Pokédex number (e.g. "6")
        :return: Rendered HTML Pokédex card
        """
        name = name_or_id.strip().lower()
        if not name:
            msg = "❌ Please provide a Pokémon name or number."
            await _emit(__event_emitter__, msg, done=True)
            return msg

        if name.isdigit():
            num = int(name)
            if num < 1 or num > self.valves.max_pokemon_id:
                msg = f"❌ Pokédex number must be between 1 and {self.valves.max_pokemon_id}."
                await _emit(__event_emitter__, msg, done=True)
                return msg

        try:
            await _emit(__event_emitter__, f"🔍 Searching for '{name_or_id}'…")

            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True, http2=False
            ) as client:

                # Core data
                poke_data = await _get_pokemon(client, name)
                pokemon_name = poke_data["name"].capitalize()
                await _emit(
                    __event_emitter__, f"✨ Found {pokemon_name} — loading details…"
                )

                species_task = _get_species(client, poke_data["species"]["url"])
                encounters_task = _get_encounters(client, poke_data["id"])

                species, encounter_locations = await asyncio.gather(
                    species_task, encounters_task
                )

                await _emit(__event_emitter__, "🔗 Fetching evolution chain…")
                evo_chain = await _get_evolution_chain(
                    client, species["evolution_chain"]["url"]
                )

                # Ability descriptions (first 3)
                await _emit(__event_emitter__, "💡 Loading ability data…")
                ability_descriptions = {}
                for a in poke_data.get("abilities", [])[:3]:
                    aname = a["ability"]["name"]
                    url_a = a["ability"]["url"]
                    desc = await _get_ability_description(client, url_a)
                    ability_descriptions[aname] = desc

                # Moves (level-up + machine, sorted by level)
                await _emit(__event_emitter__, "⚔️ Fetching move data…")
                raw_moves = poke_data.get("moves", [])
                # Prefer level-up moves, fallback to machine
                level_up = []
                machine = []
                for m in raw_moves:
                    for vg in m.get("version_group_details", []):
                        method = vg.get("move_learn_method", {}).get("name", "")
                        lvl = vg.get("level_learned_at", 0)
                        if method == "level-up":
                            level_up.append(
                                (lvl, m["move"]["name"], m["move"]["url"], method)
                            )
                        elif method == "machine":
                            machine.append(
                                (0, m["move"]["name"], m["move"]["url"], method)
                            )

                level_up.sort(key=lambda x: x[0])
                selected_moves = (level_up + machine)[: self.valves.max_moves]

                moves_data = []
                move_fetch_tasks = [
                    _get_move_details(client, url) for _, _, url, _ in selected_moves
                ]
                move_details_list = await asyncio.gather(*move_fetch_tasks)

                for i, (lvl, mname, murl, method) in enumerate(selected_moves):
                    detail = move_details_list[i]
                    moves_data.append(
                        {
                            "name": mname,
                            "level_learned_at": lvl,
                            "method": method,
                            **detail,
                        }
                    )

            # LLM narrative
            narrative = ""
            if self.valves.generate_narrative:
                await _emit(__event_emitter__, "🧠 Generating trainer analysis…")
                types = [t["type"]["name"] for t in poke_data["types"]]
                total_stats = sum(s["base_stat"] for s in poke_data["stats"])
                abilities_list = [
                    a["ability"]["name"].replace("-", " ").title()
                    for a in poke_data.get("abilities", [])
                ]
                flavor_entries = [
                    e
                    for e in species.get("flavor_text_entries", [])
                    if e.get("language", {}).get("name") == "en"
                ]
                flavor_text = (
                    _clean_text(flavor_entries[-1]["flavor_text"])
                    if flavor_entries
                    else ""
                )
                gen = _generation_label(species.get("generation", {}).get("name", ""))

                narrative = await _generate_llm_narrative(
                    pokemon_name=pokemon_name,
                    types=types,
                    total_stats=total_stats,
                    abilities=abilities_list,
                    flavor_text=flavor_text,
                    is_legendary=species.get("is_legendary", False),
                    is_mythical=species.get("is_mythical", False),
                    gen=gen,
                    __user__=__user__,
                )

            await _emit(__event_emitter__, f"🎨 Building card for {pokemon_name}…")

            # Sprite selection
            sprites = poke_data.get("sprites", {})
            sprite_url = sprites.get("other", {}).get("official-artwork", {}).get(
                "front_default"
            ) or _find_best_sprite(sprites)

            html = _build_html(
                pokemon=poke_data,
                species=species,
                evo_chain=evo_chain,
                unit=self.valves.unit,
                sprite_url=sprite_url,
                moves_data=moves_data,
                encounter_locations=encounter_locations,
                ability_descriptions=ability_descriptions,
                llm_narrative=narrative,
            )

            # Emit citation + success notification
            pokeapi_url = f"https://pokeapi.co/api/v2/pokemon/{poke_data['id']}/"
            await _cite_source(
                __event_emitter__,
                name=f"PokéAPI — {pokemon_name} (#{poke_data['id']})",
                url=pokeapi_url,
                snippet=f"Base data for {pokemon_name}: types, stats, abilities, moves, and species info retrieved from PokéAPI.",
            )

            await _emit(__event_emitter__, f"✅ {pokemon_name} card ready!", done=True)
            await _notify(
                __event_emitter__,
                f"Pokédex loaded: {pokemon_name} #{poke_data['id']:04d}",
                "success",
            )

            return HTMLResponse(content=html, headers={"content-disposition": "inline"})

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                msg = f"❌ '{name_or_id}' not found. Check spelling or try a Pokédex number (1–{self.valves.max_pokemon_id})."
            else:
                msg = f"❌ HTTP {e.response.status_code} from PokéAPI."
            await _emit(__event_emitter__, msg, done=True)
            await _notify(__event_emitter__, msg, "error")
            return msg
        except httpx.TimeoutException:
            msg = "❌ Request timed out. PokéAPI may be slow — try again."
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except Exception as exc:
            msg = f"❌ Unexpected error: {exc}"
            await _emit(__event_emitter__, msg, done=True)
            return msg

    async def pokedex_list(
        self,
        generation: Optional[str] = None,
        count: int = 12,
        __event_emitter__: Optional[callable] = None,
    ) -> str:
        """
        Get a formatted list of Pokémon (optionally filtered by generation).

        Examples:
            pokedex_list()                              → First 12 Pokémon
            pokedex_list(generation="generation-iv")   → First 12 Pokémon from Sinnoh
            pokedex_list(count=20)                     → First 20 Pokémon

        :param generation: Generation name like "generation-i" through "generation-ix"
        :param count: How many Pokémon to list (default 12, max 30)
        :return: Formatted markdown list
        """
        count = min(max(count, 1), 30)
        GEN_RANGES = {
            "generation-i": (1, 151),
            "generation-ii": (152, 251),
            "generation-iii": (252, 386),
            "generation-iv": (387, 493),
            "generation-v": (494, 649),
            "generation-vi": (650, 721),
            "generation-vii": (722, 809),
            "generation-viii": (810, 905),
            "generation-ix": (906, 1025),
        }

        try:
            await _emit(__event_emitter__, "📋 Fetching Pokédex list…")

            start_id = 1
            if generation:
                generation = generation.lower()
                if generation not in GEN_RANGES:
                    available = ", ".join(GEN_RANGES.keys())
                    msg = f"❌ Unknown generation. Choose from: {available}"
                    await _emit(__event_emitter__, msg, done=True)
                    return msg
                start_id = GEN_RANGES[generation][0]

            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True, http2=False
            ) as client:
                results = []
                for i in range(start_id, start_id + count):
                    if i > self.valves.max_pokemon_id:
                        break
                    try:
                        poke = await _get_pokemon(client, str(i))
                        results.append(poke)
                    except Exception:
                        continue

            gen_label = _generation_label(generation) if generation else "All"
            lines = [f"### 📋 Pokédex List — {gen_label} ({len(results)} Pokémon)\n"]
            for poke in results:
                n = poke["id"]
                pname = poke["name"].capitalize()
                types = " / ".join(
                    t["type"]["name"].capitalize() for t in poke["types"]
                )
                bst = sum(s["base_stat"] for s in poke["stats"])
                lines.append(f"**#{n:04d}** · **{pname}** — {types} · BST {bst}")

            await _emit(
                __event_emitter__, f"✅ Listed {len(results)} Pokémon!", done=True
            )
            return "\n".join(lines)

        except Exception as exc:
            msg = f"❌ Error: {exc}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
