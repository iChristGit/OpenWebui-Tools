"""
title: Sports Hub Pro
description: Ultimate sports tool — live scores, team schedules (past + future), standings and news rendered as a beautiful inline HTML card. Multi-source cascade: ESPN (site + core + soccer/all), official NHL API (api-web.nhle.com), official MLB API (statsapi.mlb.com), TheSportsDB. Covers 60+ leagues: soccer, NBA, NFL, NHL, MLB, tennis, golf, F1, NASCAR, MMA/UFC, WWE wrestling, AEW, esports (LoL, CS2, Dota2, Overwatch, Valorant), rugby, cricket, AFL and more. No API key required. v11: vivid sport-specific color themes, fixed NBA upcoming games, full-width layout, smarter API usage.
author: ichrist
version: 1.0.0
license: MIT
requirements: httpx
"""

# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE v11 — What changed from v10
#
# CRITICAL FIXES:
#   1. _current_season("basketball" | "hockey") was returning WRONG year.
#      NBA 2025-26 season is ESPN-labeled "2026" (ending year convention).
#      Old formula: m>=9 → y, else y-1   ← WRONG (Mar 2026 → 2025 = old season)
#      New formula: m>=10 → y+1, else y  ← CORRECT (Mar 2026 → 2026 = current)
#      _nhl_season_str now uses (ending_year-1, ending_year) = "20252026".
#   2. NBA/NFL team schedule: if future_cards is empty after ESPN team schedule
#      call, fall back to scoreboard date-range (next 30 days) + filter by team.
#      This ensures upcoming games always show even near season boundaries.
#   3. PATH D upcoming queries: now use a direct DATE RANGE scoreboard fetch
#      instead of probing one day at a time (7x more efficient, more results).
#
# UI OVERHAUL:
#   4. Full-width layout: .sp uses width:100% (no more max-width dead space).
#   5. Sport-specific color themes: each sport gets its own vivid palette
#      injected via CSS classes (.sp-soccer, .sp-basketball, .sp-football, etc.)
#   6. _build_html() now accepts a sport= parameter that picks the theme class.
#   7. All _build_html() callsites updated to pass the correct sport.
#
# API IMPROVEMENTS:
#   8. Scoreboard calls now use ?enable=linescores for richer period data.
#   9. League scoreboard for upcoming queries uses a 14-day date range to catch
#      all scheduled events without multi-round day-by-day probing.
#  10. Odds / win-probability endpoint queried for live games (Core API v2).
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

import httpx
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# ESPN TEAM IDs  {team_fragment: (league_key, espn_team_id)}
# ─────────────────────────────────────────────────────────────────────────────

ESPN_TEAMS: dict[str, tuple] = {
    # ── La Liga ────────────────────────────────────────────────────────────
    "real madrid": ("laliga", 86),
    "fc barcelona": ("laliga", 83),
    "barcelona": ("laliga", 83),
    "barca": ("laliga", 83),
    "atletico madrid": ("laliga", 1068),
    "atletico": ("laliga", 1068),
    "sevilla": ("laliga", 94),
    "real betis": ("laliga", 88),
    "betis": ("laliga", 88),
    "villarreal": ("laliga", 102),
    "real sociedad": ("laliga", 89),
    "athletic bilbao": ("laliga", 84),
    "athletic club": ("laliga", 84),
    "valencia": ("laliga", 100),
    "osasuna": ("laliga", 87),
    "getafe": ("laliga", 3842),
    "girona": ("laliga", 9812),
    "celta vigo": ("laliga", 3833),
    "mallorca": ("laliga", 96),
    "alaves": ("laliga", 3834),
    "rayo vallecano": ("laliga", 3839),
    "rayo": ("laliga", 3839),
    "las palmas": ("laliga", 3840),
    "leganes": ("laliga", 3843),
    "espanyol": ("laliga", 3836),
    "valladolid": ("laliga", 3845),
    # ── EPL ───────────────────────────────────────────────────────────────
    "arsenal": ("epl", 359),
    "chelsea": ("epl", 363),
    "liverpool": ("epl", 364),
    "manchester city": ("epl", 382),
    "man city": ("epl", 382),
    "manchester united": ("epl", 360),
    "man united": ("epl", 360),
    "man utd": ("epl", 360),
    "tottenham": ("epl", 367),
    "tottenham hotspur": ("epl", 367),
    "spurs": ("epl", 367),
    "newcastle": ("epl", 361),
    "west ham": ("epl", 371),
    "aston villa": ("epl", 362),
    "brighton": ("epl", 331),
    "everton": ("epl", 368),
    "crystal palace": ("epl", 384),
    "brentford": ("epl", 333),
    "fulham": ("epl", 370),
    "bournemouth": ("epl", 349),
    "nottingham forest": ("epl", 393),
    "leicester": ("epl", 375),
    "southampton": ("epl", 376),
    "ipswich": ("epl", 373),
    # ── Serie A ───────────────────────────────────────────────────────────
    "juventus": ("seriea", 109),
    "juve": ("seriea", 109),
    "inter milan": ("seriea", 110),
    "inter": ("seriea", 110),
    "ac milan": ("seriea", 103),
    "napoli": ("seriea", 114),
    "roma": ("seriea", 116),
    "lazio": ("seriea", 111),
    "atalanta": ("seriea", 106),
    "fiorentina": ("seriea", 108),
    "torino": ("seriea", 118),
    "bologna": ("seriea", 107),
    "udinese": ("seriea", 119),
    "monza": ("seriea", 5913),
    "lecce": ("seriea", 4056),
    "genoa": ("seriea", 5911),
    "cagliari": ("seriea", 5910),
    # ── Bundesliga ────────────────────────────────────────────────────────
    "bayern munich": ("bundesliga", 132),
    "bayern": ("bundesliga", 132),
    "borussia dortmund": ("bundesliga", 124),
    "dortmund": ("bundesliga", 124),
    "bayer leverkusen": ("bundesliga", 131),
    "leverkusen": ("bundesliga", 131),
    "rb leipzig": ("bundesliga", 11420),
    "leipzig": ("bundesliga", 11420),
    "eintracht frankfurt": ("bundesliga", 126),
    "frankfurt": ("bundesliga", 126),
    "wolfsburg": ("bundesliga", 136),
    "gladbach": ("bundesliga", 127),
    "stuttgart": ("bundesliga", 135),
    "union berlin": ("bundesliga", 11828),
    "freiburg": ("bundesliga", 125),
    "werder bremen": ("bundesliga", 123),
    "augsburg": ("bundesliga", 11430),
    "hoffenheim": ("bundesliga", 10189),
    # ── Ligue 1 ───────────────────────────────────────────────────────────
    "paris saint-germain": ("ligue1", 160),
    "psg": ("ligue1", 160),
    "marseille": ("ligue1", 156),
    "lyon": ("ligue1", 157),
    "monaco": ("ligue1", 158),
    "lille": ("ligue1", 155),
    "rennes": ("ligue1", 162),
    "lens": ("ligue1", 154),
    "nice": ("ligue1", 159),
    "strasbourg": ("ligue1", 165),
    "reims": ("ligue1", 161),
    "nantes": ("ligue1", 3011),
    "toulouse": ("ligue1", 169),
    # ── NBA ───────────────────────────────────────────────────────────────
    "lakers": ("nba", 13),
    "celtics": ("nba", 2),
    "warriors": ("nba", 9),
    "bulls": ("nba", 4),
    "heat": ("nba", 14),
    "knicks": ("nba", 18),
    "nets": ("nba", 17),
    "bucks": ("nba", 15),
    "nuggets": ("nba", 7),
    "suns": ("nba", 24),
    "mavericks": ("nba", 6),
    "mavs": ("nba", 6),
    "clippers": ("nba", 12),
    "rockets": ("nba", 10),
    "thunder": ("nba", 25),
    "blazers": ("nba", 22),
    "trail blazers": ("nba", 22),
    "jazz": ("nba", 26),
    "kings": ("nba", 26),
    "sacramento kings": ("nba", 26),
    "grizzlies": ("nba", 29),
    "pelicans": ("nba", 3),
    "hawks": ("nba", 1),
    "hornets": ("nba", 30),
    "magic": ("nba", 19),
    "pistons": ("nba", 8),
    "pacers": ("nba", 11),
    "cavaliers": ("nba", 5),
    "cavs": ("nba", 5),
    "raptors": ("nba", 28),
    "76ers": ("nba", 20),
    "sixers": ("nba", 20),
    "wizards": ("nba", 27),
    "timberwolves": ("nba", 16),
    "okc": ("nba", 25),
    "spurs": ("nba", 23),
    "san antonio spurs": ("nba", 23),
    # ── NFL ───────────────────────────────────────────────────────────────
    "patriots": ("nfl", 17),
    "chiefs": ("nfl", 12),
    "cowboys": ("nfl", 6),
    "eagles": ("nfl", 21),
    "49ers": ("nfl", 25),
    "packers": ("nfl", 9),
    "steelers": ("nfl", 23),
    "ravens": ("nfl", 33),
    "seahawks": ("nfl", 26),
    "bills": ("nfl", 2),
    "rams": ("nfl", 14),
    "bengals": ("nfl", 4),
    "chargers": ("nfl", 24),
    "broncos": ("nfl", 7),
    "raiders": ("nfl", 13),
    "titans": ("nfl", 10),
    "colts": ("nfl", 11),
    "jaguars": ("nfl", 30),
    "texans": ("nfl", 34),
    "browns": ("nfl", 5),
    "dolphins": ("nfl", 15),
    "jets": ("nfl", 20),
    "giants": ("nfl", 19),
    "bears": ("nfl", 3),
    "vikings": ("nfl", 16),
    "lions": ("nfl", 8),
    "falcons": ("nfl", 1),
    "saints": ("nfl", 18),
    "buccaneers": ("nfl", 27),
    "bucs": ("nfl", 27),
    "cardinals": ("nfl", 22),
    "commanders": ("nfl", 28),
    # ── MLB ───────────────────────────────────────────────────────────────
    "yankees": ("mlb", 10),
    "red sox": ("mlb", 2),
    "dodgers": ("mlb", 19),
    "cubs": ("mlb", 16),
    "astros": ("mlb", 18),
    "mets": ("mlb", 21),
    "braves": ("mlb", 15),
    "phillies": ("mlb", 22),
    "padres": ("mlb", 25),
    "mariners": ("mlb", 28),
    "blue jays": ("mlb", 14),
    "rangers": ("mlb", 13),
    "orioles": ("mlb", 1),
    "twins": ("mlb", 9),
    "reds": ("mlb", 17),
    "tigers": ("mlb", 6),
    "rays": ("mlb", 30),
    "royals": ("mlb", 7),
    "white sox": ("mlb", 4),
    "guardians": ("mlb", 5),
    "nationals": ("mlb", 20),
    "pirates": ("mlb", 23),
    "athletics": ("mlb", 29),
    "angels": ("mlb", 3),
    "rockies": ("mlb", 27),
    "brewers": ("mlb", 8),
    "giants": ("mlb", 26),
    "diamondbacks": ("mlb", 29),
    "dbacks": ("mlb", 29),
    # ── NHL ───────────────────────────────────────────────────────────────
    "bruins": ("nhl", 1),
    "sabres": ("nhl", 2),
    "flames": ("nhl", 3),
    "blackhawks": ("nhl", 4),
    "red wings": ("nhl", 5),
    "oilers": ("nhl", 6),
    "kings": ("nhl", 7),
    "canadiens": ("nhl", 8),
    "senators": ("nhl", 9),
    "rangers": ("nhl", 10),
    "devils": ("nhl", 11),
    "islanders": ("nhl", 12),
    "hurricanes": ("nhl", 13),
    "lightning": ("nhl", 14),
    "flyers": ("nhl", 15),
    "penguins": ("nhl", 16),
    "blues": ("nhl", 17),
    "predators": ("nhl", 18),
    "avalanche": ("nhl", 21),
    "ducks": ("nhl", 25),
    "stars": ("nhl", 24),
    "canucks": ("nhl", 23),
    "capitals": ("nhl", 15),
    "wild": ("nhl", 30),
    "golden knights": ("nhl", 36),
    "kraken": ("nhl", 55),
    "maple leafs": ("nhl", 28),
    "blue jackets": ("nhl", 29),
    "utah hockey": ("nhl", 59),
    "panthers": ("nhl", 13),
}

# NHL abbreviations for the official nhle.com API
NHL_ABBREVS: dict[str, str] = {
    "bruins": "BOS",
    "sabres": "BUF",
    "flames": "CGY",
    "blackhawks": "CHI",
    "red wings": "DET",
    "oilers": "EDM",
    "kings": "LAK",
    "canadiens": "MTL",
    "senators": "OTT",
    "rangers": "NYR",
    "devils": "NJD",
    "islanders": "NYI",
    "hurricanes": "CAR",
    "lightning": "TBL",
    "flyers": "PHI",
    "penguins": "PIT",
    "blues": "STL",
    "predators": "NSH",
    "jets": "WPG",
    "avalanche": "COL",
    "ducks": "ANA",
    "stars": "DAL",
    "canucks": "VAN",
    "capitals": "WSH",
    "wild": "MIN",
    "golden knights": "VGK",
    "kraken": "SEA",
    "maple leafs": "TOR",
    "blue jackets": "CBJ",
    "coyotes": "UTA",
    "utah hockey": "UTA",
    "panthers": "FLA",
}

# MLB team IDs for statsapi.mlb.com
MLB_TEAM_IDS: dict[str, int] = {
    "yankees": 147,
    "red sox": 111,
    "dodgers": 119,
    "cubs": 112,
    "astros": 117,
    "mets": 121,
    "braves": 144,
    "phillies": 143,
    "padres": 135,
    "mariners": 136,
    "blue jays": 141,
    "rangers": 140,
    "orioles": 110,
    "twins": 142,
    "reds": 113,
    "tigers": 116,
    "rays": 139,
    "royals": 118,
    "white sox": 145,
    "guardians": 114,
    "nationals": 120,
    "pirates": 134,
    "athletics": 133,
    "angels": 108,
    "rockies": 115,
    "brewers": 158,
    "giants": 137,
    "diamondbacks": 109,
    "dbacks": 109,
}

TEAM_LEAGUE_MAP: dict[str, str] = {k: v[0] for k, v in ESPN_TEAMS.items()}
TEAM_LEAGUE_MAP.update(
    {
        "inter miami": "mls",
        "la galaxy": "mls",
        "lafc": "mls",
        "seattle sounders": "mls",
        "portland timbers": "mls",
        "atlanta united": "mls",
        "nycfc": "mls",
        "toronto fc": "mls",
        "columbus crew": "mls",
        "dc united": "mls",
        "orlando city": "mls",
        "austin fc": "mls",
        "charlotte fc": "mls",
        "nashville sc": "mls",
        "fc dallas": "mls",
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# LEAGUE REGISTRY  (sport_slug, espn_slug, display_name, emoji, tsdb_id)
# ─────────────────────────────────────────────────────────────────────────────

LEAGUES: dict[str, tuple] = {
    "nba": ("basketball", "nba", "NBA", "🏀", 4387),
    "wnba": ("basketball", "wnba", "WNBA", "🏀", 4389),
    "ncaamb": (
        "basketball",
        "mens-college-basketball",
        "NCAA Basketball(M)",
        "🏀",
        None,
    ),
    "ncaawb": (
        "basketball",
        "womens-college-basketball",
        "NCAA Basketball(W)",
        "🏀",
        None,
    ),
    "nfl": ("football", "nfl", "NFL", "🏈", 4391),
    "ncaafb": ("football", "college-football", "NCAA Football", "🏈", None),
    "mlb": ("baseball", "mlb", "MLB", "⚾", 4424),
    "nhl": ("hockey", "nhl", "NHL", "🏒", 4380),
    "mls": ("soccer", "usa.1", "MLS", "⚽", 4346),
    "epl": ("soccer", "eng.1", "Premier League", "⚽", 4328),
    "laliga": ("soccer", "esp.1", "La Liga", "⚽", 4335),
    "ucl": ("soccer", "uefa.champions", "Champions League", "⚽", 4480),
    "uel": ("soccer", "uefa.europa", "Europa League", "⚽", 4481),
    "uecl": ("soccer", "uefa.europa.conf", "Conference League", "⚽", None),
    "seriea": ("soccer", "ita.1", "Serie A", "⚽", 4332),
    "bundesliga": ("soccer", "ger.1", "Bundesliga", "⚽", 4331),
    "ligue1": ("soccer", "fra.1", "Ligue 1", "⚽", 4334),
    "eredivisie": ("soccer", "ned.1", "Eredivisie", "⚽", 4337),
    "primeiraliga": ("soccer", "por.1", "Primeira Liga", "⚽", 4344),
    "spl": ("soccer", "sco.1", "Scottish Prem", "⚽", 4336),
    "championship": ("soccer", "eng.2", "Championship", "⚽", 4329),
    "la2": ("soccer", "esp.2", "Segunda División", "⚽", 4340),
    "serieb": ("soccer", "ita.2", "Serie B", "⚽", 4333),
    "bundesliga2": ("soccer", "ger.2", "2. Bundesliga", "⚽", None),
    "coparey": ("soccer", "esp.copa_del_rey", "Copa del Rey", "⚽", None),
    "facup": ("soccer", "eng.fa", "FA Cup", "⚽", None),
    "carabao": ("soccer", "eng.league_cup", "Carabao Cup", "⚽", None),
    "euro": ("soccer", "uefa.euro", "UEFA Euro", "⚽", None),
    "wc": ("soccer", "fifa.world", "FIFA World Cup", "⚽", None),
    "nations": ("soccer", "uefa.nations", "UEFA Nations Lge", "⚽", None),
    "ligamx": ("soccer", "mex.1", "Liga MX", "⚽", 4350),
    "brasileirao": ("soccer", "bra.1", "Brasileirao", "⚽", 4351),
    "argentina": ("soccer", "arg.1", "Liga Profesional", "⚽", 4406),
    "copalibert": ("soccer", "conmebol.libertadores", "Copa Libertadores", "⚽", None),
    "tennis": ("tennis", "atp", "ATP Tennis", "🎾", None),
    "wta": ("tennis", "wta", "WTA Tennis", "🎾", None),
    "golf": ("golf", "leaderboard", "Golf / PGA", "⛳", None),
    "f1": ("racing", "f1", "Formula 1", "🏎️", 4370),
    "mma": ("mma", "ufc", "UFC / MMA", "🥊", 4443),
    "boxing": ("boxing", "boxing", "Boxing", "🥊", None),
    "rugby": ("rugby", "irb", "Rugby Union", "🏉", None),
    "rugbyl": ("rugby-league", "nrl", "Rugby League", "🏉", None),
    "cricket": ("cricket", "icc", "Cricket", "🏏", None),
    "afl": ("australian-football", "afl", "AFL", "🏉", None),
    "nascar": ("racing", "nascar-premier", "NASCAR Cup Series", "🏁", 4370),
    "indycar": ("racing", "indycar", "IndyCar Series", "🏁", None),
    "wwe": ("wrestling", "wwe", "WWE Wrestling", "🤼", 4428),
    "aew": ("wrestling", "aew", "AEW Wrestling", "🤼", None),
    "lol": ("esports", "lol", "League of Legends", "🎮", 4455),
    "csgo": ("esports", "cs2", "CS2 / Counter-Strike", "🎮", 4421),
    "dota2": ("esports", "dota2", "Dota 2", "🎮", 4422),
    "overwatch": ("esports", "owl", "Overwatch League", "🎮", 4434),
    "valorant": ("esports", "valorant", "VALORANT Champions", "🎮", None),
    "rl": ("esports", "rocketleague", "Rocket League", "🎮", None),
    "lacrosse": ("lacrosse", "pll", "Pro Lacrosse (PLL)", "🥍", None),
    "handball": ("handball", "ehf", "EHF Handball", "🤾", None),
}

SPORT_GROUP_MAP: dict[str, list[str]] = {
    "soccer": ["epl", "laliga", "ucl", "seriea", "bundesliga", "ligue1", "uel"],
    "football": ["nfl"],
    "basketball": ["nba", "wnba"],
    "hockey": ["nhl"],
    "baseball": ["mlb"],
    "mma": ["mma"],
    "ufc": ["mma"],
    "tennis": ["tennis", "wta"],
    "golf": ["golf"],
    "f1": ["f1"],
    "formula 1": ["f1"],
    "formula one": ["f1"],
    "racing": ["f1", "nascar", "indycar"],
    "nascar": ["nascar"],
    "indycar": ["indycar"],
    "rugby": ["rugby", "rugbyl"],
    "cricket": ["cricket"],
    "afl": ["afl"],
    "wrestling": ["wwe", "aew"],
    "wwe": ["wwe"],
    "aew": ["aew"],
    "esports": ["lol", "csgo", "dota2", "overwatch", "valorant", "rl"],
    "league of legends": ["lol"],
    "lol": ["lol"],
    "counter-strike": ["csgo"],
    "cs2": ["csgo"],
    "csgo": ["csgo"],
    "dota": ["dota2"],
    "dota 2": ["dota2"],
    "overwatch": ["overwatch"],
    "valorant": ["valorant"],
    "rocket league": ["rl"],
    "boxing": ["boxing"],
    "lacrosse": ["lacrosse"],
}

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports"
ESPN_LOGO = "https://a.espncdn.com/i/teamlogos"
TSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
NHL_BASE = "https://api-web.nhle.com/v1"
MLB_BASE = "https://statsapi.mlb.com/api/v1"

# ─────────────────────────────────────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────────────────────────────────────

_cache: dict = {}


def _ck(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def _cget(k: str):
    e = _cache.get(k)
    return e[1] if e and time.time() < e[0] else None


def _cset(k: str, v, ttl: int = 60):
    _cache[k] = (time.time() + ttl, v)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────

_HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
_CLIENT: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(timeout=12, headers=_HDRS, follow_redirects=True)
    return _CLIENT


# ─────────────────────────────────────────────────────────────────────────────
# CSS — v11: SPORT-SPECIFIC VIVID THEMES  +  FULL-WIDTH LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;800;900&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,700&display=swap');

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent;font-family:'DM Sans',system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;color-scheme:dark;}

/* ════════════════════════════════════════════════════════════
   ROOT DEFAULTS (Soccer / generic — lush green)
════════════════════════════════════════════════════════════ */
:root{
  --bg0:#07100a; --bg1:#0c1710; --bg2:#101d13; --bg3:#152018;
  --line:#1b2e20; --line2:#233527; --line3:#2c4532;
  --txt:#e4f5eb; --txt2:#9dbfaa; --dim:#4d7a5e; --dim2:#2e4d39;
  --a1:#00e676; --a2:#00c853; --a3:#69ff47; --neon:#30ff80;
  --glow:rgba(0,230,118,.4); --glow2:rgba(0,230,118,.1);
  --red:#ff4d6a; --gold:#ffd740; --blue:#29b6f6; --purp:#ce93d8;
}

/* ── BASKETBALL (NBA) — orange flame + midnight blue ─────── */
.sp-basketball{
  --bg0:#07080f; --bg1:#0c0e1a; --bg2:#10142a; --bg3:#141836;
  --line:#1e2240; --line2:#252b50; --line3:#303860;
  --txt:#f0f2ff; --dim:#5a6290; --dim2:#343d6a;
  --a1:#E8503A; --a2:#1D428A; --a3:#FEC524; --neon:#E8503A;
  --glow:rgba(232,80,58,.45); --glow2:rgba(29,66,138,.15);
}
/* ── FOOTBALL (NFL) — gold rush + deep navy ──────────────── */
.sp-football{
  --bg0:#080807; --bg1:#0f0f0e; --bg2:#161611; --bg3:#1c1c14;
  --line:#2a2918; --line2:#343420; --line3:#40402a;
  --txt:#f5f3e8; --dim:#706e4a; --dim2:#3e3d27;
  --a1:#FFB612; --a2:#013369; --a3:#D50A0A; --neon:#FFB612;
  --glow:rgba(255,182,18,.5); --glow2:rgba(1,51,105,.15);
}
/* ── HOCKEY (NHL) — glacier blue + white ice ─────────────── */
.sp-hockey{
  --bg0:#060a10; --bg1:#09101e; --bg2:#0d172a; --bg3:#111e34;
  --line:#1a2a40; --line2:#223350; --line3:#2a3e60;
  --txt:#e8f4ff; --dim:#4a7090; --dim2:#2a4060;
  --a1:#0088FF; --a2:#66C5FF; --a3:#FFFFFF; --neon:#66C5FF;
  --glow:rgba(0,136,255,.45); --glow2:rgba(102,197,255,.1);
}
/* ── BASEBALL (MLB) — deep red + patriot blue ────────────── */
.sp-baseball{
  --bg0:#080508; --bg1:#100810; --bg2:#180c18; --bg3:#201020;
  --line:#30182a; --line2:#3c2035; --line3:#4a2840;
  --txt:#f5eef5; --dim:#80506a; --dim2:#4a2e40;
  --a1:#C4002B; --a2:#003087; --a3:#FFD700; --neon:#C4002B;
  --glow:rgba(196,0,43,.45); --glow2:rgba(0,48,135,.15);
}
/* ── F1 / RACING — racing red + dark asphalt ────────────── */
.sp-racing{
  --bg0:#080707; --bg1:#0f0d0d; --bg2:#161312; --bg3:#1c1918;
  --line:#2a2020; --line2:#352828; --line3:#403030;
  --txt:#f5f0ee; --dim:#806050; --dim2:#4a3830;
  --a1:#FF1801; --a2:#FF8C00; --a3:#FFD700; --neon:#FF1801;
  --glow:rgba(255,24,1,.5); --glow2:rgba(255,140,0,.15);
}
/* ── MMA / UFC — blood red + gold championship ───────────── */
.sp-mma{
  --bg0:#080808; --bg1:#100808; --bg2:#180c0c; --bg3:#201010;
  --line:#301818; --line2:#3c2020; --line3:#4a2828;
  --txt:#f5ecec; --dim:#804040; --dim2:#4a2424;
  --a1:#E40000; --a2:#FFD700; --a3:#FF6B00; --neon:#FF6B00;
  --glow:rgba(228,0,0,.45); --glow2:rgba(255,107,0,.15);
}
/* ── TENNIS — lime court + stadium green ────────────────── */
.sp-tennis{
  --bg0:#080a06; --bg1:#0d1009; --bg2:#12160d; --bg3:#171c12;
  --line:#222a18; --line2:#2c3620; --line3:#384228;
  --txt:#f0f5e8; --dim:#608040; --dim2:#384d24;
  --a1:#C8E93C; --a2:#3A7D44; --a3:#FFDF00; --neon:#C8E93C;
  --glow:rgba(200,233,60,.45); --glow2:rgba(58,125,68,.15);
}
/* ── CRICKET / RUGBY / AFL — earthy amber ───────────────── */
.sp-other{
  --a1:#FF9800; --a2:#5D4037; --a3:#FFEB3B; --neon:#FF9800;
  --glow:rgba(255,152,0,.4); --glow2:rgba(93,64,55,.15);
}

/* ════════════════════════════════════════════════════════════
   LAYOUT — full-width, no dead space
════════════════════════════════════════════════════════════ */
.sp{
  background:var(--bg0);color:var(--txt);
  width:100%;
  border-radius:16px;padding:18px 20px 16px;
  border:1px solid var(--line2);
  box-shadow:0 16px 48px rgba(0,0,0,.9),0 0 0 1px var(--glow2),
             inset 0 1px 0 var(--glow2);
  position:relative;overflow:hidden;
}
.sp::before{
  content:'';position:absolute;top:0;left:6%;right:6%;height:1px;
  background:linear-gradient(90deg,transparent,var(--a2) 30%,var(--neon) 50%,var(--a2) 70%,transparent);
  filter:blur(.4px);
}

/* Header */
.sp-hd{display:flex;align-items:center;justify-content:space-between;padding-bottom:12px;margin-bottom:14px;border-bottom:1px solid var(--line);}
.sp-hd h2{font-family:'Barlow Condensed',sans-serif;font-size:1.35rem;font-weight:900;letter-spacing:.6px;text-transform:uppercase;color:var(--a1);
  text-shadow:0 0 20px var(--glow),0 0 40px var(--glow2);margin:0;}
.sp-hd time{font-size:.62rem;color:var(--dim);letter-spacing:.3px;background:var(--bg2);padding:3px 10px;border-radius:20px;border:1px solid var(--line2);white-space:nowrap;}

/* Pills */
.sp-pills{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px;}
.sp-pill{border-radius:20px;padding:4px 13px;font-size:.65rem;font-weight:700;display:inline-flex;align-items:center;gap:5px;border:1px solid;letter-spacing:.5px;text-transform:uppercase;}
.sp-pill.live{color:var(--red);border-color:var(--red);background:rgba(255,77,106,.09);}
.sp-pill.done{color:var(--dim);border-color:var(--line2);background:var(--bg2);}
.sp-pill.soon{color:var(--a1);border-color:var(--a2);background:var(--glow2);}

/* Section divider */
.sp-day{display:flex;align-items:center;gap:10px;font-size:.6rem;font-weight:700;color:var(--a2);text-transform:uppercase;letter-spacing:3px;margin:20px 0 9px;padding-bottom:7px;border-bottom:1px solid var(--line);}
.sp-day::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--line2),transparent);}
.sp-sec{font-family:'Barlow Condensed',sans-serif;font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:3px;color:var(--a2);margin:22px 0 8px;}

/* ═══ GAME CARD ═══ */
.sp-game{
  background:linear-gradient(150deg,var(--bg1) 0%,var(--bg2) 100%);
  border:1px solid var(--line);border-radius:14px;margin:6px 0;overflow:hidden;
  transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease;
}
.sp-game:hover{transform:translateY(-2px);border-color:var(--line3);box-shadow:0 6px 28px rgba(0,0,0,.45);}
.sp-game.live-card{border-color:rgba(255,77,106,.3);box-shadow:0 0 20px rgba(255,77,106,.07);}

/* Meta bar */
.sp-meta{display:flex;align-items:center;justify-content:space-between;padding:6px 14px 5px;border-bottom:1px solid var(--line);background:rgba(0,0,0,.18);}
.sp-comp-name{font-size:.63rem;font-weight:600;color:var(--dim);letter-spacing:.15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px;}
.sp-note-txt{color:var(--a3);font-size:.63rem;font-weight:700;}

/* Game body 3-col */
.sp-body{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:14px 14px 12px;gap:8px;}

/* Team block */
.sp-team2{display:flex;align-items:center;gap:10px;}
.sp-team2.r{flex-direction:row-reverse;text-align:right;}
.sp-team2 img{width:40px;height:40px;object-fit:contain;flex-shrink:0;border-radius:6px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.6));}
.sp-tname{font-family:'Barlow Condensed',sans-serif;font-size:1.08rem;font-weight:800;letter-spacing:.3px;text-transform:uppercase;color:var(--txt);line-height:1.15;}
.sp-trec{font-size:.6rem;color:var(--dim);margin-top:2px;}
.sp-team2.winner .sp-tname{color:var(--a1);text-shadow:0 0 12px var(--glow);}
.sp-team2.loser .sp-tname{color:var(--dim);}

/* Score center */
.sp-sc-block{display:flex;flex-direction:column;align-items:center;gap:3px;min-width:120px;}
.sp-badge2{display:inline-flex;align-items:center;gap:4px;font-size:.54rem;font-weight:800;padding:3px 11px;border-radius:20px;letter-spacing:.9px;text-transform:uppercase;border:1px solid;margin-bottom:2px;}
.sp-badge2.done{background:var(--bg3);color:var(--dim);border-color:var(--line2);}
.sp-badge2.live{background:rgba(255,77,106,.1);color:var(--red);border-color:rgba(255,77,106,.4);box-shadow:0 0 10px rgba(255,77,106,.2);}
.sp-badge2.soon{background:var(--glow2);color:var(--a1);border-color:var(--a2);}
.sp-dot2{width:5px;height:5px;border-radius:50%;background:var(--red);box-shadow:0 0 6px var(--red);animation:pulse2 1.1s ease-in-out infinite;}
@keyframes pulse2{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.2;transform:scale(.55);}}

.sp-scores{display:flex;align-items:baseline;gap:0;font-family:'Barlow Condensed',sans-serif;font-weight:900;line-height:1;}
.sp-sn{font-size:2.8rem;color:var(--txt);letter-spacing:-1px;}
.sp-sn.win{color:var(--a1);text-shadow:0 0 18px var(--glow);}
.sp-sn.lose{color:var(--dim);}
.sp-sdash{font-size:1.4rem;color:var(--line3);font-weight:600;padding:0 6px;align-self:center;}
.sp-vs{font-family:'Barlow Condensed',sans-serif;font-size:1.15rem;font-weight:800;color:var(--dim2);letter-spacing:3px;}

.sp-status2{font-size:.67rem;font-weight:600;color:var(--dim);margin-top:1px;text-align:center;}
.sp-status2.live{color:var(--red);font-weight:800;}
.sp-status2.soon{color:var(--a1);}

.sp-extras{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:5px;margin-top:5px;}
.sp-tv2{display:inline-flex;align-items:center;gap:3px;font-size:.58rem;font-weight:700;color:var(--blue);background:rgba(41,182,246,.07);border:1px solid rgba(41,182,246,.2);padding:2px 8px;border-radius:5px;}
.sp-venue2{display:inline-flex;align-items:center;gap:3px;font-size:.58rem;color:var(--dim);background:var(--bg3);border:1px solid var(--line);padding:2px 8px;border-radius:5px;}
.sp-odds2{display:inline-flex;align-items:center;gap:3px;font-size:.58rem;color:var(--a3);background:var(--glow2);border:1px solid var(--a2);padding:2px 8px;border-radius:5px;font-weight:700;}

/* Linescore */
.sp-ls-wrap{padding:2px 14px 10px;display:flex;flex-direction:column;gap:3px;}
.sp-ls-row{display:flex;align-items:center;gap:3px;}
.sp-ls-lbl{font-size:.5rem;font-weight:700;color:var(--dim2);width:20px;text-align:center;letter-spacing:.5px;text-transform:uppercase;font-family:'Barlow Condensed',sans-serif;}
.sp-ls-q{background:var(--bg3);border:1px solid var(--line);border-radius:4px;padding:2px 0;min-width:26px;text-align:center;font-size:.58rem;font-weight:700;color:var(--dim);font-family:'Barlow Condensed',sans-serif;}
.sp-ls-q.hd{background:transparent;border-color:transparent;color:var(--dim2);font-size:.48rem;letter-spacing:.8px;}
.sp-ls-q.ot{color:var(--a3);}

/* Standings */
.sp-row{display:flex;align-items:center;gap:10px;background:var(--bg1);border-radius:10px;padding:9px 13px;margin:4px 0;font-size:.83rem;border:1px solid var(--line);transition:border-color .15s;}
.sp-row:hover{border-color:var(--line3);}
.sp-pos{min-width:22px;font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:1rem;color:var(--a1);text-align:center;}
.sp-pos.g{color:var(--a3);}
.sp-sn2{flex:1;font-weight:600;color:var(--txt);}
.sp-stat{color:var(--dim);font-size:.72rem;min-width:40px;text-align:right;}
.sp-stat.hi{color:var(--txt);font-weight:700;}

/* News */
.sp-news{background:var(--bg1);border-radius:10px;padding:11px 14px;margin:6px 0;border:1px solid var(--line);border-left:3px solid var(--a2);}
.sp-news:hover{border-color:var(--line3);}
.sp-news a{color:var(--a1);text-decoration:none;font-size:.88rem;font-weight:700;line-height:1.4;}
.sp-news .meta{font-size:.64rem;color:var(--dim);margin-top:5px;line-height:1.5;}

/* Empty */
.sp-empty{color:var(--dim);font-size:.84rem;padding:22px 16px;text-align:center;border:1px dashed var(--line2);border-radius:12px;margin:10px 0;background:var(--bg1);}

/* Footer */
.sp-ft{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;font-size:.56rem;color:var(--dim2);margin-top:14px;border-top:1px solid var(--line);padding-top:9px;}
.sp-chips{display:flex;gap:5px;flex-wrap:wrap;}
.sp-chip{background:var(--bg2);color:var(--dim);padding:2px 8px;border-radius:10px;border:1px solid var(--line2);font-size:.55rem;}
.sp-brand{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:.7rem;letter-spacing:1.2px;text-transform:uppercase;color:var(--a2);}

@media(max-width:480px){
  .sp-sn{font-size:2rem;} .sp-tname{font-size:.92rem;}
  .sp-body{padding:12px 10px 10px;gap:4px;} .sp-sc-block{min-width:86px;}
  .sp{padding:14px 12px 14px;}
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# SPORT → CSS CLASS  (used in _build_html)
# ─────────────────────────────────────────────────────────────────────────────

_SPORT_CSS: dict[str, str] = {
    "basketball": "sp-basketball",
    "football": "sp-football",
    "hockey": "sp-hockey",
    "baseball": "sp-baseball",
    "racing": "sp-racing",
    "mma": "sp-mma",
    "boxing": "sp-mma",
    "tennis": "sp-tennis",
    "cricket": "sp-other",
    "rugby": "sp-other",
    "rugby-league": "sp-other",
    "australian-football": "sp-other",
}


def _build_html(
    title: str, emoji: str, body: str, sources: list, sport: str = "soccer"
) -> str:
    ts = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    chips = "".join(f'<span class="sp-chip">{s}</span>' for s in dict.fromkeys(sources))
    sport_cls = _SPORT_CSS.get(sport, "")  # soccer = default (no extra class)
    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{_CSS}</style></head><body>"
        f"<div class='sp {sport_cls}'>"
        f"<div class='sp-hd'><h2>{emoji} {title}</h2><time>{ts}</time></div>"
        f"{body}"
        f"<div class='sp-ft'><div class='sp-chips'>{chips}</div>"
        "<span class='sp-brand'>⚡ Sports Hub Pro v11</span></div>"
        "</div></body></html>"
    )


def _pills_html(plains: list) -> str:
    live = sum(1 for p in plains if p.get("state") == "live")
    done = sum(1 for p in plains if p.get("state") == "final")
    soon = sum(1 for p in plains if p.get("state") == "upcoming")
    out = []
    if live:
        out.append(f'<span class="sp-pill live">🔴 {live} Live</span>')
    if done:
        out.append(f'<span class="sp-pill done">✔ {done} Finished</span>')
    if soon:
        out.append(f'<span class="sp-pill soon">📅 {soon} Upcoming</span>')
    return '<div class="sp-pills">' + "".join(out) + "</div>" if out else ""


# ─────────────────────────────────────────────────────────────────────────────
# UTIL HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _extract_score(raw) -> str:
    if isinstance(raw, dict):
        dv = raw.get("displayValue")
        if dv is not None:
            return str(dv)
        v = raw.get("value")
        if v is not None:
            return str(int(v)) if float(v) == int(float(v)) else str(v)
        return ""
    return "" if raw is None else str(raw)


def _fmt_dt(iso: str) -> str:
    if not iso:
        return ""
    iso = iso.strip()
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b · %H:%M UTC")
    except Exception:
        pass
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(iso[: len(fmt)], fmt).strftime(
                "%a %d %b · %H:%M UTC"
            )
        except Exception:
            pass
    return iso


def _fmt_dt_rel(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = (dt.date() - now.date()).days
        time_str = dt.strftime("%H:%M UTC")
        if delta == 0:
            return f"Today · {time_str}"
        if delta == 1:
            return f"Tomorrow · {time_str}"
        if delta == -1:
            return f"Yesterday · {time_str}"
        return dt.strftime("%a %d %b · %H:%M UTC")
    except Exception:
        return _fmt_dt(iso)


def _period(sport: str, p: int) -> str:
    return {
        "basketball": lambda n: f"Q{n}" if n <= 4 else f"OT{n-4}",
        "football": lambda n: f"Q{n}" if n <= 4 else "OT",
        "hockey": lambda n: f"P{n}" if n <= 3 else "OT",
        "baseball": lambda n: f"Inn {n}",
    }.get(sport, lambda n: f"{n}'")(p)


def _logo_espn(sport: str, abbrev: str, sz: int = 36) -> str:
    ns = "soccer" if sport == "soccer" else sport
    url = f"{ESPN_LOGO}/{ns}/{sz}/{abbrev.lower()}.png"
    return f'<img src="{url}" width="{sz}" height="{sz}" onerror="this.style.display=\'none\'">'


def _logo_url(url: str, sz: int = 36) -> str:
    if not url:
        return ""
    return f'<img src="{url}" width="{sz}" height="{sz}" onerror="this.style.display=\'none\'">'


# ─────────────────────────────────────────────────────────────────────────────
# LINESCORE
# ─────────────────────────────────────────────────────────────────────────────


def _build_linescore_html(away_ls: list, home_ls: list) -> str:
    n = max(len(away_ls), len(home_ls))
    if n < 2:
        return ""
    away_vals = [_extract_score(c) for c in away_ls] + [""] * (n - len(away_ls))
    home_vals = [_extract_score(c) for c in home_ls] + [""] * (n - len(home_ls))
    labels = [
        f"Q{i+1}" if i < 4 else ("OT" if n - 4 == 1 else f"OT{i-3}") for i in range(n)
    ]
    hdrs = "".join(f'<span class="sp-ls-q hd">{l}</span>' for l in labels)

    def cells(vals):
        return "".join(
            f'<span class="sp-ls-q{" ot" if i>=4 else ""}">{v or "—"}</span>'
            for i, v in enumerate(vals)
        )

    return (
        f'<div class="sp-ls-row"><span class="sp-ls-lbl"></span>{hdrs}</div>'
        f'<div class="sp-ls-row"><span class="sp-ls-lbl">A</span>{cells(away_vals)}</div>'
        f'<div class="sp-ls-row"><span class="sp-ls-lbl">H</span>{cells(home_vals)}</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# CARD BUILDERS
# ─────────────────────────────────────────────────────────────────────────────


def _espn_card(ev: dict, sport: str):
    """Returns (html_str, plain_dict) — v11 broadcast layout."""
    comps = ev.get("competitions", [{}])[0]
    competitors = comps.get("competitors", [])
    status = ev.get("status", {})
    state = status.get("type", {}).get("state", "pre")
    detail = status.get("type", {}).get("shortDetail", "")
    clock = status.get("displayClock", "")
    period = status.get("period", 0)

    comp_name = (comps.get("league") or {}).get("shortName", "") or (
        comps.get("league") or {}
    ).get("name", "")
    note = ev.get("note", "") or ev.get("notes", "")
    if isinstance(note, list) and note:
        note = note[0].get("headline", "")

    venue_name = (comps.get("venue") or {}).get("fullName", "")
    broadcasts = comps.get("broadcasts", [])
    tv_name = ""
    if broadcasts:
        names = broadcasts[0].get("names", [])
        if names:
            tv_name = names[0]

    odds_line = ""
    odds_list = comps.get("odds", [])
    if odds_list:
        o = odds_list[0]
        odds_line = o.get("details", "") or o.get("overUnder", "")

    if len(competitors) < 2:
        return "", {}

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    def team_info(c):
        t = c.get("team", {})
        name = t.get("shortDisplayName") or t.get("displayName", "TBD")
        abv = t.get("abbreviation", "")
        rec = c.get("records", [{}])[0].get("summary", "") if c.get("records") else ""
        logo = _logo_espn(sport, abv)
        won = bool(c.get("winner"))
        return name, abv, rec, logo, won

    a_name, a_abv, a_rec, a_logo, a_won = team_info(away)
    h_name, h_abv, h_rec, h_logo, h_won = team_info(home)
    aw = _extract_score(away.get("score", ""))
    hm = _extract_score(home.get("score", ""))

    a_cls = "winner" if a_won else ("loser" if (not a_won and h_won) else "")
    h_cls = "winner" if h_won else ("loser" if (not h_won and a_won) else "")
    aw_cls = "win" if a_won else ("lose" if h_won else "")
    hm_cls = "win" if h_won else ("lose" if a_won else "")

    away_ls = away.get("linescores", [])
    home_ls = home.get("linescores", [])
    ls_html = ""
    if sport in ("basketball", "football") and (away_ls or home_ls):
        ls_html = _build_linescore_html(away_ls, home_ls)

    ot_tag = ""
    if state == "post" and period > 4 and sport in ("basketball", "football"):
        ot_tag = " (OT)"

    if state == "in":
        per_str = _period(sport, period)
        if "halftime" in detail.lower():
            per_str = "Halftime"
        badge_html = (
            '<span class="sp-badge2 live"><span class="sp-dot2"></span>LIVE</span>'
        )
        scores_html = f'<div class="sp-scores"><span class="sp-sn">{aw}</span><span class="sp-sdash">—</span><span class="sp-sn">{hm}</span></div>'
        status_html = f'<div class="sp-status2 live">{clock} {per_str}</div>'
        sk = "live"
    elif state == "post":
        badge_html = '<span class="sp-badge2 done">FINAL</span>'
        scores_html = f'<div class="sp-scores"><span class="sp-sn {aw_cls}">{aw}</span><span class="sp-sdash">—</span><span class="sp-sn {hm_cls}">{hm}</span></div>'
        status_html = f'<div class="sp-status2">{detail or ("Final" + ot_tag)}</div>'
        sk = "final"
    else:
        badge_html = '<span class="sp-badge2 soon">UPCOMING</span>'
        scores_html = '<div class="sp-vs">VS</div>'
        status_html = (
            f'<div class="sp-status2 soon">{_fmt_dt_rel(ev.get("date",""))}</div>'
        )
        aw = hm = ""
        sk = "upcoming"

    extras = ""
    if tv_name:
        extras += f'<span class="sp-tv2">📺 {tv_name}</span>'
    if venue_name and sk == "upcoming":
        extras += f'<span class="sp-venue2">📍 {venue_name}</span>'
    if odds_line and sk == "upcoming":
        extras += f'<span class="sp-odds2">📊 {odds_line}</span>'
    extras_html = f'<div class="sp-extras">{extras}</div>' if extras else ""

    meta_left = note if note else comp_name
    meta_cls = "sp-note-txt" if note else "sp-comp-name"
    comp_extra = (
        f'<span class="sp-comp-name">{comp_name}</span>' if (note and comp_name) else ""
    )
    meta_html = (
        f'<div class="sp-meta"><span class="{meta_cls}">{meta_left}</span>'
        f"{comp_extra}</div>"
    )

    def team_block(name, rec, logo, cls, align):
        align_cls = f"sp-team2 {align} {cls}".strip()
        rec_html = f'<div class="sp-trec">{rec}</div>' if rec else ""
        return (
            f'<div class="{align_cls}">{logo}'
            f'<div><div class="sp-tname">{name}</div>'
            f"{rec_html}"
            f"</div></div>"
        )

    away_block = team_block(a_name, a_rec, a_logo, a_cls, "")
    home_block = team_block(h_name, h_rec, h_logo, h_cls, "r")
    center_html = (
        f'<div class="sp-sc-block">{badge_html}{scores_html}'
        f"{status_html}{extras_html}</div>"
    )
    body_html = f'<div class="sp-body">{away_block}{center_html}{home_block}</div>'
    ls_wrap = f'<div class="sp-ls-wrap">{ls_html}</div>' if ls_html else ""
    game_cls = "sp-game live-card" if sk == "live" else "sp-game"
    html = f'<div class="{game_cls}">{meta_html}{body_html}{ls_wrap}</div>'

    plain = {
        "home": h_name,
        "away": a_name,
        "score": f"{aw}–{hm}" if (aw or hm) else "vs",
        "state": sk,
        "time": _fmt_dt(ev.get("date", "")),
        "comp": comp_name,
        "venue": venue_name,
        "tv": tv_name,
        "src": "ESPN",
    }
    return html, plain


def _tsdb_card(ev: dict):
    home = ev.get("strHomeTeam", "?")
    away = ev.get("strAwayTeam", "?")
    h_sc = ev.get("intHomeScore")
    a_sc = ev.get("intAwayScore")
    date_s = (ev.get("dateEvent", "") + " " + (ev.get("strTime") or "")).strip()
    status = (ev.get("strStatus") or "").strip()
    comp = ev.get("strLeague", "")
    rnd = ev.get("intRound", "")
    h_logo = ev.get("strHomeTeamBadge", "")
    a_logo = ev.get("strAwayTeamBadge", "")

    fin = status in ("FT", "AET", "Pen.", "PEN", "AP", "After Pens", "After ET")
    live = status in ("Live", "HT", "1H", "2H", "ET", "P") and not fin

    if live:
        badge_h = (
            '<span class="sp-badge2 live"><span class="sp-dot2"></span>LIVE</span>'
        )
        scores_h = f'<div class="sp-scores"><span class="sp-sn">{a_sc}</span><span class="sp-sdash">—</span><span class="sp-sn">{h_sc}</span></div>'
        status_h = f'<div class="sp-status2 live">{status}</div>'
        sk = "live"
    elif fin and h_sc is not None:
        a_w = (
            int(a_sc) > int(h_sc)
            if str(a_sc).isdigit() and str(h_sc).isdigit()
            else False
        )
        h_w = (
            int(h_sc) > int(a_sc)
            if str(a_sc).isdigit() and str(h_sc).isdigit()
            else False
        )
        badge_h = '<span class="sp-badge2 done">FINAL</span>'
        scores_h = f'<div class="sp-scores"><span class="sp-sn {("win" if a_w else "lose" if h_w else "")}">{a_sc}</span><span class="sp-sdash">—</span><span class="sp-sn {("win" if h_w else "lose" if a_w else "")}">{h_sc}</span></div>'
        status_h = f'<div class="sp-status2">{status or "FT"}</div>'
        sk = "final"
    else:
        badge_h = '<span class="sp-badge2 soon">UPCOMING</span>'
        scores_h = '<div class="sp-vs">VS</div>'
        status_h = f'<div class="sp-status2 soon">{_fmt_dt(date_s)}</div>'
        sk = "upcoming"

    rstr = f"Rd {rnd} · " if rnd else ""
    meta_h = (
        f'<div class="sp-meta"><span class="sp-comp-name">{rstr}{comp}</span>'
        f'<span class="sp-chip" style="font-size:.52rem;padding:1px 6px">TSDB</span></div>'
    )

    def tblk(name, logo_url, align):
        logo_h = _logo_url(logo_url) if logo_url else ""
        return f'<div class="sp-team2 {align}">{logo_h}<div><div class="sp-tname">{name}</div></div></div>'

    center_h = f'<div class="sp-sc-block">{badge_h}{scores_h}{status_h}</div>'
    html = (
        f'<div class="sp-game">{meta_h}'
        f'<div class="sp-body">{tblk(away, a_logo, "")}{center_h}{tblk(home, h_logo, "r")}</div>'
        f"</div>"
    )
    plain = {
        "home": home,
        "away": away,
        "score": f"{a_sc}–{h_sc}" if sk != "upcoming" else "vs",
        "state": sk,
        "time": _fmt_dt(date_s),
        "comp": comp,
        "src": "TSDB",
    }
    return html, plain


def _nhl_card(game: dict):
    gs = game.get("gameState", "")
    gt = game.get("gameType", 2)
    away = game.get("awayTeam", {})
    home = game.get("homeTeam", {})
    a_name = away.get("commonName", {}).get("default", away.get("abbrev", "?"))
    h_name = home.get("commonName", {}).get("default", home.get("abbrev", "?"))
    a_sc = away.get("score", "")
    h_sc = home.get("score", "")
    start = game.get("startTimeUTC", "")
    period = game.get("periodDescriptor", {}).get("number", 0)
    ptype = game.get("periodDescriptor", {}).get("periodType", "")
    clock = game.get("clock", {}).get("timeRemaining", "")
    series = game.get("seriesSummary", {}).get("seriesAbbrev", "") if gt == 3 else ""
    a_logo = away.get("darkLogo", away.get("logo", ""))
    h_logo = home.get("darkLogo", home.get("logo", ""))
    gtype_str = "Playoffs" if gt == 3 else ("Preseason" if gt == 1 else "NHL")
    comp_str = f"{gtype_str}{(' · ' + series) if series else ''}"

    if gs in ("LIVE", "CRIT"):
        per_str = "OT" if (ptype in ("OT", "SO") or period > 3) else f"P{period}"
        badge_h = (
            '<span class="sp-badge2 live"><span class="sp-dot2"></span>LIVE</span>'
        )
        scores_h = f'<div class="sp-scores"><span class="sp-sn">{a_sc}</span><span class="sp-sdash">—</span><span class="sp-sn">{h_sc}</span></div>'
        status_h = f'<div class="sp-status2 live">{clock} {per_str}</div>'
        sk = "live"
    elif gs in ("FINAL", "OFF", "OVER"):
        ot_s = " (OT)" if ptype == "OT" else (" (SO)" if ptype == "SO" else "")
        try:
            a_w = int(a_sc) > int(h_sc)
            h_w = int(h_sc) > int(a_sc)
        except Exception:
            a_w = h_w = False
        badge_h = '<span class="sp-badge2 done">FINAL</span>'
        scores_h = f'<div class="sp-scores"><span class="sp-sn {("win" if a_w else "lose" if h_w else "")}">{a_sc}</span><span class="sp-sdash">—</span><span class="sp-sn {("win" if h_w else "lose" if a_w else "")}">{h_sc}</span></div>'
        status_h = f'<div class="sp-status2">Final{ot_s}</div>'
        sk = "final"
    else:
        badge_h = '<span class="sp-badge2 soon">UPCOMING</span>'
        scores_h = '<div class="sp-vs">VS</div>'
        status_h = f'<div class="sp-status2 soon">{_fmt_dt_rel(start)}</div>'
        a_sc = h_sc = ""
        sk = "upcoming"

    meta_h = (
        f'<div class="sp-meta"><span class="sp-comp-name">{comp_str}</span>'
        f'<span class="sp-chip" style="font-size:.52rem;padding:1px 6px">NHL API</span></div>'
    )

    def tblk(name, logo_url, align):
        logo_h = _logo_url(logo_url) if logo_url else ""
        return f'<div class="sp-team2 {align}"><div>{logo_h}</div><div><div class="sp-tname">{name}</div></div></div>'

    center_h = f'<div class="sp-sc-block">{badge_h}{scores_h}{status_h}</div>'
    html = (
        f'<div class="sp-game">{meta_h}'
        f'<div class="sp-body">{tblk(a_name, a_logo, "")}{center_h}{tblk(h_name, h_logo, "r")}</div>'
        f"</div>"
    )
    plain = {
        "home": h_name,
        "away": a_name,
        "score": f"{a_sc}–{h_sc}" if sk != "upcoming" else "vs",
        "state": sk,
        "time": _fmt_dt(start),
        "comp": "NHL",
        "src": "NHL",
    }
    return html, plain


def _mlb_card(game: dict):
    status_code = game.get("status", {}).get("abstractGameCode", "P")
    status_detail = game.get("status", {}).get("detailedState", "Scheduled")
    teams = game.get("teams", {})
    a_team = teams.get("away", {}).get("team", {})
    h_team = teams.get("home", {}).get("team", {})
    a_name = a_team.get("name", "?")
    h_name = h_team.get("name", "?")
    a_sc = teams.get("away", {}).get("score", "")
    h_sc = teams.get("home", {}).get("score", "")
    start = game.get("gameDate", "")
    inning = game.get("linescore", {}).get("currentInning", 0)
    inning_half = game.get("linescore", {}).get("inningHalf", "")
    series = game.get("seriesDescription", "")

    if status_code == "L":
        inn_str = f"{inning_half[:3]} {inning}" if inning else "Live"
        badge_h = (
            '<span class="sp-badge2 live"><span class="sp-dot2"></span>LIVE</span>'
        )
        scores_h = f'<div class="sp-scores"><span class="sp-sn">{a_sc}</span><span class="sp-sdash">—</span><span class="sp-sn">{h_sc}</span></div>'
        status_h = f'<div class="sp-status2 live">{inn_str}</div>'
        sk = "live"
    elif status_code == "F":
        try:
            a_w = int(a_sc) > int(h_sc)
            h_w = int(h_sc) > int(a_sc)
        except Exception:
            a_w = h_w = False
        badge_h = '<span class="sp-badge2 done">FINAL</span>'
        scores_h = f'<div class="sp-scores"><span class="sp-sn {("win" if a_w else "lose" if h_w else "")}">{a_sc}</span><span class="sp-sdash">—</span><span class="sp-sn {("win" if h_w else "lose" if a_w else "")}">{h_sc}</span></div>'
        status_h = f'<div class="sp-status2">{status_detail}</div>'
        sk = "final"
    else:
        badge_h = '<span class="sp-badge2 soon">UPCOMING</span>'
        scores_h = '<div class="sp-vs">VS</div>'
        status_h = f'<div class="sp-status2 soon">{_fmt_dt_rel(start)}</div>'
        sk = "upcoming"

    comp_str = f"MLB{(' · ' + series) if series else ''}"
    meta_h = (
        f'<div class="sp-meta"><span class="sp-comp-name">{comp_str}</span>'
        f'<span class="sp-chip" style="font-size:.52rem;padding:1px 6px">MLB API</span></div>'
    )

    def tblk(name, align):
        return f'<div class="sp-team2 {align}"><div><div class="sp-tname">{name}</div></div></div>'

    center_h = f'<div class="sp-sc-block">{badge_h}{scores_h}{status_h}</div>'
    html = (
        f'<div class="sp-game">{meta_h}'
        f'<div class="sp-body">{tblk(a_name, "")}{center_h}{tblk(h_name, "r")}</div>'
        f"</div>"
    )
    plain = {
        "home": h_name,
        "away": a_name,
        "score": f"{a_sc}–{h_sc}" if sk != "upcoming" else "vs",
        "state": sk,
        "time": _fmt_dt(start),
        "comp": "MLB",
        "src": "MLB",
    }
    return html, plain


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────────────────────────────────────


async def _get(url: str, params: dict = None, extra_headers: dict = None) -> dict:
    ck = _ck(url, str(params))
    if (c := _cget(ck)) is not None:
        return c
    hdrs = dict(_HDRS)
    if extra_headers:
        hdrs.update(extra_headers)
    r = await _client().get(url, params=params or {}, headers=hdrs)
    r.raise_for_status()
    data = r.json()
    _cset(ck, data, 90)
    return data


async def _espn_scoreboard(
    sport: str, slug: str, dates: str = None, dates_range: str = "", enable: str = ""
) -> dict:
    """
    dates       – single YYYYMMDD
    dates_range – YYYYMMDD-YYYYMMDD
    enable      – comma-separated extras, e.g. 'linescores,odds'
    """
    params: dict = {"limit": 200}
    if dates_range:
        params["dates"] = dates_range
    elif dates:
        params["dates"] = dates
    if enable:
        params["enable"] = enable
    return await _get(f"{ESPN_BASE}/{sport}/{slug}/scoreboard", params)


async def _espn_soccer_team_schedule(team_id: int, fixture: bool = False) -> dict:
    url = f"{ESPN_BASE}/soccer/all/teams/{team_id}/schedule"
    params = {"fixture": "true"} if fixture else {}
    ck = _ck("soccer_all_sched", team_id, fixture)
    if (c := _cget(ck)) is not None:
        return c
    r = await _client().get(url, params=params, headers=_HDRS)
    r.raise_for_status()
    data = r.json()
    _cset(ck, data, 120)
    return data


async def _espn_team_schedule(
    sport: str, slug: str, team_id: int, season: int = None
) -> dict:
    """Team schedule for non-soccer sports. Uses ?enable=linescores for richer data."""
    params = {"limit": 100, "enable": "linescores"}
    if season:
        params["season"] = season
    url = f"{ESPN_BASE}/{sport}/{slug}/teams/{team_id}/schedule"
    ck = _ck("team_sched", sport, slug, team_id, season)
    if (c := _cget(ck)) is not None:
        return c
    r = await _client().get(url, params=params, headers=_HDRS)
    r.raise_for_status()
    data = r.json()
    _cset(ck, data, 90)
    return data


async def _espn_scoreboard_team_filter(
    sport: str, slug: str, team_id: int, start_d: str, end_d: str
) -> list:
    """
    v11 FIX: Fetch scoreboard for a date range and filter events to those
    involving team_id. Used as upcoming-game fallback for NBA/NFL/etc.
    Returns list of (hc, pd) tuples.
    """
    dr = f"{start_d}-{end_d}"
    cards = []
    try:
        data = await _espn_scoreboard(
            sport, slug, dates_range=dr, enable="linescores,odds"
        )
        now_utc = _now_utc()
        for ev in data.get("events", []):
            comps_c = ev.get("competitions", [{}])[0]
            is_team = any(
                str(c.get("id", "")) == str(team_id)
                or str(c.get("team", {}).get("id", "")) == str(team_id)
                for c in comps_c.get("competitors", [])
            )
            if not is_team:
                continue
            try:
                ev_dt = datetime.fromisoformat(
                    ev.get("date", "").replace("Z", "+00:00")
                )
                if ev_dt < now_utc:
                    continue  # only future
            except Exception:
                pass
            hc, pd = _espn_card(ev, sport)
            if hc and pd["state"] == "upcoming":
                cards.append((hc, pd))
    except Exception:
        pass
    return cards


async def _nhl_score_date(date: str) -> dict:
    return await _get(f"{NHL_BASE}/score/{date}")


async def _nhl_team_schedule_season(abbrev: str, season: str) -> dict:
    return await _get(f"{NHL_BASE}/club-schedule-season/{abbrev}/{season}")


async def _nhl_standings() -> dict:
    return await _get(f"{NHL_BASE}/standings/now")


async def _mlb_schedule(
    date: str = None, team_id: int = None, start: str = None, end: str = None
) -> dict:
    params: dict = {"sportId": 1, "hydrate": "linescore"}
    if date:
        params["date"] = date
    elif start and end:
        params["startDate"] = start
        params["endDate"] = end
    if team_id:
        params["teamId"] = team_id
    return await _get(f"{MLB_BASE}/schedule", params)


async def _tsdb_get(path: str, params: dict = None) -> dict:
    ck = _ck("tsdb", path, str(params))
    if (c := _cget(ck)) is not None:
        return c
    r = await _client().get(f"{TSDB_BASE}/{path}", params=params or {}, headers=_HDRS)
    r.raise_for_status()
    data = r.json()
    _cset(ck, data, 120)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# RESOLVERS & HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _is_upcoming(q: str) -> bool:
    return any(
        k in q.lower()
        for k in [
            "next",
            "upcoming",
            "schedule",
            "fixture",
            "fixtures",
            "when",
            "future",
            "calendar",
            "coming",
            "preview",
            "soon",
            "ahead",
            "plan",
            "next game",
        ]
    )


def _is_past(q: str) -> bool:
    return any(
        k in q.lower()
        for k in [
            "last",
            "recent",
            "result",
            "results",
            "past",
            "previous",
            "played",
            "history",
            "yesterday",
            "finished",
        ]
    )


def _resolve_league(query: str) -> Optional[str]:
    q = query.lower().strip()
    if q in LEAGUES:
        return q
    for key, info in LEAGUES.items():
        if info[2].lower() in q:
            return key
    shortcuts = {
        "premier league": "epl",
        "la liga": "laliga",
        "champions league": "ucl",
        "serie a": "seriea",
        "ligue 1": "ligue1",
        "copa del rey": "coparey",
        "fa cup": "facup",
        "europa league": "uel",
        "conference league": "uecl",
        "formula one": "f1",
        "formula 1": "f1",
        "american football": "nfl",
        "world cup": "wc",
        "nations league": "nations",
        "copa libertadores": "copalibert",
        "2. bundesliga": "bundesliga2",
        "segunda": "la2",
        "wwe": "wwe",
        "wrestling": "wwe",
        "aew": "aew",
        "all elite wrestling": "aew",
        "nascar": "nascar",
        "indycar": "indycar",
        "indy car": "indycar",
        "league of legends": "lol",
        "lol esports": "lol",
        "counter strike": "csgo",
        "counter-strike": "csgo",
        "cs2": "csgo",
        "csgo": "csgo",
        "dota 2": "dota2",
        "dota2": "dota2",
        "overwatch league": "overwatch",
        "overwatch": "overwatch",
        "valorant": "valorant",
        "rocket league": "rl",
        "esports": "lol",
    }
    for kw, lk in shortcuts.items():
        if kw in q:
            return lk
    for frag, lk in sorted(TEAM_LEAGUE_MAP.items(), key=lambda x: -len(x[0])):
        if frag in q:
            return lk
    return None


def _resolve_team(query: str) -> Optional[str]:
    q = query.lower().strip()
    for frag in sorted(ESPN_TEAMS.keys(), key=len, reverse=True):
        if frag in q:
            return frag
    for frag in sorted(TEAM_LEAGUE_MAP.keys(), key=len, reverse=True):
        if frag in q:
            return frag
    return None


def _resolve_group(query: str) -> Optional[list]:
    q = query.lower().strip()
    for kw, keys in SPORT_GROUP_MAP.items():
        if kw in q:
            return keys
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _current_season(sport_slug: str) -> int:
    """
    v11 FIX: NBA/NHL season is labeled by ENDING year in ESPN.
    2025-26 season (Oct 2025 → Jun 2026) = ESPN label "2026".

    Old (wrong): m>=9 → y, else y-1
    New (correct): m>=10 → y+1 (new season just started, ends next year)
                   m<10  → y   (current year = ending year of ongoing season)

    Soccer: season starts ~July, labeled by starting year → y if m>=7 else y-1
    NFL:    labeled by starting year → y if m>=8 else y-1
    MLB:    labeled by starting year → y if m>=3 else y-1
    """
    now = _now_utc()
    y, m = now.year, now.month
    if sport_slug in ("basketball", "hockey"):
        # Season runs Oct–Jun, ESPN uses ending-year label
        return y + 1 if m >= 10 else y
    if sport_slug == "soccer":
        return y if m >= 7 else y - 1
    if sport_slug == "football":
        return y if m >= 8 else y - 1
    if sport_slug == "baseball":
        return y if m >= 3 else y - 1
    return y


def _nhl_season_str() -> str:
    """Return NHL season in YYYYYYYY format e.g. '20252026'.
    v11: ending_year = _current_season("hockey"), start = ending-1."""
    ending = _current_season("hockey")  # e.g. 2026 for 2025-26 season
    return f"{ending-1}{ending}"  # "20252026"


async def _emit(fn, msg: str, done: bool = False):
    if fn:
        await fn({"type": "status", "data": {"description": msg, "done": done}})


def _patch_ev_state(ev: dict, now_utc: datetime) -> dict:
    """Force state='post' for events whose date has already passed."""
    try:
        raw = ev.get("date", "")
        if not raw:
            return ev
        ev_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        tp = ev.setdefault("status", {}).setdefault("type", {})
        if ev_dt < now_utc and tp.get("state", "pre") == "pre":
            tp.update(
                {
                    "state": "post",
                    "name": "STATUS_FINAL",
                    "shortDetail": "FT",
                    "description": "Final",
                    "completed": True,
                }
            )
    except Exception:
        pass
    return ev


# ─────────────────────────────────────────────────────────────────────────────
# TEAM CARDS HELPER
# ─────────────────────────────────────────────────────────────────────────────


def _add_team_cards(
    html_parts,
    plain_list,
    past_cards,
    future_cards,
    want_past,
    want_future,
    max_recent,
    max_upcoming,
):
    recent = past_cards[-max_recent:] if past_cards else []
    upcoming = future_cards[:max_upcoming] if future_cards else []
    if recent:
        html_parts.append('<div class="sp-day">🏁 Recent Results</div>')
        for hc, pd in recent:
            html_parts.append(hc)
            plain_list.append(pd)
    if want_future and upcoming:
        html_parts.append('<div class="sp-day">📅 Upcoming Fixtures</div>')
        for hc, pd in upcoming:
            html_parts.append(hc)
            plain_list.append(pd)


# ─────────────────────────────────────────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────────────────────────────────────────


class Tools:
    class Valves(BaseModel):
        max_games: int = Field(
            default=20, description="Max games shown per team/league."
        )
        recent_games: int = Field(
            default=5, description="Recent results shown for a team."
        )
        upcoming_games: int = Field(
            default=8, description="Upcoming fixtures shown for a team."
        )
        default_leagues: str = Field(
            default="nba,epl,nfl", description="Leagues shown when no sport specified."
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── 1 · SCORES / SCHEDULE ────────────────────────────────────────────────

    async def get_scores(
        self,
        query: str = "",
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get live scores, team schedules (past + upcoming), or league scoreboards
        for ANY sport, team or league. Returns a beautiful inline HTML card.

        v11 improvements:
          • NBA/NFL team upcoming games now always shown (scoreboard range fallback)
          • Fixed season year for basketball/hockey (was fetching WRONG season)
          • Sport-specific vivid color themes (NBA=blue/orange, NFL=navy/gold, etc.)
          • Upcoming league queries use date range (not day-by-day probing)
          • Odds/lines shown on upcoming game cards

        Examples:
          "Trail Blazers next games" / "Lakers schedule"
          "NBA scores today" / "Real Madrid upcoming"
          "NHL scores" / "Yankees schedule"

        :param query: Team name, league, sport, or "today".
        :param date: Optional YYYYMMDD date override.
        :return: Rendered HTML card.
        """
        ee = __event_emitter__
        q = query.lower().strip()
        want_past = _is_past(query)
        want_future = _is_upcoming(query) or (not want_past)
        team_frag = _resolve_team(query)
        league_key = _resolve_league(query)
        sport_group = _resolve_group(query)

        html_parts: list[str] = []
        plain_list: list[dict] = []
        sources: list[str] = []
        now_utc = _now_utc()
        sport_for_theme = "soccer"  # default; overridden per path

        # ── PATH A: Specific team ────────────────────────────────────────────
        if team_frag:
            espn_entry = ESPN_TEAMS.get(team_frag)
            league_of_team = (
                espn_entry[0] if espn_entry else TEAM_LEAGUE_MAP.get(team_frag, "")
            )
            sport_s = (
                LEAGUES.get(league_of_team, ("soccer",))[0]
                if league_of_team
                else "soccer"
            )
            emu = LEAGUES.get(league_of_team, ("", "", "", "🏟️"))[3] or "🏟️"
            sport_for_theme = sport_s

            # ── NHL ──────────────────────────────────────────────────────────
            if league_of_team == "nhl" or team_frag in NHL_ABBREVS:
                abbrev = NHL_ABBREVS.get(team_frag)
                if abbrev:
                    await _emit(ee, f"🏒 Fetching {team_frag.title()} from NHL API…")
                    try:
                        season_str = _nhl_season_str()
                        data = await _nhl_team_schedule_season(abbrev, season_str)
                        games = data.get("games", [])
                        past_cards, future_cards = [], []
                        for g in games:
                            hc, pd = _nhl_card(g)
                            if not hc:
                                continue
                            if g.get("gameState", "FUT") in ("FINAL", "OFF", "OVER"):
                                past_cards.append((hc, pd))
                            else:
                                future_cards.append((hc, pd))
                        _add_team_cards(
                            html_parts,
                            plain_list,
                            past_cards,
                            future_cards,
                            want_past,
                            want_future,
                            self.valves.recent_games,
                            self.valves.upcoming_games,
                        )
                        if plain_list:
                            sources.append("NHL Official")
                    except Exception as ex:
                        await _emit(ee, f"NHL API failed ({ex}), trying ESPN…")

            # ── MLB ──────────────────────────────────────────────────────────
            elif league_of_team == "mlb" or team_frag in MLB_TEAM_IDS:
                mlb_id = MLB_TEAM_IDS.get(team_frag)
                if mlb_id:
                    await _emit(ee, f"⚾ Fetching {team_frag.title()} from MLB API…")
                    try:
                        y = _current_season("baseball")
                        data = await _mlb_schedule(
                            team_id=mlb_id, start=f"{y}-01-01", end=f"{y}-12-31"
                        )
                        all_games = [
                            g for d in data.get("dates", []) for g in d.get("games", [])
                        ]
                        past_cards, future_cards = [], []
                        for g in all_games:
                            hc, pd = _mlb_card(g)
                            if not hc:
                                continue
                            if pd["state"] == "final":
                                past_cards.append((hc, pd))
                            else:
                                future_cards.append((hc, pd))
                        _add_team_cards(
                            html_parts,
                            plain_list,
                            past_cards,
                            future_cards,
                            want_past,
                            want_future,
                            self.valves.recent_games,
                            self.valves.upcoming_games,
                        )
                        if plain_list:
                            sources.append("MLB Official")
                    except Exception as ex:
                        await _emit(ee, f"MLB API failed ({ex}), trying ESPN…")

            # ── Soccer ───────────────────────────────────────────────────────
            elif sport_s == "soccer" and espn_entry:
                team_id = espn_entry[1]
                await _emit(
                    ee, f"⚽ Fetching {team_frag.title()} all-competition schedule…"
                )
                try:
                    past_cards, future_cards = [], []
                    seen_ids: set = set()

                    # Step 1: Past results via scoreboard date-range (has real scores)
                    league_of_team_key = espn_entry[0]
                    league_info = LEAGUES.get(league_of_team_key, ())
                    league_slug_sb = league_info[1] if league_info else ""
                    sb_leagues = [league_slug_sb] if league_slug_sb else []
                    for extra in [
                        "uefa.champions",
                        "esp.copa_del_rey",
                        "fifa.world.clubs",
                        "uefa.super_cup",
                    ]:
                        if extra not in sb_leagues:
                            sb_leagues.append(extra)

                    start_d = (now_utc - timedelta(days=45)).strftime("%Y%m%d")
                    end_d = now_utc.strftime("%Y%m%d")
                    dr = f"{start_d}-{end_d}"

                    for slug_try in sb_leagues[:4]:
                        try:
                            sb = await _espn_scoreboard(
                                "soccer",
                                slug_try,
                                dates_range=dr,
                                enable="linescores,odds",
                            )
                            for ev in sb.get("events", []):
                                ev_id = ev.get("id", "")
                                if ev_id in seen_ids:
                                    continue
                                comps_c = ev.get("competitions", [{}])[0]
                                is_team = any(
                                    str(c.get("id", "")) == str(team_id)
                                    or str(c.get("team", {}).get("id", ""))
                                    == str(team_id)
                                    for c in comps_c.get("competitors", [])
                                )
                                if not is_team:
                                    continue
                                seen_ids.add(ev_id)
                                hc, pd = _espn_card(ev, "soccer")
                                if hc and pd["state"] in ("final", "live"):
                                    past_cards.append((hc, pd))
                        except Exception:
                            pass

                    # Step 2: Past fallback via schedule endpoint (no scores, patches state)
                    if not past_cards:
                        try:
                            past_data = await _espn_soccer_team_schedule(
                                team_id, fixture=False
                            )
                            for ev in past_data.get("events") or []:
                                ev_id = ev.get("id", "")
                                if ev_id in seen_ids:
                                    continue
                                ev = _patch_ev_state(ev, now_utc)
                                hc, pd = _espn_card(ev, "soccer")
                                if not hc:
                                    continue
                                seen_ids.add(ev_id)
                                try:
                                    ev_dt = datetime.fromisoformat(
                                        ev.get("date", "").replace("Z", "+00:00")
                                    )
                                    if ev_dt < now_utc:
                                        past_cards.append((hc, pd))
                                except Exception:
                                    if pd["state"] in ("final", "live"):
                                        past_cards.append((hc, pd))
                        except Exception:
                            pass

                    # Step 3: Upcoming via schedule?fixture=true
                    try:
                        future_data = await _espn_soccer_team_schedule(
                            team_id, fixture=True
                        )
                        for ev in future_data.get("events") or []:
                            ev_id = ev.get("id", "")
                            if ev_id in seen_ids:
                                continue
                            try:
                                ev_dt = datetime.fromisoformat(
                                    ev.get("date", "").replace("Z", "+00:00")
                                )
                                is_future = ev_dt >= now_utc
                            except Exception:
                                is_future = True
                            if not is_future:
                                ev = _patch_ev_state(ev, now_utc)
                                hc, pd = _espn_card(ev, "soccer")
                                if hc:
                                    seen_ids.add(ev_id)
                                    past_cards.append((hc, pd))
                            else:
                                hc, pd = _espn_card(ev, "soccer")
                                if hc and pd["state"] == "upcoming":
                                    seen_ids.add(ev_id)
                                    future_cards.append((hc, pd))
                    except Exception:
                        pass

                    await _emit(
                        ee,
                        f"✅ {len(past_cards)} results, {len(future_cards)} upcoming loaded.",
                    )
                    _add_team_cards(
                        html_parts,
                        plain_list,
                        past_cards,
                        future_cards,
                        want_past,
                        want_future,
                        self.valves.recent_games,
                        self.valves.upcoming_games,
                    )
                    if plain_list:
                        sources.append("ESPN")
                except Exception as ex:
                    await _emit(ee, f"ESPN soccer schedule failed ({ex}), trying TSDB…")

            # ── Other sports (NBA, NFL, etc.) ─────────────────────────────────
            elif espn_entry:
                lk, team_id = espn_entry
                info = LEAGUES.get(lk, ("soccer", "esp.1", "?", "⚽"))
                sport_s2, slug = info[0], info[1]
                season = _current_season(sport_s2)

                await _emit(
                    ee, f"🔍 Fetching {team_frag.title()} schedule (season {season})…"
                )
                try:
                    data = await _espn_team_schedule(sport_s2, slug, team_id, season)
                    evts = data.get("events") or []
                    past_cards, future_cards = [], []
                    for ev in evts:
                        ev = _patch_ev_state(ev, now_utc)
                        hc, pd = _espn_card(ev, sport_s2)
                        if not hc:
                            continue
                        try:
                            ev_dt = datetime.fromisoformat(
                                ev.get("date", "").replace("Z", "+00:00")
                            )
                            is_past_ev = ev_dt < now_utc
                        except Exception:
                            is_past_ev = pd.get("state") in ("final", "live")
                        if is_past_ev:
                            past_cards.append((hc, pd))
                        else:
                            future_cards.append((hc, pd))

                    # v11 FIX: if ESPN team schedule returned no upcoming games,
                    # fall back to scoreboard date-range and filter by team.
                    if not future_cards and want_future:
                        await _emit(
                            ee,
                            f"📅 Team schedule had no upcoming games — checking scoreboard…",
                        )
                        start_d = now_utc.strftime("%Y%m%d")
                        end_d = (now_utc + timedelta(days=30)).strftime("%Y%m%d")
                        future_cards = await _espn_scoreboard_team_filter(
                            sport_s2, slug, team_id, start_d, end_d
                        )
                        if future_cards:
                            await _emit(
                                ee,
                                f"✅ Found {len(future_cards)} upcoming via scoreboard range.",
                            )

                    _add_team_cards(
                        html_parts,
                        plain_list,
                        past_cards,
                        future_cards,
                        want_past,
                        want_future,
                        self.valves.recent_games,
                        self.valves.upcoming_games,
                    )
                    if plain_list:
                        sources.append("ESPN")
                except Exception as ex:
                    await _emit(ee, f"ESPN schedule failed ({ex}), trying TSDB…")

            # ── Universal TSDB fallback ───────────────────────────────────────
            if not plain_list:
                await _emit(ee, f"📅 Trying TheSportsDB for {team_frag.title()}…")
                try:
                    search = await _tsdb_get("searchteams.php", {"t": team_frag})
                    teams = search.get("teams") or []
                    if teams:
                        tid = int(teams[0]["idTeam"])
                        nxt_data = await _tsdb_get("eventsnext.php", {"id": tid})
                        lst_data = await _tsdb_get("eventslast.php", {"id": tid})
                        past_cards = [
                            _tsdb_card(e)
                            for e in (lst_data.get("results") or [])[
                                : self.valves.recent_games
                            ]
                        ]
                        future_cards = [
                            _tsdb_card(e)
                            for e in (nxt_data.get("events") or [])[
                                : self.valves.upcoming_games
                            ]
                        ]
                        if past_cards:
                            html_parts.append(
                                '<div class="sp-day">🏁 Recent Results</div>'
                            )
                            for hc, pd in past_cards:
                                html_parts.append(hc)
                                plain_list.append(pd)
                        if future_cards:
                            html_parts.append(
                                '<div class="sp-day">📅 Upcoming Fixtures</div>'
                            )
                            for hc, pd in future_cards:
                                html_parts.append(hc)
                                plain_list.append(pd)
                        if plain_list:
                            sources.append("TheSportsDB")
                except Exception:
                    pass

            if not html_parts:
                html_parts.append(
                    f'<div class="sp-empty">No schedule data found for <b>{team_frag.title()}</b>. '
                    f"The team may be in off-season or try a different name.</div>"
                )
            title = f"{team_frag.title()} Schedule"

        # ── PATH B: NHL league ────────────────────────────────────────────────
        elif league_key == "nhl" or (sport_group and "nhl" in sport_group):
            sport_for_theme = "hockey"
            await _emit(ee, "🏒 Fetching NHL scores from NHL API…")
            fetch_date = date or now_utc.strftime("%Y-%m-%d")
            emu = "🏒"
            try:
                score_data = await _nhl_score_date(fetch_date)
                for g in score_data.get("games", []):
                    hc, pd = _nhl_card(g)
                    if hc:
                        html_parts.append(hc)
                        plain_list.append(pd)
                if plain_list:
                    sources.append("NHL Official")
            except Exception as ex:
                await _emit(ee, f"NHL score API failed ({ex}), trying ESPN…")
            if not plain_list:
                try:
                    d = date or now_utc.strftime("%Y%m%d")
                    data = await _espn_scoreboard("hockey", "nhl", d)
                    for ev in data.get("events", []):
                        hc, pd = _espn_card(ev, "hockey")
                        if hc:
                            html_parts.append(hc)
                            plain_list.append(pd)
                    if plain_list:
                        sources.append("ESPN")
                except Exception:
                    pass
            title = "NHL Scores"

        # ── PATH C: MLB league ────────────────────────────────────────────────
        elif league_key == "mlb" or (sport_group and "mlb" in sport_group):
            sport_for_theme = "baseball"
            await _emit(ee, "⚾ Fetching MLB scores from MLB API…")
            fetch_date_iso = date or now_utc.strftime("%Y-%m-%d")
            if date and len(date) == 8:
                fetch_date_iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            emu = "⚾"
            try:
                data = await _mlb_schedule(date=fetch_date_iso)
                for d_entry in data.get("dates", []):
                    for g in d_entry.get("games", []):
                        hc, pd = _mlb_card(g)
                        if hc:
                            html_parts.append(hc)
                            plain_list.append(pd)
                if plain_list:
                    sources.append("MLB Official")
            except Exception as ex:
                await _emit(ee, f"MLB API failed ({ex}), trying ESPN…")
            if not plain_list:
                try:
                    d = date or now_utc.strftime("%Y%m%d")
                    data = await _espn_scoreboard("baseball", "mlb", d)
                    for ev in data.get("events", []):
                        hc, pd = _espn_card(ev, "baseball")
                        if hc:
                            html_parts.append(hc)
                            plain_list.append(pd)
                    if plain_list:
                        sources.append("ESPN")
                except Exception:
                    pass
            title = "MLB Scores"

        # ── PATH D: League / sport / default — ESPN scoreboard ───────────────
        else:
            lk_list = (
                [league_key]
                if league_key
                else (
                    sport_group
                    if sport_group
                    else (
                        [
                            k.strip()
                            for k in self.valves.default_leagues.split(",")
                            if k.strip()
                        ]
                        if not q
                        else ["nba", "epl", "nfl"]
                    )
                )
            )

            # v11: determine smart date range for scoreboard fetch
            fetch_date_ymd = date or now_utc.strftime("%Y%m%d")

            async def _fetch_one(lk: str):
                if lk not in LEAGUES:
                    return lk, [], [], []
                info = LEAGUES[lk]
                sport_s = info[0]
                slug = info[1]
                tsdb_lid = info[4] if len(info) > 4 else None
                sec_h, sec_p, lk_src = [], [], []

                try:
                    if _is_upcoming(query):
                        # v11: use 14-day range for upcoming (one shot, much faster)
                        start_r = (now_utc + timedelta(days=1)).strftime("%Y%m%d")
                        end_r = (now_utc + timedelta(days=14)).strftime("%Y%m%d")
                        data = await _espn_scoreboard(
                            sport_s,
                            slug,
                            dates_range=f"{start_r}-{end_r}",
                            enable="linescores,odds",
                        )
                        for ev in data.get("events", [])[: self.valves.max_games]:
                            hc, pd = _espn_card(ev, sport_s)
                            if hc:
                                sec_h.append(hc)
                                sec_p.append(pd)
                    else:
                        # Try today ±1 day until we find games
                        dates_to_try = [fetch_date_ymd]
                        if not _is_past(query):
                            dates_to_try.insert(
                                0, (now_utc - timedelta(days=1)).strftime("%Y%m%d")
                            )
                            dates_to_try.append(
                                (now_utc + timedelta(days=1)).strftime("%Y%m%d")
                            )
                        for d_str in dates_to_try:
                            if sec_h:
                                break
                            data = await _espn_scoreboard(
                                sport_s, slug, d_str, enable="linescores,odds"
                            )
                            for ev in data.get("events", []):
                                if len(sec_h) >= self.valves.max_games:
                                    break
                                hc, pd = _espn_card(ev, sport_s)
                                if hc:
                                    sec_h.append(hc)
                                    sec_p.append(pd)
                    if sec_h:
                        lk_src.append("ESPN")
                except Exception:
                    pass

                # TSDB fallback
                if not sec_h and tsdb_lid:
                    try:
                        today_iso = now_utc.strftime("%Y-%m-%d")
                        ts_sport = {
                            "soccer": "Soccer",
                            "basketball": "Basketball",
                            "football": "American Football",
                            "hockey": "Ice Hockey",
                            "baseball": "Baseball",
                            "racing": "Motorsport",
                            "mma": "MMA",
                        }.get(sport_s, "Soccer")
                        day_data = await _tsdb_get(
                            "eventsday.php", {"d": today_iso, "s": ts_sport}
                        )
                        filtered = [
                            e
                            for e in (day_data.get("events") or [])
                            if str(e.get("idLeague", "")) == str(tsdb_lid)
                        ]
                        if not filtered:
                            nxt = await _tsdb_get(
                                "eventsnextleague.php", {"id": tsdb_lid}
                            )
                            filtered = (nxt.get("events") or [])[
                                : self.valves.max_games
                            ]
                        for e in filtered[: self.valves.max_games]:
                            hc, pd = _tsdb_card(e)
                            sec_h.append(hc)
                            sec_p.append(pd)
                        if sec_h:
                            lk_src.append("TheSportsDB")
                    except Exception:
                        pass

                return lk, sec_h, sec_p, lk_src

            await _emit(ee, f"⚡ Fetching {len(lk_list)} league(s) in parallel…")
            results = await asyncio.gather(*[_fetch_one(lk) for lk in lk_list])

            for lk, sec_h, sec_p, lk_src in results:
                if lk not in LEAGUES:
                    continue
                info = LEAGUES[lk]
                name, emoji = info[2], info[3]
                if sec_h:
                    if len(lk_list) > 1:
                        html_parts.append(f'<div class="sp-sec">{emoji} {name}</div>')
                    html_parts.extend(sec_h)
                    plain_list.extend(sec_p)
                    sources.extend(lk_src)
                elif len(lk_list) == 1:
                    html_parts.append(
                        f'<div class="sp-empty">No {name} games found. '
                        f'Try "next {name} matches" or a specific team.</div>'
                    )

            if league_key:
                i = LEAGUES[league_key]
                title = f"{i[2]} {'Schedule' if want_future else 'Scores'}"
                emu = i[3]
                sport_for_theme = LEAGUES[league_key][0]
            elif sport_group:
                title = "Scores & Schedule"
                emu = LEAGUES.get(sport_group[0], ("", "", "", "🏟️"))[3]
                sport_for_theme = LEAGUES.get(sport_group[0], ("soccer",))[0]
            else:
                title = "Scores & Schedule"
                emu = "🏟️"

        # ── RENDER ───────────────────────────────────────────────────────────
        if not html_parts:
            msg = f'No results found for "{query}". Try a different team, league, or date.'
            await _emit(ee, msg, done=True)
            return msg

        sources = list(dict.fromkeys(sources))
        body = _pills_html(plain_list) + "".join(html_parts)
        html_doc = _build_html(title, emu, body, sources, sport=sport_for_theme)
        await _emit(ee, f"✅ {len(plain_list)} events loaded.", done=True)
        return HTMLResponse(content=html_doc, headers={"content-disposition": "inline"})

    # ── 2 · STANDINGS ────────────────────────────────────────────────────────

    async def get_standings(
        self,
        query: str = "nba",
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get league standings / table for any sport.
        NHL standings from official NHL API. All others from ESPN.

        Examples: "Premier League table", "NBA standings", "NHL standings",
                  "La Liga tabla", "NFL standings", "MLB standings"

        :param query: League or sport name.
        :return: Rendered HTML standings card.
        """
        ee = __event_emitter__
        lk = _resolve_league(query) or "nba"
        info = LEAGUES[lk]
        sport_s, slug, name, emoji = info[0], info[1], info[2], info[3]

        # NHL: use official API
        if lk == "nhl":
            await _emit(ee, "🏒 Fetching NHL standings from NHL API…")
            try:
                data = await _nhl_standings()
                standings = data.get("standings", [])
                rows_h: list[str] = []
                cur_div = ""
                for pos, team in enumerate(standings, 1):
                    div = team.get("divisionName", "")
                    if div != cur_div:
                        rows_h.append(f'<div class="sp-sec">{div}</div>')
                        cur_div = div
                    tname = team.get("teamName", {}).get("default", "?")
                    logo = team.get("teamLogo", "")
                    w, l = team.get("wins", 0), team.get("losses", 0)
                    ot = team.get("otLosses", 0)
                    pts = team.get("points", 0)
                    rec = f"{w}–{l}–{ot}  {pts}pts"
                    pcls = "g" if pos <= 3 else ""
                    logo_h = _logo_url(logo, 22)
                    rows_h.append(
                        f'<div class="sp-row"><div class="sp-pos {pcls}">{pos}</div>{logo_h}'
                        f'<div class="sp-sn2">{tname}</div>'
                        f'<div class="sp-stat hi">{rec}</div></div>'
                    )
                if rows_h:
                    html_doc = _build_html(
                        "NHL Standings",
                        "🏒",
                        "".join(rows_h),
                        ["NHL Official"],
                        sport="hockey",
                    )
                    await _emit(ee, "✅ NHL standings loaded.", done=True)
                    return HTMLResponse(
                        content=html_doc, headers={"content-disposition": "inline"}
                    )
            except Exception as ex:
                await _emit(ee, f"NHL standings API failed ({ex}), trying ESPN…")

        ck = _ck("standings_html_v11", lk)
        if cached := _cget(ck):
            await _emit(ee, f"✅ {name} standings (cached).", done=True)
            return HTMLResponse(
                content=cached, headers={"content-disposition": "inline"}
            )

        try:
            await _emit(ee, f"📊 Fetching {name} standings…")
            r = await _client().get(
                f"{ESPN_BASE}/{sport_s}/{slug}/standings", headers=_HDRS
            )
            r.raise_for_status()
            data = r.json()

            rows_h: list[str] = []
            groups = data.get("children") or [data]
            for group in groups[:8]:
                gname = group.get("name") or group.get("abbreviation") or ""
                entries = group.get("standings", {}).get("entries", []) or group.get(
                    "entries", []
                )
                if not entries:
                    for child in group.get("children", []):
                        entries += child.get("standings", {}).get("entries", [])
                if not entries:
                    continue
                if gname:
                    rows_h.append(f'<div class="sp-sec">{gname}</div>')
                for pos, entry in enumerate(entries, 1):
                    team = entry.get("team", {})
                    tname = team.get("displayName", team.get("name", "?"))
                    abv = team.get("abbreviation", "")
                    logo = _logo_espn(sport_s, abv, 22)
                    stats = {
                        s.get("shortDisplayName", s.get("name", "")): s.get(
                            "displayValue", ""
                        )
                        for s in entry.get("stats", [])
                    }
                    w = stats.get("W") or stats.get("wins") or ""
                    l = stats.get("L") or stats.get("losses") or ""
                    d = stats.get("D") or stats.get("ties") or ""
                    pts = (
                        stats.get("pts")
                        or stats.get("PTS")
                        or stats.get("points")
                        or ""
                    )
                    gb = stats.get("GB") or stats.get("gamesBehind") or ""
                    rec = (
                        f"{w}–{d}–{l}"
                        if (w and d and l)
                        else (f"{w}–{l}" if w and l else "")
                    )
                    if rec and pts:
                        rec += f"  {pts}pts"
                    elif pts:
                        rec = f"{pts}pts"
                    if gb:
                        rec += f"  GB {gb}"
                    pcls = "g" if pos <= 3 else ""
                    rows_h.append(
                        f'<div class="sp-row"><div class="sp-pos {pcls}">{pos}</div>{logo}'
                        f'<div class="sp-sn2">{tname}</div>'
                        f'<div class="sp-stat hi">{rec}</div></div>'
                    )
                if len(rows_h) > 150:
                    break

            if not rows_h:
                msg = f"Could not parse {name} standings."
                await _emit(ee, msg, done=True)
                return msg

            html_doc = _build_html(
                f"{name} Standings", emoji, "".join(rows_h), ["ESPN"], sport=sport_s
            )
            _cset(ck, html_doc, 300)
            await _emit(ee, f"✅ {name} standings loaded.", done=True)
            return HTMLResponse(
                content=html_doc, headers={"content-disposition": "inline"}
            )

        except Exception as exc:
            err = f"❌ Could not fetch {name} standings: {exc}"
            await _emit(ee, err, done=True)
            return err

    # ── 3 · NEWS ─────────────────────────────────────────────────────────────

    async def get_sports_news(
        self,
        query: str = "nba",
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get latest sports news, headlines, transfers and articles.

        Examples: "Barcelona news", "Premier League latest", "NBA news",
                  "F1 updates", "NHL trades", "MLB news"

        :param query: League, sport, or team name.
        :return: Rendered HTML news card.
        """
        ee = __event_emitter__
        lk = _resolve_league(query) or "nba"
        info = LEAGUES[lk]
        sport_s, slug, name, emoji = info[0], info[1], info[2], info[3]

        ck = _ck("news_html_v11", lk)
        if cached := _cget(ck):
            await _emit(ee, f"✅ {name} news (cached).", done=True)
            return HTMLResponse(
                content=cached, headers={"content-disposition": "inline"}
            )

        try:
            await _emit(ee, f"📰 Fetching {name} news…")
            r = await _client().get(
                f"{ESPN_BASE}/{sport_s}/{slug}/news",
                params={"limit": 15},
                headers=_HDRS,
            )
            r.raise_for_status()
            articles = r.json().get("articles", [])

            rows_h: list[str] = []
            for a in articles[:12]:
                headline = a.get("headline", "")
                link = a.get("links", {}).get("web", {}).get("href", "#")
                pub = a.get("published", "")
                desc = a.get("description", "")
                snippet = (desc[:140] + "…") if len(desc) > 140 else desc
                ts_str = _fmt_dt(pub) if pub else ""
                rows_h.append(
                    f'<div class="sp-news">'
                    f'<a href="{link}" target="_blank" rel="noopener">{headline}</a>'
                    f'<div class="meta">{ts_str}{"<br>"+snippet if snippet else ""}</div>'
                    f"</div>"
                )

            if not rows_h:
                msg = f"No news found for {name}."
                await _emit(ee, msg, done=True)
                return msg

            html_doc = _build_html(
                f"{name} News", emoji, "".join(rows_h), ["ESPN"], sport=sport_s
            )
            _cset(ck, html_doc, 300)
            await _emit(ee, f"✅ {len(rows_h)} articles loaded.", done=True)
            return HTMLResponse(
                content=html_doc, headers={"content-disposition": "inline"}
            )

        except Exception as exc:
            err = f"❌ Could not fetch {name} news: {exc}"
            await _emit(ee, err, done=True)
            return err
