"""
title: Weather
description: Beautiful real-time weather cards with current conditions, hourly forecast, and 7-day outlook — powered by Open-Meteo. Zero API key required.
author: ichrist
author_url: https://github.com/iChristGit/OpenWebui-Tools
funding_url: https://github.com/iChristGit/OpenWebui-Tools
version: 1.2.0
license: MIT
requirements: httpx
"""

import httpx
from datetime import datetime
from typing import Awaitable, Callable, Optional
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# WMO Weather Code → human label + emoji
# ---------------------------------------------------------------------------

WMO = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Icy fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    61: ("Slight rain", "🌧️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "❄️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Slight showers", "🌦️"),
    81: ("Moderate showers", "🌧️"),
    82: ("Violent showers", "⛈️"),
    85: ("Snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm + hail", "⛈️"),
    99: ("Thunderstorm + heavy hail", "⛈️"),
}


def _wmo(code: int):
    return WMO.get(code, ("Unknown", "🌡️"))


def _wind_dir(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


def _uv_label(uv: float) -> tuple:
    if uv < 3:
        return "Low", "#4caf50"
    if uv < 6:
        return "Moderate", "#ffeb3b"
    if uv < 8:
        return "High", "#ff9800"
    if uv < 11:
        return "Very High", "#f44336"
    return "Extreme", "#9c27b0"


GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def _geocode(location: str) -> dict:
    with httpx.Client(timeout=10) as client:
        r = client.get(
            GEO_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results")
        if not results:
            raise ValueError(f"Location not found: '{location}'")
        return results[0]


def _fetch_weather(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "is_day",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "surface_pressure",
            "visibility",
            "uv_index",
        ],
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
        ],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "uv_index_max",
            "sunrise",
            "sunset",
        ],
        "timezone": "auto",
        "forecast_days": 7,
    }
    with httpx.Client(timeout=10) as client:
        r = client.get(WEATHER_URL, params=params)
        r.raise_for_status()
        return r.json()


def _build_card(geo: dict, w: dict, unit: str) -> str:
    c = w["current"]
    daily = w["daily"]
    hourly = w["hourly"]
    tz = w.get("timezone_abbreviation", "")

    temp_unit = "°C" if unit == "celsius" else "°F"
    speed_unit = "km/h"

    temp = c["temperature_2m"]
    feels = c["apparent_temperature"]
    humidity = c["relative_humidity_2m"]
    wind_spd = c["wind_speed_10m"]
    wind_dir = _wind_dir(c["wind_direction_10m"])
    pressure = c["surface_pressure"]
    precip = c["precipitation"]
    code = c["weather_code"]
    is_day = c.get("is_day", 1)
    uv = c.get("uv_index", 0) or 0
    visibility = c.get("visibility", None)

    label, icon = _wmo(code)
    uv_lbl, uv_color = _uv_label(uv)

    city = geo.get("name", "Unknown")
    country = geo.get("country", "")
    region = geo.get("admin1", "")
    seen = set()
    parts = []
    for p in [city, region, country]:
        key = p.strip().lower()
        if p and key not in seen:
            seen.add(key)
            parts.append(p)
    location_str = ", ".join(parts)

    if not is_day:
        bg = "linear-gradient(135deg, #0f0c29, #1a1a4e, #24243e)"
        text_color = "#e8eaf6"
    elif code in (0, 1):
        bg = "linear-gradient(135deg, #1a6dce, #38b6ff, #74d7ff)"
        text_color = "#fff"
    elif code in (2, 3):
        bg = "linear-gradient(135deg, #4a5568, #718096, #a0aec0)"
        text_color = "#fff"
    elif code >= 61:
        bg = "linear-gradient(135deg, #2c3e50, #3d5a73, #4a7fa5)"
        text_color = "#e8f4f8"
    else:
        bg = "linear-gradient(135deg, #1a6dce, #38b6ff, #74d7ff)"
        text_color = "#fff"

    sunrise = daily["sunrise"][0].split("T")[1] if daily.get("sunrise") else "N/A"
    sunset = daily["sunset"][0].split("T")[1] if daily.get("sunset") else "N/A"

    forecast_items = []
    for i in range(min(7, len(daily["time"]))):
        _, d_icon = _wmo(daily["weather_code"][i])
        d_max = round(daily["temperature_2m_max"][i])
        d_min = round(daily["temperature_2m_min"][i])
        d_rain = daily["precipitation_probability_max"][i] or 0
        date_obj = datetime.strptime(daily["time"][i], "%Y-%m-%d")
        d_name = "Today" if i == 0 else date_obj.strftime("%a")
        forecast_items.append(f"""
            <div class="day-item">
              <div class="day-name">{d_name}</div>
              <div class="day-icon">{d_icon}</div>
              <div class="day-temps">
                <span class="day-max">{d_max}{temp_unit}</span>
                <span class="day-min">{d_min}{temp_unit}</span>
              </div>
              <div class="day-rain">💧{d_rain}%</div>
            </div>""")
    forecast_html = "".join(forecast_items)

    now_hour = datetime.now().hour
    hourly_items = []
    shown = 0
    for i, time_str in enumerate(hourly["time"]):
        h = int(time_str.split("T")[1].split(":")[0])
        day_str = time_str.split("T")[0]
        today_str = datetime.now().strftime("%Y-%m-%d")
        if day_str != today_str:
            continue
        if h < now_hour:
            continue
        if shown >= 8:
            break
        h_temp = round(hourly["temperature_2m"][i])
        h_rain = hourly["precipitation_probability"][i] or 0
        _, h_icon = _wmo(hourly["weather_code"][i])
        hourly_items.append(f"""
            <div class="hour-item">
              <div class="hour-label">{h:02d}:00</div>
              <div class="hour-icon">{h_icon}</div>
              <div class="hour-temp">{h_temp}{temp_unit}</div>
              <div class="hour-rain">💧{h_rain}%</div>
            </div>""")
        shown += 1
    hourly_html = "".join(hourly_items)

    vis_str = f"{int(visibility / 1000)} km" if visibility else "N/A"
    now_str = datetime.now().strftime("%A, %d %b %Y · %H:%M")

    # Full HTML document — same pattern as the working podcast tool
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{
  background:transparent;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  padding:6px;
}}
.wx-card {{
  background: {bg};
  color: {text_color};
  border-radius: 20px;
  padding: 24px;
  max-width: 620px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  overflow: hidden;
}}
.wx-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }}
.wx-location {{ font-size: 1.1rem; font-weight: 700; opacity: 0.95; }}
.wx-date {{ font-size: 0.72rem; opacity: 0.7; margin-top: 3px; }}
.wx-main {{ display: flex; align-items: center; gap: 12px; margin: 16px 0 8px; }}
.wx-icon {{ font-size: 4.5rem; line-height: 1; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.3)); }}
.wx-temp {{ font-size: 3.8rem; font-weight: 800; line-height: 1; letter-spacing: -2px; }}
.wx-feels {{ font-size: 0.8rem; opacity: 0.75; margin-top: 4px; }}
.wx-condition {{ font-size: 1.05rem; font-weight: 600; opacity: 0.9; margin: 6px 0 16px; }}
.wx-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 14px 0; }}
.wx-stat {{ background: rgba(255,255,255,0.15); border-radius: 12px; padding: 10px 12px; backdrop-filter: blur(10px); }}
.wx-stat-label {{ font-size: 0.65rem; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.wx-stat-val {{ font-size: 0.95rem; font-weight: 700; }}
.wx-divider {{ border: none; border-top: 1px solid rgba(255,255,255,0.15); margin: 16px 0; }}
.wx-section-title {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; opacity: 0.65; margin-bottom: 10px; }}
.wx-hourly {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: none; }}
.wx-hourly::-webkit-scrollbar {{ display: none; }}
.hour-item {{ background: rgba(255,255,255,0.15); border-radius: 12px; padding: 10px; text-align: center; min-width: 62px; backdrop-filter: blur(10px); flex-shrink: 0; }}
.hour-label {{ font-size: 0.68rem; opacity: 0.7; }}
.hour-icon {{ font-size: 1.3rem; margin: 4px 0; }}
.hour-temp {{ font-size: 0.85rem; font-weight: 700; }}
.hour-rain {{ font-size: 0.65rem; opacity: 0.7; margin-top: 2px; }}
.wx-forecast {{ display: flex; flex-direction: column; gap: 6px; }}
.day-item {{ display: flex; align-items: center; background: rgba(255,255,255,0.12); border-radius: 10px; padding: 8px 14px; backdrop-filter: blur(10px); }}
.day-name {{ min-width: 48px; font-size: 0.82rem; font-weight: 600; opacity: 0.85; }}
.day-icon {{ font-size: 1.2rem; min-width: 36px; text-align: center; }}
.day-temps {{ display: flex; gap: 10px; flex: 1; justify-content: flex-end; font-size: 0.85rem; }}
.day-max {{ font-weight: 700; }}
.day-min {{ opacity: 0.6; }}
.day-rain {{ min-width: 44px; text-align: right; font-size: 0.72rem; opacity: 0.7; }}
.wx-sun {{ display: flex; gap: 16px; font-size: 0.82rem; opacity: 0.8; margin-top: 10px; }}
.wx-footer {{ font-size: 0.62rem; opacity: 0.4; text-align: right; margin-top: 14px; }}
</style>
</head>
<body>
<div class="wx-card">
  <div class="wx-header">
    <div>
      <div class="wx-location">📍 {location_str}</div>
      <div class="wx-date">{now_str} {tz}</div>
    </div>
  </div>
  <div class="wx-main">
    <div class="wx-icon">{icon}</div>
    <div class="wx-temp-block">
      <div class="wx-temp">{round(temp)}{temp_unit}</div>
      <div class="wx-feels">Feels like {round(feels)}{temp_unit}</div>
    </div>
  </div>
  <div class="wx-condition">{label}</div>
  <div class="wx-stats">
    <div class="wx-stat"><div class="wx-stat-label">💧 Humidity</div><div class="wx-stat-val">{humidity}%</div></div>
    <div class="wx-stat"><div class="wx-stat-label">💨 Wind</div><div class="wx-stat-val">{round(wind_spd)} {speed_unit} {wind_dir}</div></div>
    <div class="wx-stat"><div class="wx-stat-label">🌡️ Pressure</div><div class="wx-stat-val">{round(pressure)} hPa</div></div>
    <div class="wx-stat"><div class="wx-stat-label">☁️ Precip</div><div class="wx-stat-val">{precip} mm</div></div>
    <div class="wx-stat"><div class="wx-stat-label">👁️ Visibility</div><div class="wx-stat-val">{vis_str}</div></div>
    <div class="wx-stat"><div class="wx-stat-label">🔆 UV Index</div><div class="wx-stat-val" style="color:{uv_color}">{round(uv)} · {uv_lbl}</div></div>
  </div>
  <div class="wx-sun">
    <span>🌅 Sunrise {sunrise}</span>
    <span>🌇 Sunset {sunset}</span>
  </div>
  <hr class="wx-divider">
  <div class="wx-section-title">Today — Hourly</div>
  <div class="wx-hourly">{hourly_html}</div>
  <hr class="wx-divider">
  <div class="wx-section-title">7-Day Forecast</div>
  <div class="wx-forecast">{forecast_html}</div>
  <div class="wx-footer">Powered by Open-Meteo · No API key required</div>
</div>
</body>
</html>"""


async def _emit(emitter, desc: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": desc, "done": done}})


class Tools:
    class Valves(BaseModel):
        default_unit: str = Field(
            default="celsius",
            description="Temperature unit: 'celsius' or 'fahrenheit'.",
        )
        default_location: str = Field(
            default="",
            description="Default location if none is provided (e.g. 'London').",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def get_weather(
        self,
        location: Optional[str] = None,
        unit: Optional[str] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> "HTMLResponse | str":
        """
        Get a beautiful real-time weather card for any city or location in the world.
        Shows current conditions, hourly forecast for today, and a full 7-day outlook.
        Use this whenever the user asks about weather, temperature, forecast, rain,
        wind, or climate for any place.

        IMPORTANT: Only set `location` if the user EXPLICITLY names a city or place
        in their message (e.g. "weather in Paris", "London weather"). If the user just
        says "weather", "what's the weather", or similar with no place, leave `location`
        as null — a default_location valve is configured and will be used instead.
        Do NOT infer or guess the location from system context, IP, or conversation history.

        :param location: City explicitly typed by the user. Null/omit if not stated.
        :param unit: 'celsius' or 'fahrenheit'. Null to use default.
        :return: Rendered HTML weather card.
        """
        loc = location or self.valves.default_location
        u = (unit or self.valves.default_unit).lower()
        if u not in ("celsius", "fahrenheit"):
            u = "celsius"

        if not loc:
            msg = "Please provide a location, e.g. 'weather in London'."
            await _emit(__event_emitter__, msg, done=True)
            return msg

        try:
            await _emit(__event_emitter__, f"📍 Looking up {loc}…")
            geo = _geocode(loc)

            await _emit(__event_emitter__, f"🌤️ Fetching weather for {geo['name']}…")
            weather = _fetch_weather(geo["latitude"], geo["longitude"])

            if u == "fahrenheit":
                c = weather["current"]
                for key in ("temperature_2m", "apparent_temperature"):
                    c[key] = round(c[key] * 9 / 5 + 32, 1)
                for i in range(len(weather["hourly"]["temperature_2m"])):
                    weather["hourly"]["temperature_2m"][i] = round(
                        weather["hourly"]["temperature_2m"][i] * 9 / 5 + 32, 1
                    )
                for key in ("temperature_2m_max", "temperature_2m_min"):
                    weather["daily"][key] = [
                        round(t * 9 / 5 + 32, 1) for t in weather["daily"][key]
                    ]

            html = _build_card(geo, weather, u)

            await _emit(
                __event_emitter__, f"✅ Weather loaded for {geo['name']}.", done=True
            )

            # ✅ THE FIX: return HTMLResponse directly, exactly like the podcast tool.
            # Open WebUI renders this inline. A plain string return goes to the LLM instead.
            return HTMLResponse(content=html, headers={"content-disposition": "inline"})

        except ValueError as ve:
            msg = f"❌ {ve}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
        except Exception as exc:
            msg = f"❌ Could not fetch weather: {exc}"
            await _emit(__event_emitter__, msg, done=True)
            return msg
