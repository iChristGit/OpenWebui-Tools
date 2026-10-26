"""
title: Message Loading Indicator
description: Message Loading Indicator + Thinking Studio. Adds settings under Settings > Interface so each user picks how a reply shows it is loading (100 styles plus a Random option), which icon sits beside the Thinking header, and replaces the bland 'Thinking...' text with rotating thinking words (Claude-style, dev, playful, hacker, zen, custom...) with animated effects, fonts, colors, speed and an optional live timer. Published into /static/loader.js through the Shared Assets Protocol, so it coexists with Theme Designer Pro and any other plugin using it.
author: ichrist (adapted from G30 function)
author_url: https://openwebui.com/u/ichrist
funding_url:
version: 2.4.0
license: MIT
required_open_webui_version: 0.11.0
"""

import hashlib
import json as _json

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


import asyncio
import logging
import uuid
from typing import Any, Optional

from open_webui.utils.json_codec import JSONCodec

ASSET_KEY = "message-loading-indicator"  # fixed, used for asset_register too

# ===========================================================================
# Live reload broadcast
# ---------------------------------------------------------------------------
# Each load publishes over Redis; a peer whose cached code differs from the
# database re-executes it. register(app) is yours and must be idempotent; gate
# each producer on reload_active(app).
# ===========================================================================
RELOAD_STATE_ATTR = "_owui_live_reload"  # {key: {active, exec_id, listener}}
RELOAD_EXEC_ID = uuid.uuid4().hex  # new on every exec of this source
# Open WebUI executes each function as module "function_<id>", or on newer
# builds "function_<id>_<32 hex digits>"; the id is what is left of either.
RELOAD_FUNCTION_ID = __name__.removeprefix("function_")
if (
    len(RELOAD_FUNCTION_ID) > 33
    and RELOAD_FUNCTION_ID[-33] == "_"
    and all(c in "0123456789abcdef" for c in RELOAD_FUNCTION_ID[-32:])
):
    RELOAD_FUNCTION_ID = RELOAD_FUNCTION_ID[:-33]

reload_log = logging.getLogger("owui-live-reload")
# asyncio only keeps weak references to tasks.
reload_tasks: set = set()


def reload_state(app: Any) -> dict:
    registry = getattr(app.state, RELOAD_STATE_ATTR, None)
    if not isinstance(registry, dict):
        registry = {}
        app.state.__setattr__(RELOAD_STATE_ATTR, registry)
    return registry.setdefault(ASSET_KEY, {})


def reload_active(app: Any) -> bool:
    return bool(reload_state(app).get("active"))


def reload_channel() -> str:
    from open_webui.env import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}:live-reload:{ASSET_KEY}"


def reload_mark_loaded(app: Any) -> None:
    register(app)
    state = reload_state(app)
    state["active"] = True
    state["exec_id"] = RELOAD_EXEC_ID


async def reload_publish(app: Any, active: bool) -> None:
    redis = getattr(app.state, "redis", None)
    if redis is None:
        return
    try:
        await redis.publish(reload_channel(), JSONCodec.dumps({"active": active}))
    except Exception as e:
        reload_log.warning("[%s] publish failed: %s", ASSET_KEY, type(e).__name__)


async def reload_ensure_listener(app: Any) -> None:
    state = reload_state(app)
    if state.get("listener") is not None:
        return
    redis = getattr(app.state, "redis", None)
    if redis is None:
        return

    from types import SimpleNamespace

    from open_webui.models.functions import Functions
    from open_webui.utils.plugin import (
        get_function_module_from_cache,
        get_functions_cache,
    )

    # Mark before awaiting so a concurrent event() can't double-subscribe.
    state["listener"] = True
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe(reload_channel())
    except Exception as e:
        state["listener"] = None
        reload_log.warning("[%s] subscribe failed: %s", ASSET_KEY, type(e).__name__)
        return

    async def listen():
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                if not JSONCodec.loads(message["data"])["active"]:
                    state["active"] = False
                    continue
                was_active = state.get("active")
                # Enable broadcasts arrive before is_active commits; bootstrap trusts this flag.
                state["active"] = True
                context = SimpleNamespace(app=app)
                if not was_active:
                    # Force a fresh exec so its bootstrap registers again.
                    get_functions_cache(context).pop(RELOAD_FUNCTION_ID, None)
                try:
                    function_module, _, _ = await get_function_module_from_cache(
                        context, RELOAD_FUNCTION_ID
                    )
                    # Peers never see a valves save; re-read them like Open WebUI's dispatch does.
                    if hasattr(function_module, "Valves"):
                        valves = await Functions.get_function_valves_by_id(
                            RELOAD_FUNCTION_ID
                        )
                        function_module.valves = function_module.Valves(
                            **(valves or {})
                        )
                except Exception as e:
                    reload_log.warning(
                        "[%s] reload from db failed: %s", ASSET_KEY, type(e).__name__
                    )
        except Exception as e:
            reload_log.warning("[%s] listener stopped: %s", ASSET_KEY, type(e).__name__)

    state["listener"] = asyncio.create_task(listen())


def reload_bootstrap() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def bootstrap():
        try:
            from open_webui.main import app
            from open_webui.models.functions import Functions

            own = await Functions.get_function_by_id(RELOAD_FUNCTION_ID)
            # Loading a disabled function (e.g. for its valves) must not switch it on.
            if own is None or not (own.is_active or reload_active(app)):
                return
            reload_mark_loaded(app)
            await reload_ensure_listener(app)
            await reload_publish(app, True)
        except Exception as e:
            reload_log.warning("[%s] bootstrap failed: %s", ASSET_KEY, type(e).__name__)

    task = loop.create_task(bootstrap())
    reload_tasks.add(task)
    task.add_done_callback(reload_tasks.discard)


async def reload_on_event(
    app: Any, event: Optional[dict], event_name: Optional[str]
) -> None:
    await reload_ensure_listener(app)
    state = reload_state(app)

    is_own = ((event or {}).get("subject") or {}).get("id") == RELOAD_FUNCTION_ID
    if is_own and event_name == "function.disable_started":
        state["active"] = False
        await reload_publish(app, False)
        return
    if is_own and event_name == "function.valves_updated":
        await reload_publish(app, True)

    current = state.get("active") and state.get("exec_id") == RELOAD_EXEC_ID
    if current and event_name != "system.startup.completed":
        return
    reload_mark_loaded(app)
    await reload_publish(app, True)


# =========================== end live reload block =========================


import hashlib
from pathlib import Path
from typing import Any

# ===========================================================================
# Shared static-asset registry
# --- KEEP BYTE-IDENTICAL IN EVERY PLUGIN THAT USES IT ----------------------
# ---------------------------------------------------------------------------
# Each plugin publishes a fragment into one app.state registry and the route
# composes them per request, so load order is irrelevant. Per-process: each
# container serves what it has loaded.
#
# Contract:
#   * ASSET_REGISTRY_ATTR, ASSET_ROUTE_ATTR, the entry shape and the paths are
#     the interop surface. The route owner's copy serves everyone.
#   * `key` must be a module-level constant, or a re-exec adds a second entry.
#   * Lower `order` composes first (default 0). Never encode priority in the key.
#   * Producers run on the event loop for every request, 304s included: return
#     a prebuilt string, no I/O, no locks.
#   * Return "" to withdraw. A deleted plugin never sees its own deletion, so
#     disable it first.
#   * Inline fragments only: <script src> / @import lands after hydration.
# ===========================================================================
LOADER_PATH = "/static/loader.js"
CUSTOM_CSS_PATH = "/static/custom.css"
SHARED_ASSET_TYPES = {
    LOADER_PATH: "application/javascript; charset=utf-8",
    CUSTOM_CSS_PATH: "text/css; charset=utf-8",
}
ASSET_REGISTRY_ATTR = "_owui_static_fragments"  # {path: {key: entry}}
ASSET_ROUTE_ATTR = "_owui_shared_asset"  # set to the path the route serves
ASSET_IMPL_ATTR = "_owui_shared_asset_impl"  # implementation version of the route
# Bump on any behaviour change: the newest copy takes over the route.
ASSET_IMPL_VERSION = 4

# Warn once per (path, key, exception type): compose runs on every page load.
_ASSET_WARNED: set = set()


def asset_fragments(app: Any, path: str) -> dict:
    registry = getattr(app.state, ASSET_REGISTRY_ATTR, None)
    if not isinstance(registry, dict):
        registry = {}
        app.state.__setattr__(ASSET_REGISTRY_ATTR, registry)
    bucket = registry.get(path)
    if not isinstance(bucket, dict):
        bucket = {}
        registry[path] = bucket
    return bucket


def asset_sort_key(item):
    """(order, key); a non-int order falls back to 0 so it cannot break sorted()."""
    key, entry = item
    try:
        order = int(entry.get("order", 0))
    except (TypeError, ValueError):
        order = 0
    return (order, key)


def asset_strip_block(content: str, start_marker: str, end_marker: str) -> str:
    """Remove every marker-wrapped block, leaving other content untouched."""
    while start_marker in content:
        start = content.find(start_marker)
        end = content.find(end_marker, start)
        if end == -1:
            # No end marker: the block was appended last, so drop to EOF.
            content = content[:start]
            break
        end += len(end_marker)
        if content[end : end + 1] == "\n":
            end += 1
        content = content[:start] + content[end:]
    return content


def asset_compose(app: Any, path: str) -> str:
    """Disk file plus every registered fragment, in (order, key) order."""
    import logging

    try:
        from open_webui.env import STATIC_DIR

        target = Path(STATIC_DIR) / path.rsplit("/", 1)[-1]
        body = (
            ""
            if (target.is_symlink() or not target.is_file())
            else target.read_text(encoding="utf-8")
        )
    except Exception:
        body = ""

    ordered = sorted(asset_fragments(app, path).items(), key=asset_sort_key)
    # Strip first: an older file-writing build may have left a block on disk.
    for _key, entry in ordered:
        body = asset_strip_block(body, entry["start"], entry["end"])
    body = body.rstrip()

    for key, entry in ordered:
        try:
            block = (entry["js"]() or "").strip()
        except Exception as exc:
            mark = (path, key, type(exc).__name__)
            if mark not in _ASSET_WARNED:
                if len(_ASSET_WARNED) > 256:
                    _ASSET_WARNED.clear()
                _ASSET_WARNED.add(mark)
                logging.getLogger("owui-shared-assets").warning(
                    "fragment %r failed for %s - it will be omitted",
                    key,
                    path,
                    exc_info=True,
                )
            continue
        if block:
            body = (body + "\n\n" if body else "") + block
    return body + "\n" if body else ""


def asset_register(
    app: Any, path: str, key: str, start: str, end: str, producer, order: int = 0
) -> None:
    """Publish a fragment and ensure the route exists. Idempotent."""
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    asset_fragments(app, path)[key] = {
        "start": start,
        "end": end,
        "js": producer,
        "order": order,
    }

    for existing in app.routes:
        if getattr(existing, ASSET_ROUTE_ATTR, None) != path:
            continue
        if getattr(existing, ASSET_IMPL_ATTR, 0) >= ASSET_IMPL_VERSION:
            return  # an equal or newer implementation already owns the route
        break  # ours is newer - fall through and replace it

    # Fragments live on app.state, so replacing the route loses nothing.
    app.routes[:] = [r for r in app.routes if getattr(r, "path", "") != path]
    media_type = SHARED_ASSET_TYPES.get(path, "text/plain; charset=utf-8")

    async def serve_asset(request):
        content = asset_compose(app, path)
        etag = (
            '"owui-'
            # Cache validator only; a bare md5() raises on FIPS hosts.
            + hashlib.md5(
                (path + "\x00" + content).encode("utf-8"), usedforsecurity=False
            ).hexdigest()
            + '"'
        )
        # no-cache, not no-store: no-store would disable the 304 below.
        headers = {
            "Cache-Control": "no-cache, must-revalidate, private",
            "ETag": etag,
        }
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        # Starlette only adds charset for text/*.
        return Response(content, media_type=media_type, headers=headers)

    insert_at = len(app.routes)
    for position, existing in enumerate(app.routes):
        if isinstance(existing, Mount) and getattr(existing, "name", "") == "static":
            insert_at = position
            break
    shared = Route(path, serve_asset, methods=["GET"])
    setattr(shared, ASSET_ROUTE_ATTR, path)
    setattr(shared, ASSET_IMPL_ATTR, ASSET_IMPL_VERSION)
    app.routes.insert(insert_at, shared)


# =========================== end shared asset block ========================


STYLE_NAMES = {
    "default": "Default",
    "cursor": "Blinking Cursor",
    "dot": "Pulsing Dot",
    "bars": "Legacy Bars",
    "block": "Terminal Block",
    "typing": "Typing Dots",
    "wave": "Equalizer",
    "spinner": "Spinner",
    "shimmer": "Shimmer Lines",
    "ellipsis": "Ellipsis",
    "scanner": "Scanner",
    "orbit": "Orbit",
    "ripple": "Ripple",
    "breathe": "Breathing Orb",
    "grid": "Dot Grid",
    "flip": "Flipping Square",
    "sparkle": "Sparkle",
    "heartbeat": "Heartbeat",
    "ball": "Bouncing Ball",
}

# The Thinking header icon is small and inline, so it only offers the compact
# styles (no full-width bars/shimmer, no text cursor), plus "none" to hide it.
THINK_NAMES = {
    "default": "Default",
    "none": "Hidden",
    "spinner": "Spinner",
    "dot": "Pulsing Dot",
    "block": "Terminal Block",
    "typing": "Typing Dots",
    "wave": "Equalizer",
    "ellipsis": "Ellipsis",
    "scanner": "Scanner",
    "orbit": "Orbit",
    "ripple": "Ripple",
    "breathe": "Breathing Orb",
    "grid": "Dot Grid",
    "flip": "Flipping Square",
    "sparkle": "Sparkle",
    "heartbeat": "Heartbeat",
    "ball": "Bouncing Ball",
}

# CSS display of each compact indicator element.
DISPLAY = {
    "block": "inline-block",
    "typing": "inline-flex",
    "wave": "inline-flex",
    "spinner": "inline-block",
    "dot": "inline-flex",
    "ellipsis": "inline-flex",
    "scanner": "inline-block",
    "orbit": "inline-block",
    "ripple": "inline-block",
    "breathe": "inline-block",
    "grid": "inline-grid",
    "flip": "inline-block",
    "sparkle": "inline-block",
    "heartbeat": "inline-block",
    "ball": "inline-block",
}
# Styles added in 1.2.0; their CSS is generated below instead of hand-listed.
NEW_STYLES = [
    "ellipsis",
    "scanner",
    "orbit",
    "ripple",
    "breathe",
    "grid",
    "flip",
    "sparkle",
    "heartbeat",
    "ball",
]


# ---------------------------------------------------------------------------
# 1.3.0: 30 more styles. Merged into the dicts above so the generated CSS,
# both pickers and the valves pick them up automatically.
# ---------------------------------------------------------------------------
def _s(n):
    return "<span></span>" * n


MORE_STYLE_NAMES = {
    "dualring": "Dual Ring",
    "chase": "Dot Chase",
    "dna": "DNA Helix",
    "pendulum": "Pendulum",
    "cradle": "Newton's Cradle",
    "progress": "Progress Bar",
    "stripes": "Barber Pole",
    "hourglass": "Hourglass",
    "clock": "Clock",
    "radar": "Radar",
    "pulsering": "Pulse Ring",
    "squares": "Fading Squares",
    "diamond": "Morphing Diamond",
    "sine": "Sine Wave",
    "dotwave": "Dot Wave",
    "chart": "Bar Chart",
    "typewriter": "Typewriter",
    "underscore": "Underscore",
    "lines": "Rolling Lines",
    "pacman": "Chomper",
    "infinity": "Infinity",
    "triangle": "Triangle Trace",
    "morph": "Morphing Blob",
    "dotring": "Dot Ring",
    "bubbles": "Rising Bubbles",
    "stairs": "Stairs",
    "wifi": "Signal",
    "bolt": "Lightning",
    "twinkle": "Twinkle",
    "gradient": "Gradient Ring",
}
# ---- 1.4.0: 40 more styles (merged into MORE_STYLE_NAMES below) ----
EXTRA_STYLE_NAMES = {
    "spiral": "Spiral",
    "target": "Target",
    "squarejump": "Jumping Squares",
    "seesaw": "Seesaw",
    "propeller": "Propeller",
    "cog": "Cog",
    "dotted": "Dotted Circle",
    "ios": "iOS Spinner",
    "comet": "Comet",
    "marquee": "Marquee",
    "flame": "Flame",
    "drop": "Water Drop",
    "rain": "Rain",
    "fill": "Fill Up",
    "battery": "Battery",
    "moon": "Moon Phase",
    "sun": "Sun",
    "heart": "Heart Beat",
    "star": "Star Pulse",
    "spectrum": "Spectrum",
    "bars3": "Triple Bars",
    "swap": "Swap Dots",
    "trio": "Trio Orbit",
    "satellite": "Satellite",
    "atom": "Atom",
    "binary": "Binary",
    "segments": "Segmented Bar",
    "zigzag": "Zigzag",
    "squaretrace": "Square Trace",
    "hexagon": "Hexagon Trace",
    "pingpong": "Ping Pong",
    "traffic": "Traffic Light",
    "search": "Search",
    "matrix": "Dot Matrix",
    "rotsq": "Turning Square",
    "quad": "Quad Spin",
    "knight": "Knight Rider",
    "thought": "Thought Bubble",
    "diamonds": "Diamond Chain",
    "snow": "Snowfall",
}
MORE_STYLE_NAMES.update(EXTRA_STYLE_NAMES)

# ---- 2.1.0: 12 more styles (total 100) ----
V2_STYLE_NAMES = {
    "gyro": "Gyroscope",
    "domino": "Domino Fall",
    "cube": "Cube Spin",
    "blink": "Blinking Eye",
    "metronome": "Metronome",
    "brackets": "Brackets",
    "zipper": "Zipper",
    "firefly": "Fireflies",
    "plus": "Spinning Plus",
    "compass": "Compass",
    "ringpop": "Ring Pop",
    "pulsesq": "Pulse Squares",
}
MORE_STYLE_NAMES.update(V2_STYLE_NAMES)
V2_MARKUP = "".join(
    [
        '<span class="osk-gyro"><span></span><span></span></span>',
        f'<span class="osk-domino">{_s(4)}</span>',
        '<span class="osk-cube"></span>',
        '<span class="osk-blink"></span>',
        '<span class="osk-metronome"><span></span></span>',
        '<span class="osk-brackets"><span></span><span></span></span>',
        f'<span class="osk-zipper">{_s(4)}</span>',
        f'<span class="osk-firefly">{_s(3)}</span>',
        '<span class="osk-plus"></span>',
        '<span class="osk-compass"><span></span></span>',
        '<span class="osk-ringpop"><span></span><span></span></span>',
        f'<span class="osk-pulsesq">{_s(3)}</span>',
    ]
)
V2_CSS = r"""
.osk-gyro{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;perspective:60px}
.osk-gyro>span{position:absolute;inset:0;box-sizing:border-box;border:1.5px solid var(--osk-m);border-radius:9999px}
.osk-gyro>span:nth-child(1){animation:osk-gyro-x 1.6s linear infinite}
.osk-gyro>span:nth-child(2){opacity:.6;animation:osk-gyro-y 1.6s linear infinite}
@keyframes osk-gyro-x{to{transform:rotateX(360deg)}}
@keyframes osk-gyro-y{to{transform:rotateY(360deg)}}
.osk-domino{align-items:flex-end;gap:2px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-domino>span{width:3px;height:12px;border-radius:1px;background:var(--osk-m);transform-origin:bottom center;animation:osk-domino 1.4s ease-in-out infinite}
.osk-domino>span:nth-child(2){animation-delay:.12s}
.osk-domino>span:nth-child(3){animation-delay:.24s}
.osk-domino>span:nth-child(4){animation-delay:.36s}
@keyframes osk-domino{0%,25%{transform:rotate(0)}50%,75%{transform:rotate(62deg)}100%{transform:rotate(0)}}
.osk-cube{width:12px;height:12px;margin-left:4px;vertical-align:text-bottom;border-radius:2px;background:var(--osk-m);animation:osk-cube 1.4s ease-in-out infinite}
@keyframes osk-cube{0%{transform:perspective(40px) rotateY(0)}50%{transform:perspective(40px) rotateY(180deg)}100%{transform:perspective(40px) rotateY(360deg)}}
.osk-blink{position:relative;box-sizing:border-box;width:16px;height:10px;margin-left:4px;vertical-align:middle;border:1.5px solid var(--osk-m);border-radius:50%;animation:osk-blink 2.2s ease-in-out infinite}
.osk-blink::after{content:'';position:absolute;left:50%;top:50%;width:4px;height:4px;margin:-2px 0 0 -2px;border-radius:50%;background:var(--osk-m)}
@keyframes osk-blink{0%,40%,50%,100%{transform:scaleY(1)}45%{transform:scaleY(.1)}}
.osk-metronome{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-metronome>span{position:absolute;left:50%;bottom:1px;width:2px;height:14px;margin-left:-1px;border-radius:1px;background:var(--osk-m);transform-origin:bottom center;animation:osk-metro 1s ease-in-out infinite alternate}
.osk-metronome>span::after{content:'';position:absolute;left:-2px;top:0;width:6px;height:4px;border-radius:2px;background:var(--osk-m)}
@keyframes osk-metro{from{transform:rotate(-30deg)}to{transform:rotate(30deg)}}
.osk-brackets{position:relative;width:16px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-brackets>span{position:absolute;top:0;bottom:0;box-sizing:border-box;width:5px;border:2px solid var(--osk-m)}
.osk-brackets>span:nth-child(1){left:0;border-right:0;border-radius:2px 0 0 2px;animation:osk-brk 1.2s ease-in-out infinite alternate}
.osk-brackets>span:nth-child(2){right:0;border-left:0;border-radius:0 2px 2px 0;animation:osk-brk2 1.2s ease-in-out infinite alternate}
@keyframes osk-brk{to{transform:translateX(3px)}}
@keyframes osk-brk2{to{transform:translateX(-3px)}}
.osk-zipper{position:relative;width:22px;height:12px;margin-left:4px;vertical-align:text-bottom}
.osk-zipper>span{position:absolute;top:4px;width:3px;height:3px;border-radius:9999px;background:var(--osk-m);animation:osk-zip 1s ease-in-out infinite}
.osk-zipper>span:nth-child(1){left:0}
.osk-zipper>span:nth-child(2){left:6px;animation-delay:-.5s}
.osk-zipper>span:nth-child(3){left:12px}
.osk-zipper>span:nth-child(4){left:18px;animation-delay:-.5s}
@keyframes osk-zip{0%,100%{transform:translateY(-3px)}50%{transform:translateY(3px)}}
.osk-firefly{position:relative;width:18px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-firefly>span{position:absolute;width:3px;height:3px;border-radius:9999px;background:var(--osk-m);box-shadow:0 0 5px var(--osk-m);animation:osk-ff 2.4s ease-in-out infinite}
.osk-firefly>span:nth-child(1){left:2px;top:9px}
.osk-firefly>span:nth-child(2){left:8px;top:3px;animation-delay:-.8s;animation-duration:2.9s}
.osk-firefly>span:nth-child(3){left:14px;top:10px;animation-delay:-1.6s;animation-duration:2.1s}
@keyframes osk-ff{0%,100%{opacity:.15;transform:translate(0,0)}50%{opacity:1;transform:translate(2px,-3px)}}
.osk-plus{position:relative;width:14px;height:14px;margin-left:4px;vertical-align:text-bottom;animation:osk-plus 1.4s ease-in-out infinite}
.osk-plus::before,.osk-plus::after{content:'';position:absolute;border-radius:1px;background:var(--osk-m)}
.osk-plus::before{left:0;right:0;top:6px;height:2px}
.osk-plus::after{top:0;bottom:0;left:6px;width:2px}
@keyframes osk-plus{0%{transform:rotate(0) scale(1)}50%{transform:rotate(90deg) scale(.7)}100%{transform:rotate(180deg) scale(1)}}
.osk-compass{position:relative;box-sizing:border-box;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;border:1.5px solid var(--osk-m);border-radius:50%}
.osk-compass>span{position:absolute;left:50%;top:50%;width:2px;height:8px;margin:-4px 0 0 -1px;border-radius:1px;background:var(--osk-m);animation:osk-compass 2s ease-in-out infinite}
@keyframes osk-compass{0%,100%{transform:rotate(-40deg)}50%{transform:rotate(60deg)}}
.osk-ringpop{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-ringpop>span:nth-child(1){position:absolute;left:50%;top:50%;width:4px;height:4px;margin:-2px 0 0 -2px;border-radius:50%;background:var(--osk-m)}
.osk-ringpop>span:nth-child(2){position:absolute;inset:0;box-sizing:border-box;border:1.5px solid var(--osk-m);border-radius:50%;animation:osk-rp 1.3s ease-out infinite}
@keyframes osk-rp{0%{transform:scale(.25);opacity:1}100%{transform:scale(1);opacity:0}}
.osk-pulsesq{align-items:center;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-pulsesq>span{width:4px;height:4px;background:var(--osk-m);animation:osk-psq 1s ease-in-out infinite}
.osk-pulsesq>span:nth-child(2){animation-delay:.15s}
.osk-pulsesq>span:nth-child(3){animation-delay:.3s}
@keyframes osk-psq{0%,100%{transform:scale(.6);opacity:.5}50%{transform:scale(1.6);opacity:1}}
"""

# ---- Shape Morph (Material 3 loading indicator) ----
V3_STYLE_NAMES = {"shapemorph": "Shape Morph"}
MORE_STYLE_NAMES.update(V3_STYLE_NAMES)
V3_MARKUP = '<span class="osk-shapemorph"></span>'
V3_CSS = r"""
/* Shape Morph: exact MaterialShapes outlines, spring morph (zeta .6, k 200, 650ms/step) */
.osk-shapemorph {
  width: 16px; height: 16px; display: inline-block;
  animation: osk-shapespin 4550ms linear infinite;
}
.osk-shapemorph::before {
  content: ""; display: block; width: 100%; height: 100%;
  background: var(--osk-m);
  animation: osk-shapeblob 4550ms linear infinite;
}
@keyframes osk-shapespin {
  0.00% { transform: rotate(0.0deg); }
  1.10% { transform: rotate(22.9deg); }
  2.20% { transform: rotate(62.2deg); }
  3.30% { transform: rotate(96.9deg); }
  4.40% { transform: rotate(119.8deg); }
  5.71% { transform: rotate(132.8deg); }
  7.25% { transform: rotate(136.8deg); }
  9.23% { transform: rotate(138.2deg); }
  11.65% { transform: rotate(143.9deg); }
  14.29% { transform: rotate(154.3deg); }
  15.38% { transform: rotate(177.2deg); }
  16.48% { transform: rotate(216.4deg); }
  17.58% { transform: rotate(251.2deg); }
  18.68% { transform: rotate(274.1deg); }
  20.00% { transform: rotate(287.1deg); }
  21.54% { transform: rotate(291.1deg); }
  23.52% { transform: rotate(292.4deg); }
  25.93% { transform: rotate(298.2deg); }
  28.57% { transform: rotate(308.6deg); }
  29.67% { transform: rotate(331.5deg); }
  30.77% { transform: rotate(370.7deg); }
  31.87% { transform: rotate(405.5deg); }
  32.97% { transform: rotate(428.4deg); }
  34.29% { transform: rotate(441.4deg); }
  35.82% { transform: rotate(445.3deg); }
  37.80% { transform: rotate(446.7deg); }
  40.22% { transform: rotate(452.5deg); }
  42.86% { transform: rotate(462.9deg); }
  43.96% { transform: rotate(485.8deg); }
  45.05% { transform: rotate(525.0deg); }
  46.15% { transform: rotate(559.8deg); }
  47.25% { transform: rotate(582.7deg); }
  48.57% { transform: rotate(595.7deg); }
  50.11% { transform: rotate(599.6deg); }
  52.09% { transform: rotate(601.0deg); }
  54.51% { transform: rotate(606.8deg); }
  57.14% { transform: rotate(617.1deg); }
  58.24% { transform: rotate(640.1deg); }
  59.34% { transform: rotate(679.3deg); }
  60.44% { transform: rotate(714.1deg); }
  61.54% { transform: rotate(737.0deg); }
  62.86% { transform: rotate(750.0deg); }
  64.40% { transform: rotate(753.9deg); }
  66.37% { transform: rotate(755.3deg); }
  68.79% { transform: rotate(761.1deg); }
  71.43% { transform: rotate(771.4deg); }
  72.53% { transform: rotate(794.4deg); }
  73.63% { transform: rotate(833.6deg); }
  74.73% { transform: rotate(868.3deg); }
  75.82% { transform: rotate(891.3deg); }
  77.14% { transform: rotate(904.3deg); }
  78.68% { transform: rotate(908.2deg); }
  80.66% { transform: rotate(909.6deg); }
  83.08% { transform: rotate(915.4deg); }
  85.71% { transform: rotate(925.7deg); }
  86.81% { transform: rotate(948.7deg); }
  87.91% { transform: rotate(987.9deg); }
  89.01% { transform: rotate(1022.6deg); }
  90.11% { transform: rotate(1045.5deg); }
  91.43% { transform: rotate(1058.6deg); }
  92.97% { transform: rotate(1062.5deg); }
  94.95% { transform: rotate(1063.9deg); }
  97.36% { transform: rotate(1069.6deg); }
  100.00% { transform: rotate(1080.0deg); }
}
@keyframes osk-shapeblob {
  0.00% { clip-path: polygon(80.8% 50.0%,81.9% 52.8%,84.7% 56.1%,87.3% 60.0%,86.6% 63.3%,82.6% 65.2%,78.2% 66.3%,75.3% 67.7%,74.2% 70.3%,74.4% 74.4%,74.6% 79.3%,72.4% 82.0%,68.4% 81.9%,64.0% 80.1%,60.6% 79.1%,58.1% 80.1%,55.9% 83.4%,53.3% 87.5%,50.0% 89.1%,46.7% 87.5%,44.1% 83.3%,41.9% 80.1%,39.4% 79.1%,36.0% 80.1%,31.6% 81.9%,27.6% 82.0%,25.4% 79.3%,25.6% 74.4%,25.9% 70.3%,24.7% 67.7%,21.8% 66.3%,17.3% 65.2%,13.4% 63.3%,12.7% 60.0%,15.3% 56.1%,18.1% 52.8%,19.2% 50.0%,18.1% 47.2%,15.3% 43.9%,12.7% 40.0%,13.4% 36.7%,17.4% 34.8%,21.8% 33.7%,24.7% 32.3%,25.8% 29.7%,25.6% 25.6%,25.4% 20.7%,27.6% 18.0%,31.6% 18.1%,36.0% 19.9%,39.4% 20.9%,41.9% 19.9%,44.1% 16.6%,46.7% 12.5%,50.0% 10.9%,53.3% 12.5%,55.9% 16.7%,58.1% 19.9%,60.6% 20.9%,64.0% 19.9%,68.4% 18.1%,72.4% 18.0%,74.6% 20.7%,74.4% 25.6%,74.1% 29.7%,75.3% 32.3%,78.2% 33.7%,82.7% 34.8%,86.6% 36.7%,87.3% 40.0%,84.7% 43.9%,81.9% 47.2%); }
  1.10% { clip-path: polygon(82.2% 50.0%,82.8% 52.9%,84.9% 56.2%,87.0% 59.9%,86.4% 63.3%,83.2% 65.5%,79.4% 67.0%,76.6% 68.6%,75.2% 71.2%,74.8% 74.8%,74.4% 79.1%,72.2% 81.7%,68.6% 82.2%,64.5% 81.2%,61.2% 80.7%,58.5% 81.7%,56.0% 84.3%,53.3% 87.5%,50.0% 88.7%,46.7% 87.4%,44.0% 84.3%,41.5% 81.7%,38.8% 80.7%,35.4% 81.2%,31.4% 82.2%,27.8% 81.7%,25.6% 79.1%,25.2% 74.8%,24.8% 71.1%,23.4% 68.6%,20.6% 67.0%,16.8% 65.5%,13.6% 63.3%,13.1% 59.9%,15.1% 56.1%,17.2% 52.9%,17.8% 50.0%,16.8% 47.1%,14.5% 43.7%,12.6% 40.0%,13.7% 36.8%,17.4% 34.8%,21.3% 33.4%,23.9% 31.7%,24.9% 29.0%,25.0% 25.0%,25.3% 20.6%,27.7% 18.1%,31.6% 18.1%,35.8% 19.5%,39.1% 20.1%,41.7% 19.0%,44.0% 16.0%,46.7% 12.3%,50.0% 11.0%,53.3% 12.4%,56.0% 16.0%,58.3% 19.0%,60.9% 20.1%,64.2% 19.5%,68.5% 18.0%,72.3% 18.1%,74.6% 20.6%,75.0% 25.0%,75.0% 29.0%,76.1% 31.7%,78.7% 33.4%,82.7% 34.8%,86.3% 36.8%,87.3% 40.0%,85.4% 43.8%,83.2% 47.1%); }
  2.20% { clip-path: polygon(84.9% 50.0%,84.5% 53.0%,85.2% 56.2%,86.3% 59.7%,86.2% 63.2%,84.2% 66.0%,81.6% 68.2%,79.1% 70.4%,77.2% 72.8%,75.5% 75.5%,74.1% 78.7%,71.8% 81.2%,68.9% 82.7%,65.5% 83.3%,62.3% 83.7%,59.3% 84.6%,56.4% 86.0%,53.3% 87.4%,50.0% 87.9%,46.7% 87.4%,43.6% 86.0%,40.7% 84.6%,37.7% 83.7%,34.5% 83.3%,31.1% 82.8%,28.2% 81.2%,25.9% 78.7%,24.5% 75.5%,22.9% 72.8%,20.9% 70.4%,18.4% 68.2%,15.7% 66.0%,13.8% 63.2%,13.7% 59.7%,14.8% 56.2%,15.5% 53.0%,15.1% 50.0%,14.3% 46.9%,13.1% 43.5%,12.6% 40.0%,14.1% 36.9%,17.4% 34.8%,20.4% 32.9%,22.3% 30.6%,23.3% 27.6%,24.0% 24.0%,25.2% 20.4%,27.8% 18.3%,31.5% 17.9%,35.4% 18.7%,38.6% 18.7%,41.3% 17.5%,43.8% 14.8%,46.7% 12.1%,50.0% 11.1%,53.3% 12.1%,56.2% 14.8%,58.7% 17.5%,61.4% 18.7%,64.6% 18.7%,68.5% 17.9%,72.2% 18.3%,74.8% 20.5%,76.0% 24.0%,76.7% 27.6%,77.7% 30.6%,79.6% 32.9%,82.7% 34.8%,85.9% 36.9%,87.4% 40.0%,86.8% 43.5%,85.7% 46.9%); }
  3.30% { clip-path: polygon(87.2% 50.0%,86.0% 53.2%,85.5% 56.3%,85.7% 59.6%,85.9% 63.1%,85.2% 66.4%,83.5% 69.3%,81.3% 71.9%,78.9% 74.2%,76.1% 76.1%,73.8% 78.3%,71.5% 80.7%,69.2% 83.2%,66.4% 85.1%,63.2% 86.4%,60.0% 87.2%,56.6% 87.6%,53.3% 87.4%,50.0% 87.3%,46.7% 87.4%,43.4% 87.6%,40.0% 87.2%,36.8% 86.4%,33.6% 85.1%,30.8% 83.2%,28.5% 80.7%,26.2% 78.3%,23.9% 76.1%,21.1% 74.2%,18.7% 71.9%,16.5% 69.3%,14.8% 66.4%,14.1% 63.1%,14.3% 59.6%,14.5% 56.3%,14.0% 53.2%,12.8% 50.0%,12.1% 46.7%,11.9% 43.3%,12.5% 40.0%,14.5% 37.1%,17.3% 34.8%,19.6% 32.4%,20.9% 29.7%,21.8% 26.3%,23.1% 23.1%,25.1% 20.3%,27.9% 18.4%,31.4% 17.8%,35.1% 18.0%,38.2% 17.5%,40.9% 16.1%,43.6% 13.8%,46.7% 11.9%,50.0% 11.2%,53.3% 11.9%,56.4% 13.8%,59.1% 16.1%,61.8% 17.5%,64.9% 18.0%,68.6% 17.8%,72.1% 18.4%,74.9% 20.3%,76.9% 23.1%,78.2% 26.4%,79.1% 29.7%,80.4% 32.4%,82.7% 34.8%,85.5% 37.1%,87.4% 40.0%,88.1% 43.3%,87.9% 46.7%); }
  4.40% { clip-path: polygon(88.6% 50.0%,87.0% 53.2%,85.7% 56.3%,85.3% 59.5%,85.8% 63.0%,85.7% 66.7%,84.6% 70.0%,82.7% 72.9%,79.9% 75.1%,76.5% 76.5%,73.6% 78.1%,71.3% 80.4%,69.4% 83.5%,66.9% 86.2%,63.8% 88.0%,60.4% 88.8%,56.8% 88.5%,53.3% 87.3%,50.0% 86.9%,46.7% 87.3%,43.2% 88.5%,39.6% 88.8%,36.2% 88.0%,33.1% 86.2%,30.6% 83.5%,28.7% 80.4%,26.4% 78.1%,23.5% 76.5%,20.1% 75.1%,17.3% 72.9%,15.4% 70.0%,14.3% 66.7%,14.2% 63.0%,14.7% 59.5%,14.3% 56.3%,13.0% 53.2%,11.4% 50.0%,10.8% 46.6%,11.2% 43.2%,12.5% 40.0%,14.7% 37.2%,17.3% 34.8%,19.1% 32.1%,20.1% 29.1%,20.9% 25.6%,22.6% 22.6%,25.0% 20.2%,28.0% 18.5%,31.4% 17.7%,34.9% 17.6%,37.9% 16.8%,40.7% 15.3%,43.5% 13.1%,46.7% 11.8%,50.0% 11.3%,53.3% 11.7%,56.5% 13.1%,59.3% 15.3%,62.1% 16.8%,65.1% 17.6%,68.6% 17.7%,72.0% 18.5%,75.0% 20.2%,77.4% 22.6%,79.1% 25.6%,79.9% 29.1%,80.9% 32.1%,82.7% 34.8%,85.3% 37.2%,87.5% 40.0%,88.8% 43.2%,89.2% 46.6%); }
  5.71% { clip-path: polygon(89.2% 50.0%,87.4% 53.3%,85.8% 56.3%,85.2% 59.4%,85.7% 63.0%,86.0% 66.8%,85.2% 70.3%,83.3% 73.3%,80.4% 75.5%,76.7% 76.7%,73.5% 78.0%,71.2% 80.3%,69.4% 83.7%,67.1% 86.7%,64.1% 88.7%,60.6% 89.4%,56.9% 88.9%,53.3% 87.3%,50.0% 86.7%,46.7% 87.3%,43.1% 88.9%,39.4% 89.4%,35.9% 88.7%,32.9% 86.7%,30.6% 83.7%,28.8% 80.3%,26.5% 78.0%,23.3% 76.7%,19.6% 75.5%,16.7% 73.3%,14.8% 70.3%,14.0% 66.8%,14.3% 63.0%,14.8% 59.4%,14.2% 56.3%,12.6% 53.3%,10.8% 50.0%,10.2% 46.5%,10.9% 43.1%,12.5% 40.0%,14.8% 37.2%,17.3% 34.8%,18.9% 32.0%,19.7% 28.8%,20.5% 25.3%,22.4% 22.4%,25.0% 20.2%,28.0% 18.6%,31.3% 17.7%,34.8% 17.4%,37.8% 16.4%,40.6% 14.9%,43.4% 12.8%,46.6% 11.7%,50.0% 11.3%,53.4% 11.7%,56.6% 12.8%,59.4% 14.9%,62.2% 16.4%,65.2% 17.4%,68.7% 17.7%,72.0% 18.6%,75.0% 20.2%,77.6% 22.4%,79.5% 25.3%,80.3% 28.8%,81.1% 32.0%,82.7% 34.8%,85.2% 37.2%,87.5% 40.0%,89.1% 43.1%,89.8% 46.5%); }
  7.25% { clip-path: polygon(89.1% 50.0%,87.3% 53.3%,85.8% 56.3%,85.2% 59.4%,85.8% 63.0%,85.9% 66.7%,85.1% 70.2%,83.1% 73.2%,80.3% 75.4%,76.6% 76.6%,73.5% 78.0%,71.2% 80.3%,69.4% 83.6%,67.1% 86.6%,64.0% 88.5%,60.5% 89.3%,56.8% 88.8%,53.3% 87.3%,50.0% 86.7%,46.7% 87.3%,43.2% 88.8%,39.5% 89.3%,36.0% 88.5%,32.9% 86.6%,30.6% 83.6%,28.8% 80.3%,26.5% 78.0%,23.4% 76.6%,19.7% 75.4%,16.9% 73.2%,14.9% 70.2%,14.1% 66.7%,14.2% 63.0%,14.8% 59.4%,14.2% 56.3%,12.7% 53.3%,10.9% 50.0%,10.3% 46.5%,10.9% 43.1%,12.5% 40.0%,14.8% 37.2%,17.3% 34.8%,18.9% 32.0%,19.8% 28.9%,20.6% 25.3%,22.4% 22.4%,25.0% 20.2%,28.0% 18.6%,31.3% 17.7%,34.8% 17.4%,37.8% 16.5%,40.6% 15.0%,43.5% 12.9%,46.6% 11.7%,50.0% 11.3%,53.4% 11.7%,56.5% 12.9%,59.4% 15.0%,62.2% 16.5%,65.2% 17.4%,68.7% 17.7%,72.0% 18.6%,75.0% 20.2%,77.6% 22.4%,79.4% 25.3%,80.2% 28.9%,81.1% 32.0%,82.7% 34.8%,85.2% 37.2%,87.5% 40.0%,89.1% 43.1%,89.7% 46.5%); }
  9.23% { clip-path: polygon(88.6% 50.0%,87.0% 53.2%,85.7% 56.3%,85.3% 59.5%,85.8% 63.0%,85.7% 66.7%,84.7% 70.0%,82.7% 72.9%,80.0% 75.1%,76.5% 76.5%,73.6% 78.1%,71.3% 80.4%,69.4% 83.6%,66.9% 86.3%,63.8% 88.1%,60.4% 88.8%,56.8% 88.6%,53.3% 87.3%,50.0% 86.9%,46.7% 87.3%,43.2% 88.6%,39.6% 88.8%,36.2% 88.1%,33.1% 86.3%,30.6% 83.6%,28.7% 80.4%,26.4% 78.1%,23.5% 76.5%,20.0% 75.1%,17.3% 72.9%,15.3% 70.0%,14.3% 66.7%,14.2% 63.0%,14.7% 59.5%,14.3% 56.3%,13.0% 53.2%,11.4% 50.0%,10.7% 46.6%,11.2% 43.2%,12.5% 40.0%,14.7% 37.2%,17.3% 34.8%,19.0% 32.1%,20.1% 29.0%,20.9% 25.6%,22.6% 22.6%,25.0% 20.2%,28.0% 18.5%,31.4% 17.7%,34.9% 17.5%,37.9% 16.7%,40.7% 15.2%,43.5% 13.1%,46.7% 11.7%,50.0% 11.3%,53.3% 11.7%,56.5% 13.1%,59.3% 15.2%,62.1% 16.7%,65.1% 17.5%,68.6% 17.7%,72.0% 18.5%,75.0% 20.2%,77.4% 22.6%,79.1% 25.6%,79.9% 29.0%,81.0% 32.1%,82.7% 34.8%,85.3% 37.2%,87.5% 40.0%,88.8% 43.2%,89.3% 46.6%); }
  11.65% { clip-path: polygon(88.4% 50.0%,86.9% 53.2%,85.7% 56.3%,85.4% 59.5%,85.8% 63.0%,85.7% 66.6%,84.5% 69.9%,82.5% 72.8%,79.8% 75.0%,76.5% 76.5%,73.6% 78.1%,71.3% 80.4%,69.3% 83.5%,66.8% 86.1%,63.8% 87.8%,60.3% 88.6%,56.8% 88.4%,53.3% 87.3%,50.0% 86.9%,46.7% 87.3%,43.2% 88.4%,39.7% 88.6%,36.2% 87.8%,33.2% 86.1%,30.7% 83.5%,28.7% 80.4%,26.4% 78.1%,23.5% 76.5%,20.2% 75.0%,17.5% 72.8%,15.5% 69.9%,14.3% 66.6%,14.2% 63.0%,14.6% 59.5%,14.3% 56.3%,13.1% 53.2%,11.6% 50.0%,10.9% 46.6%,11.3% 43.2%,12.5% 40.0%,14.7% 37.2%,17.3% 34.8%,19.1% 32.2%,20.2% 29.1%,21.0% 25.7%,22.6% 22.6%,25.0% 20.2%,28.0% 18.5%,31.4% 17.7%,34.9% 17.6%,37.9% 16.9%,40.7% 15.3%,43.5% 13.2%,46.7% 11.8%,50.0% 11.3%,53.3% 11.8%,56.5% 13.2%,59.3% 15.3%,62.1% 16.9%,65.1% 17.6%,68.6% 17.7%,72.0% 18.5%,75.0% 20.2%,77.4% 22.6%,79.0% 25.7%,79.8% 29.1%,80.9% 32.2%,82.7% 34.8%,85.3% 37.2%,87.5% 40.0%,88.7% 43.2%,89.1% 46.6%); }
  14.29% { clip-path: polygon(88.5% 50.0%,86.9% 53.2%,85.7% 56.3%,85.3% 59.5%,85.8% 63.0%,85.7% 66.6%,84.6% 70.0%,82.6% 72.8%,79.8% 75.0%,76.5% 76.5%,73.6% 78.1%,71.3% 80.4%,69.4% 83.5%,66.9% 86.1%,63.8% 87.9%,60.4% 88.7%,56.8% 88.5%,53.3% 87.3%,50.0% 86.9%,46.7% 87.3%,43.2% 88.5%,39.6% 88.7%,36.2% 87.9%,33.1% 86.1%,30.6% 83.5%,28.7% 80.4%,26.4% 78.1%,23.5% 76.5%,20.2% 75.0%,17.4% 72.8%,15.4% 70.0%,14.3% 66.6%,14.2% 63.0%,14.7% 59.5%,14.3% 56.3%,13.1% 53.2%,11.5% 50.0%,10.9% 46.6%,11.2% 43.2%,12.5% 40.0%,14.7% 37.2%,17.3% 34.8%,19.1% 32.2%,20.2% 29.1%,21.0% 25.6%,22.6% 22.6%,25.0% 20.2%,28.0% 18.5%,31.4% 17.7%,34.9% 17.6%,37.9% 16.8%,40.7% 15.3%,43.5% 13.1%,46.7% 11.8%,50.0% 11.3%,53.3% 11.8%,56.5% 13.1%,59.3% 15.3%,62.1% 16.8%,65.1% 17.6%,68.6% 17.7%,72.0% 18.5%,75.0% 20.2%,77.4% 22.6%,79.0% 25.6%,79.8% 29.1%,80.9% 32.2%,82.7% 34.8%,85.3% 37.2%,87.5% 40.0%,88.8% 43.2%,89.1% 46.6%); }
  15.38% { clip-path: polygon(88.4% 50.0%,86.9% 53.2%,85.7% 56.3%,85.3% 59.4%,85.5% 62.9%,85.2% 66.4%,84.1% 69.7%,82.3% 72.6%,79.8% 75.0%,76.8% 76.8%,74.2% 78.8%,71.8% 81.1%,69.6% 84.0%,66.9% 86.3%,63.7% 87.7%,60.3% 88.3%,56.7% 88.1%,53.3% 87.2%,50.0% 86.9%,46.7% 87.2%,43.3% 88.1%,39.7% 88.3%,36.3% 87.7%,33.1% 86.3%,30.4% 84.0%,28.2% 81.1%,25.8% 78.8%,23.2% 76.8%,20.2% 75.0%,17.7% 72.6%,15.9% 69.7%,14.8% 66.4%,14.5% 62.9%,14.7% 59.4%,14.3% 56.3%,13.1% 53.2%,11.6% 50.0%,10.9% 46.6%,11.2% 43.2%,12.4% 39.9%,14.5% 37.1%,17.1% 34.7%,19.1% 32.1%,20.4% 29.3%,21.6% 26.1%,23.4% 23.4%,25.7% 21.1%,28.6% 19.4%,31.8% 18.4%,35.1% 18.0%,38.0% 17.1%,40.8% 15.5%,43.6% 13.4%,46.7% 12.1%,50.0% 11.6%,53.3% 12.1%,56.4% 13.4%,59.2% 15.5%,62.0% 17.1%,64.9% 18.0%,68.2% 18.4%,71.4% 19.4%,74.3% 21.1%,76.6% 23.4%,78.4% 26.1%,79.6% 29.3%,80.9% 32.1%,82.9% 34.7%,85.5% 37.1%,87.6% 39.9%,88.8% 43.2%,89.1% 46.6%); }
  16.48% { clip-path: polygon(88.2% 50.0%,86.9% 53.2%,85.8% 56.3%,85.1% 59.4%,84.8% 62.7%,84.2% 65.9%,83.1% 69.1%,81.6% 72.2%,79.7% 75.0%,77.5% 77.5%,75.2% 80.0%,72.7% 82.4%,70.1% 84.8%,67.0% 86.5%,63.6% 87.3%,60.1% 87.7%,56.6% 87.6%,53.2% 87.1%,50.0% 86.9%,46.8% 87.1%,43.4% 87.6%,39.9% 87.7%,36.4% 87.3%,33.0% 86.5%,29.9% 84.8%,27.3% 82.4%,24.8% 80.0%,22.5% 77.5%,20.3% 75.0%,18.4% 72.2%,16.9% 69.1%,15.8% 65.9%,15.2% 62.7%,14.9% 59.4%,14.2% 56.3%,13.1% 53.2%,11.8% 50.0%,11.0% 46.6%,11.1% 43.1%,12.1% 39.9%,14.1% 36.9%,16.6% 34.4%,19.0% 32.1%,21.0% 29.7%,22.7% 27.1%,24.7% 24.7%,27.1% 22.7%,29.7% 21.1%,32.6% 19.8%,35.5% 18.9%,38.2% 17.6%,40.9% 15.9%,43.6% 14.0%,46.7% 12.7%,50.0% 12.3%,53.3% 12.7%,56.4% 14.0%,59.1% 15.9%,61.8% 17.6%,64.5% 18.9%,67.4% 19.8%,70.3% 21.1%,72.9% 22.7%,75.3% 24.7%,77.3% 27.1%,79.0% 29.7%,81.0% 32.1%,83.4% 34.4%,85.9% 36.9%,87.9% 39.9%,88.9% 43.1%,89.0% 46.6%); }
  17.58% { clip-path: polygon(88.1% 50.0%,86.9% 53.2%,85.8% 56.3%,84.9% 59.4%,84.2% 62.4%,83.3% 65.6%,82.3% 68.7%,81.1% 71.8%,79.7% 74.9%,78.1% 78.1%,76.1% 81.1%,73.5% 83.6%,70.5% 85.6%,67.1% 86.7%,63.5% 87.0%,60.0% 87.1%,56.5% 87.1%,53.2% 86.9%,50.0% 86.8%,46.8% 86.9%,43.5% 87.1%,40.0% 87.1%,36.5% 87.0%,32.9% 86.7%,29.5% 85.6%,26.5% 83.6%,23.9% 81.1%,21.9% 78.1%,20.3% 74.9%,18.9% 71.8%,17.7% 68.7%,16.7% 65.6%,15.8% 62.4%,15.1% 59.4%,14.2% 56.3%,13.1% 53.2%,11.9% 50.0%,11.0% 46.6%,11.0% 43.1%,11.9% 39.8%,13.7% 36.8%,16.3% 34.3%,19.0% 32.1%,21.4% 30.0%,23.7% 27.9%,25.9% 25.9%,28.3% 24.2%,30.7% 22.5%,33.3% 21.0%,35.8% 19.6%,38.4% 18.0%,41.0% 16.3%,43.7% 14.4%,46.8% 13.3%,50.0% 12.9%,53.2% 13.3%,56.3% 14.4%,59.0% 16.3%,61.6% 18.0%,64.2% 19.6%,66.7% 21.0%,69.3% 22.5%,71.7% 24.2%,74.1% 25.9%,76.3% 27.9%,78.6% 30.0%,81.0% 32.1%,83.7% 34.3%,86.3% 36.8%,88.1% 39.8%,89.0% 43.1%,89.0% 46.6%); }
  18.68% { clip-path: polygon(88.0% 50.0%,86.9% 53.2%,85.9% 56.3%,84.9% 59.3%,83.8% 62.3%,82.8% 65.3%,81.8% 68.4%,80.8% 71.5%,79.7% 74.9%,78.5% 78.5%,76.6% 81.7%,74.0% 84.3%,70.8% 86.0%,67.2% 86.8%,63.4% 86.8%,59.9% 86.8%,56.5% 86.8%,53.2% 86.8%,50.0% 86.8%,46.8% 86.8%,43.5% 86.8%,40.1% 86.8%,36.6% 86.8%,32.8% 86.8%,29.2% 86.0%,26.0% 84.3%,23.4% 81.7%,21.5% 78.5%,20.3% 74.9%,19.2% 71.5%,18.2% 68.4%,17.2% 65.3%,16.2% 62.3%,15.1% 59.3%,14.1% 56.3%,13.1% 53.2%,12.0% 50.0%,11.1% 46.6%,10.9% 43.1%,11.8% 39.8%,13.5% 36.7%,16.0% 34.2%,19.0% 32.1%,21.7% 30.2%,24.2% 28.4%,26.7% 26.7%,29.0% 25.0%,31.4% 23.4%,33.7% 21.7%,36.0% 20.1%,38.5% 18.3%,41.0% 16.5%,43.8% 14.7%,46.8% 13.6%,50.0% 13.2%,53.2% 13.6%,56.2% 14.7%,59.0% 16.5%,61.5% 18.3%,64.0% 20.1%,66.3% 21.7%,68.6% 23.4%,71.0% 25.0%,73.3% 26.7%,75.8% 28.4%,78.3% 30.2%,81.0% 32.1%,84.0% 34.2%,86.5% 36.7%,88.2% 39.8%,89.1% 43.1%,88.9% 46.6%); }
  20.00% { clip-path: polygon(87.9% 50.0%,86.9% 53.2%,85.9% 56.3%,84.8% 59.3%,83.7% 62.3%,82.6% 65.2%,81.6% 68.2%,80.6% 71.4%,79.6% 74.9%,78.6% 78.6%,76.9% 82.0%,74.2% 84.6%,70.9% 86.2%,67.2% 86.8%,63.4% 86.7%,59.8% 86.7%,56.5% 86.7%,53.2% 86.8%,50.0% 86.8%,46.8% 86.8%,43.5% 86.7%,40.2% 86.7%,36.6% 86.7%,32.8% 86.8%,29.1% 86.2%,25.8% 84.6%,23.1% 82.0%,21.4% 78.6%,20.4% 74.9%,19.4% 71.4%,18.4% 68.2%,17.4% 65.2%,16.3% 62.3%,15.2% 59.3%,14.1% 56.3%,13.1% 53.2%,12.1% 50.0%,11.1% 46.6%,10.9% 43.1%,11.7% 39.7%,13.4% 36.7%,15.9% 34.1%,18.9% 32.1%,21.8% 30.3%,24.5% 28.6%,27.0% 27.0%,29.4% 25.4%,31.6% 23.8%,33.9% 22.1%,36.1% 20.3%,38.5% 18.4%,41.1% 16.6%,43.8% 14.9%,46.8% 13.7%,50.0% 13.4%,53.2% 13.7%,56.2% 14.9%,58.9% 16.6%,61.5% 18.4%,63.9% 20.3%,66.1% 22.1%,68.4% 23.8%,70.6% 25.4%,73.0% 27.0%,75.5% 28.6%,78.2% 30.3%,81.1% 32.1%,84.1% 34.1%,86.6% 36.7%,88.3% 39.7%,89.1% 43.1%,88.9% 46.6%); }
  21.54% { clip-path: polygon(87.9% 50.0%,86.9% 53.2%,85.9% 56.3%,84.8% 59.3%,83.7% 62.3%,82.6% 65.2%,81.6% 68.3%,80.6% 71.5%,79.7% 74.9%,78.6% 78.6%,76.8% 82.0%,74.2% 84.5%,70.9% 86.2%,67.2% 86.8%,63.4% 86.7%,59.8% 86.7%,56.5% 86.7%,53.2% 86.8%,50.0% 86.8%,46.8% 86.8%,43.5% 86.7%,40.2% 86.7%,36.6% 86.7%,32.8% 86.8%,29.1% 86.2%,25.8% 84.5%,23.2% 82.0%,21.4% 78.6%,20.3% 74.9%,19.4% 71.5%,18.4% 68.3%,17.4% 65.2%,16.3% 62.3%,15.2% 59.3%,14.1% 56.3%,13.1% 53.2%,12.1% 50.0%,11.1% 46.6%,10.9% 43.1%,11.7% 39.7%,13.4% 36.7%,15.9% 34.1%,18.9% 32.1%,21.8% 30.2%,24.5% 28.6%,27.0% 27.0%,29.3% 25.3%,31.6% 23.7%,33.8% 22.0%,36.1% 20.2%,38.5% 18.4%,41.0% 16.6%,43.8% 14.8%,46.8% 13.7%,50.0% 13.3%,53.2% 13.7%,56.2% 14.8%,59.0% 16.6%,61.5% 18.4%,63.9% 20.2%,66.2% 22.0%,68.4% 23.7%,70.7% 25.3%,73.0% 27.0%,75.5% 28.6%,78.2% 30.2%,81.1% 32.1%,84.1% 34.1%,86.6% 36.7%,88.3% 39.7%,89.1% 43.1%,88.9% 46.6%); }
  23.52% { clip-path: polygon(88.0% 50.0%,86.9% 53.2%,85.9% 56.3%,84.8% 59.3%,83.8% 62.3%,82.8% 65.3%,81.8% 68.4%,80.7% 71.5%,79.7% 74.9%,78.5% 78.5%,76.7% 81.8%,74.0% 84.3%,70.8% 86.0%,67.2% 86.8%,63.4% 86.8%,59.9% 86.8%,56.5% 86.8%,53.2% 86.8%,50.0% 86.8%,46.8% 86.8%,43.5% 86.8%,40.1% 86.8%,36.6% 86.8%,32.8% 86.8%,29.2% 86.0%,26.0% 84.3%,23.3% 81.8%,21.5% 78.5%,20.3% 74.9%,19.3% 71.5%,18.2% 68.4%,17.2% 65.3%,16.2% 62.3%,15.2% 59.3%,14.1% 56.3%,13.1% 53.2%,12.0% 50.0%,11.1% 46.6%,10.9% 43.1%,11.7% 39.7%,13.4% 36.7%,16.0% 34.1%,18.9% 32.1%,21.7% 30.2%,24.3% 28.4%,26.7% 26.7%,29.1% 25.1%,31.4% 23.4%,33.7% 21.8%,36.0% 20.1%,38.5% 18.3%,41.0% 16.5%,43.8% 14.7%,46.8% 13.6%,50.0% 13.2%,53.2% 13.6%,56.2% 14.7%,59.0% 16.5%,61.5% 18.3%,64.0% 20.1%,66.3% 21.8%,68.6% 23.4%,70.9% 25.1%,73.3% 26.7%,75.7% 28.4%,78.3% 30.2%,81.1% 32.1%,84.0% 34.1%,86.6% 36.7%,88.3% 39.7%,89.1% 43.1%,88.9% 46.6%); }
  25.93% { clip-path: polygon(88.0% 50.0%,86.9% 53.2%,85.9% 56.3%,84.9% 59.3%,83.9% 62.3%,82.9% 65.3%,81.9% 68.4%,80.8% 71.6%,79.7% 74.9%,78.4% 78.4%,76.6% 81.7%,74.0% 84.2%,70.8% 86.0%,67.1% 86.8%,63.4% 86.8%,59.9% 86.8%,56.5% 86.8%,53.2% 86.8%,50.0% 86.8%,46.8% 86.8%,43.5% 86.8%,40.1% 86.8%,36.6% 86.8%,32.9% 86.8%,29.2% 86.0%,26.0% 84.2%,23.4% 81.7%,21.6% 78.4%,20.3% 74.9%,19.2% 71.6%,18.1% 68.4%,17.1% 65.3%,16.1% 62.3%,15.1% 59.3%,14.1% 56.3%,13.1% 53.2%,12.0% 50.0%,11.1% 46.6%,10.9% 43.1%,11.8% 39.8%,13.5% 36.7%,16.0% 34.2%,19.0% 32.1%,21.7% 30.2%,24.2% 28.3%,26.6% 26.6%,29.0% 24.9%,31.3% 23.3%,33.6% 21.7%,36.0% 20.0%,38.5% 18.3%,41.0% 16.5%,43.8% 14.7%,46.8% 13.6%,50.0% 13.2%,53.2% 13.6%,56.2% 14.7%,59.0% 16.5%,61.5% 18.3%,64.0% 20.0%,66.4% 21.7%,68.7% 23.3%,71.0% 24.9%,73.4% 26.6%,75.8% 28.3%,78.3% 30.2%,81.0% 32.1%,84.0% 34.2%,86.5% 36.7%,88.2% 39.8%,89.1% 43.1%,88.9% 46.6%); }
  28.57% { clip-path: polygon(88.0% 50.0%,86.9% 53.2%,85.9% 56.3%,84.9% 59.3%,83.9% 62.3%,82.9% 65.3%,81.8% 68.4%,80.8% 71.6%,79.7% 74.9%,78.4% 78.4%,76.6% 81.7%,74.0% 84.2%,70.8% 86.0%,67.1% 86.8%,63.4% 86.8%,59.9% 86.8%,56.5% 86.8%,53.2% 86.8%,50.0% 86.8%,46.8% 86.8%,43.5% 86.8%,40.1% 86.8%,36.6% 86.8%,32.9% 86.8%,29.2% 86.0%,26.0% 84.2%,23.4% 81.7%,21.6% 78.4%,20.3% 74.9%,19.2% 71.6%,18.2% 68.4%,17.1% 65.3%,16.1% 62.3%,15.1% 59.3%,14.1% 56.3%,13.1% 53.2%,12.0% 50.0%,11.1% 46.6%,10.9% 43.1%,11.8% 39.8%,13.5% 36.7%,16.0% 34.2%,19.0% 32.1%,21.7% 30.2%,24.2% 28.4%,26.6% 26.6%,29.0% 25.0%,31.3% 23.3%,33.7% 21.7%,36.0% 20.0%,38.5% 18.3%,41.0% 16.5%,43.8% 14.7%,46.8% 13.6%,50.0% 13.2%,53.2% 13.6%,56.2% 14.7%,59.0% 16.5%,61.5% 18.3%,64.0% 20.0%,66.3% 21.7%,68.7% 23.3%,71.0% 25.0%,73.4% 26.6%,75.8% 28.4%,78.3% 30.2%,81.0% 32.1%,84.0% 34.2%,86.5% 36.7%,88.2% 39.8%,89.1% 43.1%,88.9% 46.6%); }
  29.67% { clip-path: polygon(88.1% 50.0%,87.1% 53.2%,86.0% 56.4%,85.0% 59.4%,83.9% 62.3%,82.7% 65.3%,81.5% 68.2%,80.3% 71.2%,79.0% 74.3%,77.6% 77.6%,75.7% 80.6%,73.2% 83.1%,70.1% 84.9%,66.7% 85.9%,63.2% 86.3%,59.8% 86.6%,56.5% 86.8%,53.2% 87.0%,50.0% 87.2%,46.7% 87.2%,43.4% 87.2%,40.0% 87.1%,36.5% 87.0%,32.8% 86.8%,29.3% 85.9%,26.1% 84.1%,23.4% 81.7%,21.4% 78.6%,20.0% 75.2%,18.7% 71.9%,17.5% 68.8%,16.4% 65.7%,15.4% 62.6%,14.5% 59.5%,13.6% 56.4%,12.7% 53.3%,11.9% 50.0%,11.3% 46.6%,11.4% 43.2%,12.3% 39.9%,13.9% 36.9%,16.4% 34.3%,19.1% 32.2%,21.7% 30.2%,24.2% 28.4%,26.6% 26.6%,28.9% 24.8%,31.2% 23.1%,33.5% 21.4%,35.8% 19.6%,38.3% 17.9%,40.9% 16.1%,43.7% 14.4%,46.8% 13.3%,50.0% 12.8%,53.2% 13.1%,56.3% 14.0%,59.2% 15.6%,62.0% 17.2%,64.6% 18.8%,67.1% 20.4%,69.6% 22.0%,72.0% 23.8%,74.4% 25.6%,76.9% 27.5%,79.3% 29.5%,81.9% 31.6%,84.5% 33.9%,86.8% 36.6%,88.3% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  30.77% { clip-path: polygon(88.3% 50.0%,87.4% 53.3%,86.4% 56.4%,85.2% 59.4%,83.9% 62.3%,82.5% 65.1%,80.9% 67.9%,79.3% 70.5%,77.7% 73.2%,76.0% 76.0%,74.0% 78.6%,71.7% 80.9%,69.0% 82.9%,66.0% 84.3%,62.8% 85.3%,59.7% 86.1%,56.5% 86.8%,53.3% 87.4%,50.0% 87.8%,46.7% 88.0%,43.3% 88.0%,39.9% 87.7%,36.4% 87.4%,32.8% 86.8%,29.4% 85.7%,26.2% 83.9%,23.4% 81.6%,21.2% 78.8%,19.3% 75.7%,17.7% 72.6%,16.3% 69.5%,15.0% 66.3%,14.0% 63.1%,13.2% 59.9%,12.5% 56.6%,12.0% 53.3%,11.7% 50.0%,11.6% 46.6%,12.1% 43.3%,13.2% 40.1%,14.8% 37.2%,17.0% 34.6%,19.4% 32.4%,21.9% 30.3%,24.2% 28.3%,26.4% 26.4%,28.6% 24.5%,30.8% 22.6%,33.1% 20.7%,35.5% 18.9%,38.0% 17.1%,40.7% 15.4%,43.6% 13.9%,46.7% 12.8%,50.0% 12.2%,53.3% 12.2%,56.6% 12.8%,59.7% 13.8%,62.7% 15.0%,65.7% 16.4%,68.5% 17.9%,71.3% 19.6%,73.9% 21.5%,76.4% 23.6%,78.8% 25.8%,81.2% 28.2%,83.4% 30.7%,85.5% 33.5%,87.3% 36.4%,88.4% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  31.87% { clip-path: polygon(88.5% 50.0%,87.7% 53.3%,86.7% 56.5%,85.4% 59.5%,83.9% 62.3%,82.2% 65.0%,80.4% 67.6%,78.5% 69.9%,76.5% 72.3%,74.6% 74.6%,72.5% 76.9%,70.3% 79.1%,68.0% 81.1%,65.4% 82.9%,62.5% 84.4%,59.6% 85.7%,56.5% 86.8%,53.3% 87.7%,50.0% 88.3%,46.6% 88.7%,43.2% 88.6%,39.7% 88.3%,36.3% 87.7%,32.8% 86.8%,29.5% 85.5%,26.3% 83.8%,23.5% 81.6%,20.9% 79.1%,18.7% 76.2%,16.8% 73.2%,15.2% 70.1%,13.8% 66.9%,12.8% 63.5%,12.1% 60.2%,11.5% 56.8%,11.3% 53.4%,11.5% 50.0%,11.9% 46.7%,12.8% 43.4%,14.0% 40.4%,15.6% 37.5%,17.6% 34.9%,19.7% 32.5%,22.0% 30.4%,24.2% 28.3%,26.3% 26.3%,28.4% 24.3%,30.6% 22.3%,32.8% 20.2%,35.2% 18.3%,37.8% 16.5%,40.6% 14.8%,43.6% 13.4%,46.7% 12.4%,50.0% 11.7%,53.4% 11.4%,56.8% 11.6%,60.1% 12.3%,63.4% 13.2%,66.6% 14.3%,69.7% 15.8%,72.7% 17.5%,75.6% 19.5%,78.2% 21.8%,80.6% 24.3%,82.8% 27.1%,84.7% 30.0%,86.4% 33.0%,87.7% 36.3%,88.5% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  32.97% { clip-path: polygon(88.6% 50.0%,87.9% 53.3%,86.8% 56.5%,85.5% 59.5%,83.9% 62.4%,82.1% 65.0%,80.1% 67.4%,77.9% 69.6%,75.8% 71.7%,73.7% 73.7%,71.6% 75.8%,69.5% 77.9%,67.3% 80.0%,65.0% 82.1%,62.3% 83.9%,59.5% 85.5%,56.5% 86.8%,53.3% 87.9%,50.0% 88.6%,46.6% 89.1%,43.1% 89.0%,39.7% 88.6%,36.2% 87.9%,32.8% 86.8%,29.5% 85.4%,26.4% 83.7%,23.5% 81.6%,20.8% 79.2%,18.4% 76.5%,16.3% 73.6%,14.5% 70.5%,13.1% 67.2%,12.1% 63.8%,11.4% 60.3%,11.0% 56.9%,10.9% 53.4%,11.4% 50.0%,12.1% 46.7%,13.2% 43.5%,14.5% 40.5%,16.1% 37.7%,17.9% 35.0%,19.9% 32.6%,22.0% 30.4%,24.1% 28.3%,26.2% 26.2%,28.3% 24.1%,30.4% 22.0%,32.6% 19.9%,35.0% 17.9%,37.6% 16.0%,40.5% 14.5%,43.5% 13.1%,46.7% 12.1%,50.0% 11.4%,53.4% 10.9%,56.9% 11.0%,60.4% 11.4%,63.8% 12.0%,67.2% 13.1%,70.5% 14.5%,73.6% 16.2%,76.6% 18.3%,79.3% 20.7%,81.7% 23.4%,83.7% 26.4%,85.5% 29.5%,86.9% 32.8%,87.9% 36.2%,88.6% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  34.29% { clip-path: polygon(88.7% 50.0%,88.0% 53.3%,86.9% 56.5%,85.6% 59.5%,83.9% 62.4%,82.0% 64.9%,80.0% 67.3%,77.7% 69.4%,75.5% 71.4%,73.4% 73.4%,71.3% 75.3%,69.2% 77.4%,67.1% 79.6%,64.8% 81.7%,62.3% 83.7%,59.5% 85.4%,56.5% 86.8%,53.3% 88.0%,50.0% 88.8%,46.6% 89.2%,43.1% 89.2%,39.6% 88.7%,36.2% 88.0%,32.8% 86.9%,29.6% 85.4%,26.5% 83.6%,23.5% 81.6%,20.7% 79.3%,18.2% 76.7%,16.1% 73.8%,14.2% 70.7%,12.8% 67.4%,11.7% 63.9%,11.1% 60.4%,10.7% 56.9%,10.8% 53.4%,11.3% 50.0%,12.2% 46.7%,13.4% 43.5%,14.7% 40.6%,16.3% 37.7%,18.1% 35.1%,20.0% 32.7%,22.1% 30.4%,24.1% 28.3%,26.2% 26.2%,28.2% 24.1%,30.3% 21.9%,32.5% 19.7%,34.9% 17.7%,37.6% 15.9%,40.4% 14.3%,43.5% 13.0%,46.7% 12.0%,50.0% 11.2%,53.4% 10.7%,56.9% 10.7%,60.5% 11.0%,64.0% 11.5%,67.5% 12.5%,70.8% 13.9%,74.0% 15.7%,77.0% 17.8%,79.7% 20.3%,82.1% 23.0%,84.2% 26.1%,85.8% 29.3%,87.1% 32.7%,88.0% 36.2%,88.6% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  35.82% { clip-path: polygon(88.7% 50.0%,88.0% 53.3%,86.9% 56.5%,85.6% 59.5%,83.9% 62.4%,82.1% 64.9%,80.0% 67.3%,77.8% 69.4%,75.6% 71.5%,73.4% 73.4%,71.3% 75.4%,69.3% 77.5%,67.1% 79.7%,64.8% 81.8%,62.3% 83.7%,59.5% 85.4%,56.5% 86.8%,53.3% 88.0%,50.0% 88.8%,46.6% 89.2%,43.1% 89.2%,39.6% 88.7%,36.2% 88.0%,32.8% 86.9%,29.6% 85.4%,26.4% 83.6%,23.5% 81.6%,20.7% 79.3%,18.3% 76.6%,16.1% 73.7%,14.3% 70.6%,12.8% 67.3%,11.8% 63.9%,11.1% 60.4%,10.8% 56.9%,10.8% 53.4%,11.3% 50.0%,12.2% 46.7%,13.3% 43.5%,14.7% 40.5%,16.3% 37.7%,18.0% 35.1%,20.0% 32.7%,22.1% 30.4%,24.1% 28.3%,26.2% 26.2%,28.2% 24.1%,30.3% 21.9%,32.5% 19.8%,34.9% 17.7%,37.6% 15.9%,40.4% 14.3%,43.5% 13.0%,46.7% 12.0%,50.0% 11.2%,53.4% 10.8%,56.9% 10.7%,60.4% 11.0%,64.0% 11.6%,67.4% 12.6%,70.8% 14.0%,74.0% 15.8%,76.9% 17.9%,79.6% 20.4%,82.0% 23.1%,84.1% 26.1%,85.8% 29.3%,87.1% 32.7%,88.0% 36.2%,88.6% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  37.80% { clip-path: polygon(88.6% 50.0%,87.9% 53.3%,86.9% 56.5%,85.5% 59.5%,83.9% 62.4%,82.1% 65.0%,80.1% 67.4%,77.9% 69.5%,75.8% 71.6%,73.7% 73.7%,71.6% 75.7%,69.5% 77.8%,67.3% 80.0%,64.9% 82.0%,62.3% 83.9%,59.5% 85.5%,56.5% 86.8%,53.3% 87.9%,50.0% 88.7%,46.6% 89.1%,43.1% 89.0%,39.7% 88.6%,36.2% 87.9%,32.8% 86.9%,29.5% 85.4%,26.4% 83.7%,23.5% 81.6%,20.8% 79.2%,18.4% 76.5%,16.3% 73.6%,14.5% 70.5%,13.1% 67.2%,12.0% 63.8%,11.3% 60.4%,10.9% 56.9%,10.9% 53.4%,11.4% 50.0%,12.1% 46.7%,13.2% 43.5%,14.5% 40.5%,16.1% 37.7%,17.9% 35.0%,19.9% 32.6%,22.0% 30.4%,24.1% 28.3%,26.2% 26.2%,28.3% 24.1%,30.4% 22.0%,32.6% 19.9%,35.0% 17.8%,37.6% 16.0%,40.5% 14.4%,43.5% 13.1%,46.7% 12.1%,50.0% 11.3%,53.4% 10.9%,56.9% 10.9%,60.4% 11.3%,63.8% 12.0%,67.2% 13.0%,70.5% 14.4%,73.7% 16.2%,76.6% 18.3%,79.3% 20.7%,81.7% 23.4%,83.8% 26.3%,85.5% 29.5%,86.9% 32.8%,87.9% 36.2%,88.6% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  40.22% { clip-path: polygon(88.6% 50.0%,87.9% 53.3%,86.8% 56.5%,85.5% 59.5%,83.9% 62.3%,82.1% 65.0%,80.1% 67.4%,78.0% 69.6%,75.9% 71.7%,73.8% 73.8%,71.7% 75.9%,69.6% 78.0%,67.4% 80.2%,65.0% 82.2%,62.4% 84.0%,59.5% 85.5%,56.5% 86.8%,53.3% 87.9%,50.0% 88.6%,46.6% 89.0%,43.1% 89.0%,39.7% 88.6%,36.2% 87.9%,32.8% 86.8%,29.5% 85.4%,26.4% 83.7%,23.5% 81.6%,20.8% 79.2%,18.4% 76.5%,16.3% 73.6%,14.6% 70.4%,13.2% 67.2%,12.1% 63.8%,11.5% 60.3%,11.0% 56.9%,11.0% 53.4%,11.4% 50.0%,12.1% 46.7%,13.1% 43.5%,14.5% 40.5%,16.0% 37.6%,17.9% 35.0%,19.9% 32.6%,22.0% 30.4%,24.1% 28.3%,26.2% 26.2%,28.3% 24.1%,30.4% 22.0%,32.6% 19.9%,35.0% 17.9%,37.7% 16.1%,40.5% 14.5%,43.5% 13.2%,46.7% 12.1%,50.0% 11.4%,53.4% 11.0%,56.9% 11.0%,60.3% 11.5%,63.8% 12.2%,67.2% 13.2%,70.4% 14.6%,73.5% 16.4%,76.5% 18.5%,79.2% 20.8%,81.5% 23.5%,83.6% 26.4%,85.4% 29.6%,86.8% 32.8%,87.9% 36.2%,88.6% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  42.86% { clip-path: polygon(88.6% 50.0%,87.9% 53.3%,86.8% 56.5%,85.5% 59.5%,83.9% 62.4%,82.1% 65.0%,80.1% 67.4%,78.0% 69.6%,75.9% 71.7%,73.8% 73.8%,71.7% 75.9%,69.6% 78.0%,67.4% 80.1%,65.0% 82.1%,62.4% 83.9%,59.5% 85.5%,56.5% 86.8%,53.3% 87.9%,50.0% 88.6%,46.6% 89.0%,43.1% 89.0%,39.7% 88.6%,36.2% 87.9%,32.8% 86.8%,29.5% 85.4%,26.4% 83.7%,23.5% 81.6%,20.8% 79.2%,18.4% 76.5%,16.3% 73.6%,14.6% 70.5%,13.2% 67.2%,12.1% 63.8%,11.4% 60.3%,11.0% 56.9%,11.0% 53.4%,11.4% 50.0%,12.1% 46.7%,13.2% 43.5%,14.5% 40.5%,16.1% 37.6%,17.9% 35.0%,19.9% 32.6%,22.0% 30.4%,24.1% 28.3%,26.2% 26.2%,28.3% 24.1%,30.4% 22.0%,32.6% 19.9%,35.0% 17.9%,37.6% 16.1%,40.5% 14.5%,43.5% 13.2%,46.7% 12.1%,50.0% 11.4%,53.4% 11.0%,56.9% 11.0%,60.3% 11.4%,63.8% 12.1%,67.2% 13.2%,70.5% 14.6%,73.6% 16.3%,76.5% 18.4%,79.2% 20.8%,81.6% 23.5%,83.7% 26.4%,85.4% 29.5%,86.8% 32.8%,87.9% 36.2%,88.6% 39.7%,89.0% 43.1%,89.0% 46.6%); }
  43.96% { clip-path: polygon(88.7% 50.0%,87.9% 53.3%,86.6% 56.5%,85.1% 59.4%,83.5% 62.2%,81.8% 64.8%,80.1% 67.4%,78.3% 69.8%,76.5% 72.2%,74.5% 74.5%,72.2% 76.5%,69.8% 78.3%,67.4% 80.1%,64.8% 81.8%,62.2% 83.5%,59.4% 85.1%,56.5% 86.6%,53.3% 87.9%,50.0% 88.7%,46.6% 88.9%,43.2% 88.4%,39.9% 87.6%,36.6% 86.7%,33.4% 85.6%,30.1% 84.4%,26.9% 82.9%,23.8% 81.2%,21.1% 78.9%,18.8% 76.2%,17.1% 73.1%,15.6% 69.9%,14.4% 66.6%,13.3% 63.4%,12.4% 60.1%,11.6% 56.8%,11.1% 53.4%,11.3% 50.0%,12.1% 46.7%,13.4% 43.5%,14.9% 40.6%,16.5% 37.8%,18.2% 35.2%,19.9% 32.6%,21.7% 30.2%,23.5% 27.8%,25.5% 25.5%,27.8% 23.5%,30.2% 21.7%,32.6% 19.9%,35.2% 18.2%,37.8% 16.5%,40.6% 14.9%,43.5% 13.4%,46.7% 12.1%,50.0% 11.3%,53.4% 11.1%,56.8% 11.6%,60.1% 12.4%,63.4% 13.3%,66.6% 14.4%,69.9% 15.6%,73.1% 17.1%,76.2% 18.8%,78.9% 21.1%,81.2% 23.8%,82.9% 26.9%,84.4% 30.1%,85.6% 33.4%,86.7% 36.6%,87.6% 39.9%,88.4% 43.2%,88.9% 46.6%); }
  45.05% { clip-path: polygon(88.9% 50.0%,88.0% 53.3%,86.2% 56.4%,84.4% 59.2%,82.6% 61.9%,81.1% 64.5%,80.0% 67.3%,78.9% 70.2%,77.7% 73.2%,75.8% 75.8%,73.2% 77.7%,70.2% 78.9%,67.3% 80.0%,64.5% 81.1%,61.9% 82.6%,59.2% 84.4%,56.4% 86.2%,53.3% 88.0%,50.0% 88.9%,46.6% 88.6%,43.4% 87.3%,40.4% 85.9%,37.5% 84.4%,34.4% 83.4%,31.2% 82.6%,27.9% 81.6%,24.5% 80.4%,21.6% 78.4%,19.6% 75.5%,18.4% 72.1%,17.4% 68.8%,16.6% 65.6%,15.6% 62.5%,14.1% 59.6%,12.7% 56.6%,11.4% 53.4%,11.1% 50.0%,12.0% 46.7%,13.8% 43.6%,15.6% 40.8%,17.4% 38.1%,18.9% 35.5%,20.0% 32.7%,21.1% 29.8%,22.3% 26.8%,24.2% 24.2%,26.8% 22.3%,29.8% 21.1%,32.7% 20.0%,35.5% 18.9%,38.1% 17.4%,40.8% 15.6%,43.6% 13.8%,46.7% 12.0%,50.0% 11.1%,53.4% 11.4%,56.6% 12.7%,59.6% 14.1%,62.5% 15.6%,65.6% 16.6%,68.8% 17.4%,72.1% 18.4%,75.5% 19.6%,78.4% 21.6%,80.4% 24.5%,81.6% 27.9%,82.6% 31.2%,83.4% 34.4%,84.4% 37.5%,85.9% 40.4%,87.3% 43.4%,88.6% 46.6%); }
  46.15% { clip-path: polygon(89.0% 50.0%,88.1% 53.3%,85.9% 56.3%,83.8% 59.1%,81.8% 61.6%,80.6% 64.3%,80.0% 67.3%,79.4% 70.6%,78.7% 74.1%,77.0% 77.0%,74.1% 78.7%,70.6% 79.4%,67.3% 80.0%,64.3% 80.6%,61.6% 81.8%,59.1% 83.8%,56.3% 85.9%,53.3% 88.1%,50.0% 89.0%,46.7% 88.3%,43.6% 86.3%,40.8% 84.3%,38.2% 82.5%,35.4% 81.4%,32.2% 80.9%,28.7% 80.4%,25.1% 79.7%,22.1% 77.9%,20.3% 74.9%,19.6% 71.3%,19.1% 67.8%,18.6% 64.6%,17.5% 61.8%,15.7% 59.2%,13.7% 56.4%,11.7% 53.3%,11.0% 50.0%,11.9% 46.7%,14.1% 43.7%,16.2% 40.9%,18.2% 38.4%,19.4% 35.7%,20.0% 32.7%,20.6% 29.4%,21.3% 25.9%,23.0% 23.0%,25.9% 21.3%,29.4% 20.6%,32.7% 20.0%,35.7% 19.4%,38.4% 18.2%,40.9% 16.2%,43.7% 14.1%,46.7% 11.9%,50.0% 11.0%,53.3% 11.7%,56.4% 13.7%,59.2% 15.7%,61.8% 17.5%,64.6% 18.6%,67.8% 19.1%,71.3% 19.6%,74.9% 20.3%,77.9% 22.1%,79.7% 25.1%,80.4% 28.7%,80.9% 32.2%,81.4% 35.4%,82.5% 38.2%,84.3% 40.8%,86.3% 43.6%,88.3% 46.7%); }
  47.25% { clip-path: polygon(89.1% 50.0%,88.1% 53.3%,85.7% 56.3%,83.4% 58.9%,81.3% 61.4%,80.2% 64.1%,80.0% 67.3%,79.7% 70.8%,79.4% 74.6%,77.7% 77.7%,74.6% 79.4%,70.8% 79.7%,67.3% 80.0%,64.1% 80.2%,61.4% 81.3%,58.9% 83.4%,56.3% 85.7%,53.3% 88.1%,50.0% 89.1%,46.7% 88.1%,43.7% 85.7%,41.1% 83.4%,38.6% 81.3%,35.9% 80.2%,32.7% 79.9%,29.2% 79.6%,25.4% 79.3%,22.4% 77.6%,20.7% 74.6%,20.4% 70.8%,20.1% 67.3%,19.8% 64.1%,18.7% 61.4%,16.6% 58.9%,14.3% 56.3%,11.9% 53.3%,10.9% 50.0%,11.9% 46.7%,14.3% 43.7%,16.6% 41.1%,18.7% 38.6%,19.8% 35.9%,20.0% 32.7%,20.3% 29.2%,20.6% 25.4%,22.3% 22.3%,25.4% 20.6%,29.2% 20.3%,32.7% 20.0%,35.9% 19.8%,38.6% 18.7%,41.1% 16.6%,43.7% 14.3%,46.7% 11.9%,50.0% 10.9%,53.3% 11.9%,56.3% 14.3%,58.9% 16.6%,61.4% 18.7%,64.1% 19.8%,67.3% 20.1%,70.8% 20.4%,74.6% 20.7%,77.6% 22.4%,79.3% 25.4%,79.6% 29.2%,79.9% 32.7%,80.2% 35.9%,81.3% 38.6%,83.4% 41.1%,85.7% 43.7%,88.1% 46.7%); }
  48.57% { clip-path: polygon(89.2% 50.0%,88.2% 53.3%,85.6% 56.3%,83.2% 58.9%,81.1% 61.3%,80.1% 64.0%,80.0% 67.3%,79.8% 70.9%,79.6% 74.9%,78.0% 78.0%,74.9% 79.6%,70.9% 79.8%,67.3% 80.0%,64.0% 80.1%,61.3% 81.1%,58.9% 83.2%,56.3% 85.6%,53.3% 88.2%,50.0% 89.2%,46.7% 88.1%,43.8% 85.4%,41.2% 83.0%,38.8% 80.8%,36.2% 79.6%,33.0% 79.5%,29.5% 79.3%,25.6% 79.1%,22.5% 77.5%,20.9% 74.4%,20.7% 70.5%,20.5% 67.0%,20.4% 63.8%,19.2% 61.2%,17.0% 58.8%,14.6% 56.2%,11.9% 53.3%,10.8% 50.0%,11.8% 46.7%,14.4% 43.7%,16.8% 41.1%,18.9% 38.7%,19.9% 36.0%,20.0% 32.7%,20.2% 29.1%,20.4% 25.1%,22.0% 22.0%,25.1% 20.4%,29.1% 20.2%,32.7% 20.0%,36.0% 19.9%,38.7% 18.9%,41.1% 16.8%,43.7% 14.4%,46.7% 11.8%,50.0% 10.8%,53.3% 11.9%,56.2% 14.6%,58.8% 17.0%,61.2% 19.2%,63.8% 20.4%,67.0% 20.5%,70.5% 20.7%,74.4% 20.9%,77.5% 22.5%,79.1% 25.6%,79.3% 29.5%,79.5% 33.0%,79.6% 36.2%,80.8% 38.8%,83.0% 41.2%,85.4% 43.8%,88.1% 46.7%); }
  50.11% { clip-path: polygon(89.2% 50.0%,88.2% 53.3%,85.6% 56.3%,83.3% 58.9%,81.2% 61.3%,80.1% 64.0%,80.0% 67.3%,79.8% 70.9%,79.6% 74.8%,78.0% 78.0%,74.8% 79.6%,70.9% 79.8%,67.3% 80.0%,64.0% 80.1%,61.3% 81.2%,58.9% 83.3%,56.3% 85.6%,53.3% 88.2%,50.0% 89.2%,46.7% 88.1%,43.8% 85.4%,41.1% 83.0%,38.8% 80.9%,36.1% 79.7%,32.9% 79.6%,29.4% 79.4%,25.5% 79.2%,22.5% 77.5%,20.8% 74.5%,20.6% 70.6%,20.4% 67.1%,20.3% 63.9%,19.1% 61.2%,17.0% 58.9%,14.6% 56.2%,11.9% 53.3%,10.8% 50.0%,11.8% 46.7%,14.4% 43.7%,16.7% 41.1%,18.8% 38.7%,19.9% 36.0%,20.0% 32.7%,20.2% 29.1%,20.4% 25.2%,22.0% 22.0%,25.2% 20.4%,29.1% 20.2%,32.7% 20.0%,36.0% 19.9%,38.7% 18.8%,41.1% 16.7%,43.7% 14.4%,46.7% 11.8%,50.0% 10.8%,53.3% 11.9%,56.2% 14.6%,58.9% 17.0%,61.2% 19.1%,63.9% 20.3%,67.1% 20.4%,70.6% 20.6%,74.5% 20.8%,77.5% 22.5%,79.2% 25.5%,79.4% 29.4%,79.6% 32.9%,79.7% 36.1%,80.9% 38.8%,83.0% 41.1%,85.4% 43.8%,88.1% 46.7%); }
  52.09% { clip-path: polygon(89.1% 50.0%,88.1% 53.3%,85.7% 56.3%,83.4% 58.9%,81.3% 61.4%,80.2% 64.1%,80.0% 67.3%,79.7% 70.8%,79.4% 74.7%,77.7% 77.7%,74.7% 79.4%,70.8% 79.7%,67.3% 80.0%,64.1% 80.2%,61.4% 81.3%,58.9% 83.4%,56.3% 85.7%,53.3% 88.1%,50.0% 89.1%,46.7% 88.1%,43.7% 85.6%,41.1% 83.3%,38.6% 81.2%,36.0% 80.1%,32.8% 79.9%,29.3% 79.6%,25.4% 79.3%,22.4% 77.6%,20.7% 74.6%,20.4% 70.7%,20.1% 67.2%,19.9% 64.0%,18.8% 61.4%,16.7% 58.9%,14.4% 56.3%,11.9% 53.3%,10.9% 50.0%,11.9% 46.7%,14.3% 43.7%,16.6% 41.1%,18.7% 38.6%,19.8% 35.9%,20.0% 32.7%,20.3% 29.2%,20.6% 25.3%,22.3% 22.3%,25.3% 20.6%,29.2% 20.3%,32.7% 20.0%,35.9% 19.8%,38.6% 18.7%,41.1% 16.6%,43.7% 14.3%,46.7% 11.9%,50.0% 10.9%,53.3% 11.9%,56.3% 14.4%,58.9% 16.7%,61.4% 18.8%,64.0% 19.9%,67.2% 20.1%,70.7% 20.4%,74.6% 20.7%,77.6% 22.4%,79.3% 25.4%,79.6% 29.3%,79.9% 32.8%,80.1% 36.0%,81.2% 38.6%,83.3% 41.1%,85.6% 43.7%,88.1% 46.7%); }
  54.51% { clip-path: polygon(89.1% 50.0%,88.1% 53.3%,85.7% 56.3%,83.4% 59.0%,81.4% 61.4%,80.3% 64.1%,80.0% 67.3%,79.7% 70.8%,79.3% 74.6%,77.6% 77.6%,74.6% 79.3%,70.8% 79.7%,67.3% 80.0%,64.1% 80.3%,61.4% 81.4%,59.0% 83.4%,56.3% 85.7%,53.3% 88.1%,50.0% 89.1%,46.7% 88.1%,43.7% 85.7%,41.0% 83.5%,38.6% 81.4%,35.9% 80.3%,32.7% 80.0%,29.2% 79.7%,25.4% 79.3%,22.3% 77.7%,20.7% 74.6%,20.3% 70.8%,20.0% 67.3%,19.7% 64.1%,18.6% 61.4%,16.5% 59.0%,14.3% 56.3%,11.9% 53.3%,10.9% 50.0%,11.9% 46.7%,14.3% 43.7%,16.6% 41.0%,18.6% 38.6%,19.7% 35.9%,20.0% 32.7%,20.3% 29.2%,20.7% 25.4%,22.4% 22.4%,25.4% 20.7%,29.2% 20.3%,32.7% 20.0%,35.9% 19.7%,38.6% 18.6%,41.0% 16.6%,43.7% 14.3%,46.7% 11.9%,50.0% 10.9%,53.3% 11.9%,56.3% 14.3%,59.0% 16.5%,61.4% 18.6%,64.1% 19.7%,67.3% 20.0%,70.8% 20.3%,74.6% 20.7%,77.7% 22.3%,79.3% 25.4%,79.7% 29.2%,80.0% 32.7%,80.3% 35.9%,81.4% 38.6%,83.5% 41.0%,85.7% 43.7%,88.1% 46.7%); }
  57.14% { clip-path: polygon(89.1% 50.0%,88.1% 53.3%,85.7% 56.3%,83.4% 59.0%,81.4% 61.4%,80.2% 64.1%,80.0% 67.3%,79.7% 70.8%,79.3% 74.6%,77.7% 77.7%,74.6% 79.3%,70.8% 79.7%,67.3% 80.0%,64.1% 80.2%,61.4% 81.4%,59.0% 83.4%,56.3% 85.7%,53.3% 88.1%,50.0% 89.1%,46.7% 88.1%,43.7% 85.7%,41.0% 83.4%,38.6% 81.4%,35.9% 80.2%,32.7% 80.0%,29.2% 79.7%,25.4% 79.3%,22.3% 77.7%,20.7% 74.6%,20.3% 70.8%,20.0% 67.3%,19.8% 64.1%,18.6% 61.4%,16.6% 59.0%,14.3% 56.3%,11.9% 53.3%,10.9% 50.0%,11.9% 46.7%,14.3% 43.7%,16.6% 41.0%,18.6% 38.6%,19.8% 35.9%,20.0% 32.7%,20.3% 29.2%,20.7% 25.4%,22.3% 22.3%,25.4% 20.7%,29.2% 20.3%,32.7% 20.0%,35.9% 19.8%,38.6% 18.6%,41.0% 16.6%,43.7% 14.3%,46.7% 11.9%,50.0% 10.9%,53.3% 11.9%,56.3% 14.3%,59.0% 16.6%,61.4% 18.6%,64.1% 19.8%,67.3% 20.0%,70.8% 20.3%,74.6% 20.7%,77.7% 22.3%,79.3% 25.4%,79.7% 29.2%,80.0% 32.7%,80.2% 35.9%,81.4% 38.6%,83.4% 41.0%,85.7% 43.7%,88.1% 46.7%); }
  58.24% { clip-path: polygon(88.3% 50.0%,87.5% 53.3%,85.7% 56.3%,84.1% 59.1%,82.7% 61.9%,81.9% 64.9%,81.6% 68.2%,81.2% 71.8%,80.5% 75.6%,78.7% 78.7%,75.6% 80.5%,71.8% 81.2%,68.2% 81.6%,64.9% 81.9%,61.9% 82.7%,59.1% 84.1%,56.3% 85.7%,53.3% 87.5%,50.0% 88.3%,46.7% 87.5%,43.7% 85.7%,40.9% 84.1%,38.1% 82.7%,35.1% 81.9%,31.8% 81.6%,28.2% 81.2%,24.4% 80.5%,21.3% 78.7%,19.5% 75.6%,18.8% 71.8%,18.4% 68.2%,18.1% 64.9%,17.3% 61.9%,15.9% 59.1%,14.3% 56.3%,12.5% 53.3%,11.7% 50.0%,12.5% 46.7%,14.3% 43.7%,15.9% 40.9%,17.3% 38.1%,18.1% 35.1%,18.4% 31.8%,18.8% 28.2%,19.5% 24.4%,21.3% 21.3%,24.4% 19.5%,28.2% 18.8%,31.8% 18.4%,35.1% 18.1%,38.1% 17.3%,40.9% 15.9%,43.7% 14.3%,46.7% 12.5%,50.0% 11.7%,53.3% 12.5%,56.3% 14.3%,59.1% 15.9%,61.9% 17.3%,64.9% 18.1%,68.2% 18.4%,71.8% 18.8%,75.6% 19.5%,78.7% 21.3%,80.5% 24.4%,81.2% 28.2%,81.6% 31.8%,81.9% 35.1%,82.7% 38.1%,84.1% 40.9%,85.7% 43.7%,87.5% 46.7%); }
  59.34% { clip-path: polygon(86.6% 50.0%,86.3% 53.2%,85.6% 56.3%,85.4% 59.5%,85.2% 62.8%,84.9% 66.3%,84.6% 70.0%,83.9% 73.7%,82.7% 77.5%,80.6% 80.6%,77.5% 82.7%,73.7% 83.9%,70.0% 84.6%,66.3% 84.9%,62.8% 85.1%,59.5% 85.4%,56.3% 85.6%,53.2% 86.3%,50.0% 86.6%,46.8% 86.3%,43.7% 85.6%,40.5% 85.4%,37.2% 85.2%,33.7% 84.9%,30.0% 84.6%,26.3% 83.9%,22.5% 82.7%,19.4% 80.6%,17.3% 77.5%,16.1% 73.7%,15.4% 70.0%,15.1% 66.3%,14.9% 62.8%,14.6% 59.5%,14.4% 56.3%,13.7% 53.2%,13.4% 50.0%,13.7% 46.8%,14.4% 43.7%,14.6% 40.5%,14.8% 37.2%,15.1% 33.7%,15.4% 30.0%,16.1% 26.3%,17.3% 22.5%,19.4% 19.4%,22.5% 17.3%,26.3% 16.1%,30.0% 15.4%,33.7% 15.1%,37.2% 14.9%,40.5% 14.6%,43.7% 14.4%,46.8% 13.7%,50.0% 13.4%,53.2% 13.7%,56.3% 14.4%,59.5% 14.6%,62.8% 14.8%,66.3% 15.1%,70.0% 15.4%,73.7% 16.1%,77.5% 17.3%,80.6% 19.4%,82.7% 22.5%,83.9% 26.3%,84.6% 30.0%,84.9% 33.7%,85.1% 37.2%,85.4% 40.5%,85.6% 43.7%,86.3% 46.8%); }
  60.44% { clip-path: polygon(85.2% 50.0%,85.3% 53.1%,85.6% 56.3%,86.5% 59.8%,87.3% 63.6%,87.6% 67.5%,87.3% 71.5%,86.3% 75.4%,84.7% 79.1%,82.3% 82.3%,79.1% 84.7%,75.4% 86.3%,71.5% 87.3%,67.5% 87.6%,63.6% 87.3%,59.8% 86.4%,56.3% 85.6%,53.1% 85.3%,50.0% 85.2%,46.9% 85.3%,43.7% 85.6%,40.2% 86.5%,36.4% 87.3%,32.5% 87.6%,28.5% 87.3%,24.6% 86.3%,20.9% 84.7%,17.7% 82.3%,15.3% 79.1%,13.7% 75.4%,12.7% 71.5%,12.4% 67.5%,12.7% 63.6%,13.6% 59.8%,14.4% 56.3%,14.7% 53.1%,14.8% 50.0%,14.7% 46.9%,14.4% 43.7%,13.5% 40.2%,12.7% 36.4%,12.4% 32.5%,12.7% 28.5%,13.7% 24.6%,15.3% 20.9%,17.7% 17.7%,20.9% 15.3%,24.6% 13.7%,28.5% 12.7%,32.5% 12.4%,36.4% 12.7%,40.2% 13.6%,43.7% 14.4%,46.9% 14.7%,50.0% 14.8%,53.1% 14.7%,56.3% 14.4%,59.8% 13.5%,63.6% 12.7%,67.5% 12.4%,71.5% 12.7%,75.4% 13.7%,79.1% 15.3%,82.3% 17.7%,84.7% 20.9%,86.3% 24.6%,87.3% 28.5%,87.6% 32.5%,87.3% 36.4%,86.4% 40.2%,85.6% 43.7%,85.3% 46.9%); }
  61.54% { clip-path: polygon(84.4% 50.0%,84.6% 53.0%,85.5% 56.3%,87.1% 60.0%,88.6% 64.1%,89.2% 68.3%,88.9% 72.5%,87.8% 76.4%,85.9% 80.1%,83.3% 83.3%,80.1% 85.9%,76.4% 87.8%,72.4% 88.9%,68.3% 89.2%,64.1% 88.6%,59.9% 87.1%,56.3% 85.5%,53.0% 84.6%,50.0% 84.4%,47.0% 84.6%,43.7% 85.5%,40.0% 87.1%,35.9% 88.6%,31.7% 89.2%,27.5% 88.9%,23.6% 87.8%,19.9% 85.9%,16.7% 83.3%,14.1% 80.1%,12.2% 76.4%,11.1% 72.4%,10.8% 68.3%,11.4% 64.1%,12.9% 59.9%,14.5% 56.3%,15.4% 53.0%,15.6% 50.0%,15.4% 47.0%,14.5% 43.7%,12.9% 40.0%,11.4% 35.9%,10.8% 31.7%,11.1% 27.5%,12.2% 23.6%,14.1% 19.9%,16.7% 16.7%,19.9% 14.1%,23.6% 12.2%,27.6% 11.1%,31.7% 10.8%,35.9% 11.4%,40.1% 12.9%,43.7% 14.5%,47.0% 15.4%,50.0% 15.6%,53.0% 15.4%,56.3% 14.5%,60.0% 12.9%,64.1% 11.4%,68.3% 10.8%,72.5% 11.1%,76.4% 12.2%,80.1% 14.1%,83.3% 16.7%,85.9% 19.9%,87.8% 23.6%,88.9% 27.6%,89.2% 31.7%,88.6% 35.9%,87.1% 40.1%,85.5% 43.7%,84.6% 47.0%); }
  62.86% { clip-path: polygon(84.0% 50.0%,84.4% 53.0%,85.5% 56.3%,87.4% 60.0%,89.2% 64.3%,89.9% 68.6%,89.6% 72.9%,88.4% 76.9%,86.4% 80.5%,83.7% 83.7%,80.5% 86.4%,76.9% 88.4%,72.9% 89.6%,68.6% 89.9%,64.3% 89.2%,60.0% 87.4%,56.3% 85.5%,53.0% 84.4%,50.0% 84.0%,47.0% 84.4%,43.7% 85.5%,40.0% 87.4%,35.7% 89.2%,31.4% 89.9%,27.1% 89.6%,23.1% 88.4%,19.5% 86.4%,16.3% 83.7%,13.6% 80.5%,11.6% 76.9%,10.4% 72.9%,10.1% 68.6%,10.8% 64.3%,12.6% 60.0%,14.5% 56.3%,15.6% 53.0%,16.0% 50.0%,15.6% 47.0%,14.5% 43.7%,12.6% 40.0%,10.8% 35.7%,10.1% 31.4%,10.4% 27.1%,11.6% 23.1%,13.6% 19.5%,16.3% 16.3%,19.5% 13.6%,23.1% 11.6%,27.1% 10.4%,31.4% 10.1%,35.7% 10.8%,40.0% 12.6%,43.7% 14.5%,47.0% 15.6%,50.0% 16.0%,53.0% 15.6%,56.3% 14.5%,60.0% 12.6%,64.3% 10.8%,68.6% 10.1%,72.9% 10.4%,76.9% 11.6%,80.5% 13.6%,83.7% 16.3%,86.4% 19.5%,88.4% 23.1%,89.6% 27.1%,89.9% 31.4%,89.2% 35.7%,87.4% 40.0%,85.5% 43.7%,84.4% 47.0%); }
  64.40% { clip-path: polygon(84.1% 50.0%,84.4% 53.0%,85.5% 56.3%,87.4% 60.0%,89.1% 64.2%,89.8% 68.6%,89.5% 72.8%,88.3% 76.8%,86.3% 80.4%,83.7% 83.7%,80.4% 86.3%,76.8% 88.3%,72.8% 89.5%,68.5% 89.8%,64.2% 89.1%,60.0% 87.4%,56.3% 85.5%,53.0% 84.4%,50.0% 84.1%,47.0% 84.4%,43.7% 85.5%,40.0% 87.4%,35.8% 89.1%,31.4% 89.8%,27.2% 89.5%,23.2% 88.3%,19.6% 86.3%,16.3% 83.7%,13.7% 80.4%,11.7% 76.8%,10.5% 72.8%,10.2% 68.5%,10.9% 64.2%,12.6% 60.0%,14.5% 56.3%,15.6% 53.0%,15.9% 50.0%,15.6% 47.0%,14.5% 43.7%,12.6% 40.0%,10.9% 35.8%,10.2% 31.4%,10.5% 27.2%,11.7% 23.2%,13.7% 19.6%,16.3% 16.3%,19.6% 13.7%,23.2% 11.7%,27.2% 10.5%,31.5% 10.2%,35.8% 10.9%,40.0% 12.6%,43.7% 14.5%,47.0% 15.6%,50.0% 15.9%,53.0% 15.6%,56.3% 14.5%,60.0% 12.6%,64.2% 10.9%,68.6% 10.2%,72.8% 10.5%,76.8% 11.7%,80.4% 13.7%,83.7% 16.3%,86.3% 19.6%,88.3% 23.2%,89.5% 27.2%,89.8% 31.5%,89.1% 35.8%,87.4% 40.0%,85.5% 43.7%,84.4% 47.0%); }
  66.37% { clip-path: polygon(84.3% 50.0%,84.6% 53.0%,85.5% 56.3%,87.2% 60.0%,88.7% 64.1%,89.3% 68.3%,89.0% 72.5%,87.8% 76.5%,85.9% 80.1%,83.3% 83.3%,80.1% 85.9%,76.5% 87.8%,72.5% 89.0%,68.3% 89.3%,64.1% 88.7%,60.0% 87.2%,56.3% 85.5%,53.0% 84.6%,50.0% 84.3%,47.0% 84.6%,43.7% 85.5%,40.0% 87.2%,35.9% 88.7%,31.7% 89.3%,27.5% 89.0%,23.5% 87.8%,19.9% 85.9%,16.7% 83.3%,14.1% 80.1%,12.2% 76.5%,11.0% 72.5%,10.7% 68.3%,11.3% 64.1%,12.8% 60.0%,14.5% 56.3%,15.4% 53.0%,15.7% 50.0%,15.4% 47.0%,14.5% 43.7%,12.8% 40.0%,11.3% 35.9%,10.7% 31.7%,11.0% 27.5%,12.2% 23.5%,14.1% 19.9%,16.7% 16.7%,19.9% 14.1%,23.5% 12.2%,27.5% 11.0%,31.7% 10.7%,35.9% 11.3%,40.0% 12.8%,43.7% 14.5%,47.0% 15.4%,50.0% 15.7%,53.0% 15.4%,56.3% 14.5%,60.0% 12.8%,64.1% 11.3%,68.3% 10.7%,72.5% 11.0%,76.5% 12.2%,80.1% 14.1%,83.3% 16.7%,85.9% 19.9%,87.8% 23.5%,89.0% 27.5%,89.3% 31.7%,88.7% 35.9%,87.2% 40.0%,85.5% 43.7%,84.6% 47.0%); }
  68.79% { clip-path: polygon(84.5% 50.0%,84.7% 53.0%,85.5% 56.3%,87.1% 59.9%,88.5% 64.0%,89.0% 68.2%,88.7% 72.4%,87.6% 76.3%,85.7% 80.0%,83.2% 83.2%,80.0% 85.7%,76.3% 87.6%,72.4% 88.7%,68.2% 89.0%,64.0% 88.5%,59.9% 87.0%,56.3% 85.5%,53.0% 84.7%,50.0% 84.5%,47.0% 84.7%,43.7% 85.5%,40.1% 87.1%,36.0% 88.5%,31.8% 89.0%,27.6% 88.7%,23.7% 87.6%,20.0% 85.7%,16.8% 83.2%,14.3% 80.0%,12.4% 76.3%,11.3% 72.4%,11.0% 68.2%,11.5% 64.0%,13.0% 59.9%,14.5% 56.3%,15.3% 53.0%,15.5% 50.0%,15.3% 47.0%,14.5% 43.7%,12.9% 40.1%,11.5% 36.0%,11.0% 31.8%,11.3% 27.6%,12.4% 23.7%,14.3% 20.0%,16.8% 16.8%,20.0% 14.3%,23.7% 12.4%,27.6% 11.3%,31.8% 11.0%,36.0% 11.5%,40.1% 13.0%,43.7% 14.5%,47.0% 15.3%,50.0% 15.5%,53.0% 15.3%,56.3% 14.5%,59.9% 12.9%,64.0% 11.5%,68.2% 11.0%,72.4% 11.3%,76.3% 12.4%,80.0% 14.3%,83.2% 16.8%,85.7% 20.0%,87.6% 23.7%,88.7% 27.6%,89.0% 31.8%,88.5% 36.0%,87.0% 40.1%,85.5% 43.7%,84.7% 47.0%); }
  71.43% { clip-path: polygon(84.4% 50.0%,84.7% 53.0%,85.5% 56.3%,87.1% 59.9%,88.6% 64.0%,89.1% 68.2%,88.8% 72.4%,87.7% 76.4%,85.8% 80.0%,83.2% 83.2%,80.0% 85.8%,76.4% 87.7%,72.4% 88.8%,68.2% 89.1%,64.0% 88.5%,59.9% 87.1%,56.3% 85.5%,53.0% 84.7%,50.0% 84.4%,47.0% 84.7%,43.7% 85.5%,40.1% 87.1%,36.0% 88.6%,31.8% 89.1%,27.6% 88.8%,23.6% 87.7%,20.0% 85.8%,16.8% 83.2%,14.2% 80.0%,12.3% 76.4%,11.2% 72.4%,10.9% 68.2%,11.5% 64.0%,12.9% 59.9%,14.5% 56.3%,15.3% 53.0%,15.6% 50.0%,15.3% 47.0%,14.5% 43.7%,12.9% 40.1%,11.4% 36.0%,10.9% 31.8%,11.2% 27.6%,12.3% 23.6%,14.2% 20.0%,16.8% 16.8%,20.0% 14.2%,23.6% 12.3%,27.6% 11.2%,31.8% 10.9%,36.0% 11.5%,40.1% 12.9%,43.7% 14.5%,47.0% 15.3%,50.0% 15.6%,53.0% 15.3%,56.3% 14.5%,59.9% 12.9%,64.0% 11.4%,68.2% 10.9%,72.4% 11.2%,76.4% 12.3%,80.0% 14.2%,83.2% 16.8%,85.8% 20.0%,87.7% 23.6%,88.8% 27.6%,89.1% 31.8%,88.5% 36.0%,87.1% 40.1%,85.5% 43.7%,84.7% 47.0%); }
  72.53% { clip-path: polygon(84.6% 50.0%,84.6% 53.0%,85.0% 56.2%,86.0% 59.6%,86.9% 63.4%,87.1% 67.3%,86.5% 71.1%,85.3% 74.7%,83.4% 78.0%,81.0% 81.0%,78.0% 83.4%,74.7% 85.3%,71.1% 86.5%,67.3% 87.1%,63.4% 86.9%,59.6% 86.0%,56.2% 85.0%,53.0% 84.6%,50.0% 84.6%,46.9% 85.1%,43.7% 86.0%,40.0% 87.4%,35.9% 88.7%,31.8% 89.1%,27.6% 88.7%,23.7% 87.6%,20.0% 85.7%,16.8% 83.2%,14.3% 80.0%,12.4% 76.3%,11.3% 72.4%,10.9% 68.2%,11.4% 64.1%,12.6% 60.0%,14.1% 56.3%,14.9% 53.1%,15.4% 50.0%,15.4% 47.0%,15.0% 43.8%,14.0% 40.4%,13.1% 36.6%,12.9% 32.7%,13.5% 28.9%,14.7% 25.3%,16.6% 22.0%,19.0% 19.0%,22.0% 16.6%,25.3% 14.7%,28.9% 13.5%,32.7% 12.9%,36.6% 13.1%,40.4% 14.0%,43.8% 15.0%,47.0% 15.4%,50.0% 15.4%,53.1% 14.9%,56.3% 14.0%,60.0% 12.6%,64.1% 11.3%,68.2% 10.9%,72.4% 11.3%,76.3% 12.4%,80.0% 14.3%,83.2% 16.8%,85.7% 20.0%,87.6% 23.7%,88.7% 27.6%,89.1% 31.8%,88.6% 35.9%,87.4% 40.0%,85.9% 43.7%,85.1% 46.9%); }
  73.63% { clip-path: polygon(85.0% 50.0%,84.4% 53.0%,84.1% 56.0%,84.0% 59.1%,83.9% 62.3%,83.3% 65.5%,82.2% 68.6%,80.8% 71.6%,79.0% 74.3%,76.8% 76.8%,74.3% 79.0%,71.6% 80.8%,68.6% 82.2%,65.5% 83.3%,62.3% 83.8%,59.1% 84.0%,56.0% 84.0%,53.0% 84.4%,50.0% 85.0%,46.9% 85.8%,43.5% 86.7%,39.8% 87.9%,35.9% 88.8%,31.8% 89.1%,27.7% 88.7%,23.7% 87.5%,20.1% 85.6%,16.9% 83.1%,14.4% 79.9%,12.5% 76.3%,11.3% 72.3%,10.9% 68.2%,11.2% 64.1%,12.1% 60.1%,13.3% 56.5%,14.2% 53.1%,15.0% 50.0%,15.6% 47.0%,15.9% 44.0%,16.0% 40.9%,16.1% 37.7%,16.7% 34.5%,17.8% 31.4%,19.2% 28.4%,21.0% 25.7%,23.2% 23.2%,25.7% 21.0%,28.4% 19.2%,31.4% 17.8%,34.5% 16.7%,37.7% 16.2%,40.9% 16.0%,44.0% 16.0%,47.0% 15.6%,50.0% 15.0%,53.1% 14.2%,56.5% 13.3%,60.2% 12.1%,64.1% 11.2%,68.2% 10.9%,72.3% 11.3%,76.3% 12.5%,79.9% 14.4%,83.1% 16.9%,85.6% 20.1%,87.5% 23.7%,88.7% 27.7%,89.1% 31.8%,88.8% 35.9%,87.9% 39.9%,86.7% 43.5%,85.8% 46.9%); }
  74.73% { clip-path: polygon(85.3% 50.0%,84.3% 53.0%,83.2% 55.9%,82.2% 58.6%,81.2% 61.3%,79.9% 64.0%,78.5% 66.5%,76.9% 68.8%,75.1% 71.1%,73.2% 73.2%,71.1% 75.1%,68.8% 76.9%,66.5% 78.5%,64.0% 79.9%,61.3% 81.2%,58.6% 82.2%,55.9% 83.2%,53.0% 84.3%,50.0% 85.3%,46.8% 86.4%,43.4% 87.4%,39.7% 88.3%,35.8% 89.0%,31.8% 89.1%,27.7% 88.6%,23.8% 87.4%,20.2% 85.6%,17.0% 83.0%,14.4% 79.8%,12.6% 76.2%,11.4% 72.3%,10.9% 68.2%,11.0% 64.2%,11.7% 60.3%,12.6% 56.6%,13.6% 53.2%,14.7% 50.0%,15.7% 47.0%,16.8% 44.1%,17.8% 41.4%,18.8% 38.7%,20.1% 36.0%,21.5% 33.5%,23.1% 31.2%,24.9% 28.9%,26.8% 26.8%,28.9% 24.9%,31.2% 23.1%,33.5% 21.5%,36.0% 20.1%,38.7% 18.8%,41.4% 17.8%,44.1% 16.8%,47.0% 15.7%,50.0% 14.7%,53.2% 13.6%,56.6% 12.6%,60.3% 11.7%,64.2% 11.0%,68.2% 10.9%,72.3% 11.4%,76.2% 12.6%,79.8% 14.4%,83.0% 17.0%,85.6% 20.2%,87.4% 23.8%,88.6% 27.7%,89.1% 31.8%,89.0% 35.8%,88.3% 39.7%,87.4% 43.4%,86.4% 46.8%); }
  75.82% { clip-path: polygon(85.5% 50.0%,84.2% 53.0%,82.7% 55.8%,81.1% 58.3%,79.5% 60.7%,77.9% 63.0%,76.2% 65.1%,74.5% 67.2%,72.8% 69.1%,71.0% 71.0%,69.1% 72.8%,67.2% 74.5%,65.1% 76.2%,63.0% 77.9%,60.7% 79.5%,58.3% 81.1%,55.8% 82.7%,53.0% 84.2%,50.0% 85.5%,46.8% 86.8%,43.3% 87.8%,39.7% 88.6%,35.8% 89.1%,31.8% 89.1%,27.7% 88.5%,23.8% 87.4%,20.2% 85.5%,17.0% 83.0%,14.5% 79.8%,12.6% 76.2%,11.5% 72.3%,10.9% 68.2%,10.9% 64.2%,11.4% 60.3%,12.2% 56.7%,13.2% 53.2%,14.5% 50.0%,15.8% 47.0%,17.3% 44.2%,18.9% 41.7%,20.5% 39.3%,22.1% 37.0%,23.8% 34.9%,25.5% 32.8%,27.2% 30.9%,29.0% 29.0%,30.9% 27.2%,32.8% 25.5%,34.9% 23.8%,37.0% 22.1%,39.3% 20.5%,41.7% 18.9%,44.2% 17.3%,47.0% 15.8%,50.0% 14.5%,53.2% 13.2%,56.7% 12.2%,60.3% 11.4%,64.2% 10.9%,68.2% 10.9%,72.3% 11.5%,76.2% 12.6%,79.8% 14.5%,83.0% 17.0%,85.5% 20.2%,87.4% 23.8%,88.5% 27.7%,89.1% 31.8%,89.1% 35.8%,88.6% 39.7%,87.8% 43.3%,86.8% 46.8%); }
  77.14% { clip-path: polygon(85.6% 50.0%,84.1% 53.0%,82.5% 55.7%,80.7% 58.2%,78.8% 60.5%,77.0% 62.6%,75.2% 64.6%,73.5% 66.4%,71.7% 68.2%,70.0% 70.0%,68.2% 71.7%,66.4% 73.5%,64.6% 75.2%,62.6% 77.0%,60.5% 78.8%,58.2% 80.7%,55.7% 82.5%,53.0% 84.1%,50.0% 85.6%,46.8% 86.9%,43.3% 88.0%,39.6% 88.7%,35.8% 89.1%,31.8% 89.1%,27.8% 88.5%,23.9% 87.3%,20.2% 85.5%,17.1% 82.9%,14.5% 79.8%,12.7% 76.1%,11.5% 72.2%,10.9% 68.2%,10.9% 64.2%,11.3% 60.4%,12.0% 56.7%,13.1% 53.2%,14.4% 50.0%,15.9% 47.0%,17.5% 44.3%,19.3% 41.8%,21.2% 39.5%,23.0% 37.4%,24.8% 35.4%,26.5% 33.6%,28.3% 31.8%,30.0% 30.0%,31.8% 28.3%,33.6% 26.5%,35.4% 24.8%,37.4% 23.0%,39.5% 21.2%,41.8% 19.3%,44.3% 17.5%,47.0% 15.9%,50.0% 14.4%,53.2% 13.1%,56.7% 12.0%,60.4% 11.3%,64.2% 10.9%,68.2% 10.9%,72.2% 11.5%,76.1% 12.7%,79.8% 14.5%,82.9% 17.1%,85.5% 20.2%,87.3% 23.9%,88.5% 27.8%,89.1% 31.8%,89.1% 35.8%,88.7% 39.6%,88.0% 43.3%,86.9% 46.8%); }
  78.68% { clip-path: polygon(85.6% 50.0%,84.1% 53.0%,82.5% 55.7%,80.8% 58.2%,79.0% 60.5%,77.2% 62.7%,75.4% 64.7%,73.7% 66.6%,71.9% 68.4%,70.2% 70.2%,68.4% 71.9%,66.6% 73.7%,64.7% 75.4%,62.7% 77.2%,60.5% 79.0%,58.2% 80.8%,55.7% 82.5%,53.0% 84.1%,50.0% 85.6%,46.8% 86.9%,43.3% 88.0%,39.6% 88.7%,35.8% 89.1%,31.8% 89.1%,27.8% 88.5%,23.8% 87.3%,20.2% 85.5%,17.1% 82.9%,14.5% 79.8%,12.7% 76.2%,11.5% 72.2%,10.9% 68.2%,10.9% 64.2%,11.3% 60.4%,12.0% 56.7%,13.1% 53.2%,14.4% 50.0%,15.9% 47.0%,17.5% 44.3%,19.2% 41.8%,21.0% 39.5%,22.8% 37.3%,24.6% 35.3%,26.3% 33.4%,28.1% 31.6%,29.8% 29.8%,31.6% 28.1%,33.4% 26.3%,35.3% 24.6%,37.3% 22.8%,39.5% 21.0%,41.8% 19.2%,44.3% 17.5%,47.0% 15.9%,50.0% 14.4%,53.2% 13.1%,56.7% 12.0%,60.4% 11.3%,64.2% 10.9%,68.2% 10.9%,72.2% 11.5%,76.2% 12.7%,79.8% 14.5%,82.9% 17.1%,85.5% 20.2%,87.3% 23.8%,88.5% 27.8%,89.1% 31.8%,89.1% 35.8%,88.7% 39.6%,88.0% 43.3%,86.9% 46.8%); }
  80.66% { clip-path: polygon(85.5% 50.0%,84.2% 53.0%,82.7% 55.8%,81.1% 58.3%,79.5% 60.7%,77.8% 63.0%,76.1% 65.1%,74.4% 67.1%,72.6% 69.0%,70.8% 70.8%,69.0% 72.6%,67.1% 74.4%,65.1% 76.1%,63.0% 77.8%,60.7% 79.5%,58.3% 81.1%,55.8% 82.7%,53.0% 84.2%,50.0% 85.5%,46.8% 86.8%,43.3% 87.8%,39.7% 88.6%,35.8% 89.1%,31.8% 89.1%,27.8% 88.5%,23.8% 87.4%,20.2% 85.5%,17.1% 82.9%,14.5% 79.8%,12.6% 76.2%,11.5% 72.2%,10.9% 68.2%,10.9% 64.2%,11.4% 60.3%,12.2% 56.7%,13.2% 53.2%,14.5% 50.0%,15.8% 47.0%,17.3% 44.2%,18.9% 41.7%,20.5% 39.3%,22.2% 37.0%,23.9% 34.9%,25.6% 32.9%,27.4% 31.0%,29.2% 29.2%,31.0% 27.4%,32.9% 25.6%,34.9% 23.9%,37.0% 22.2%,39.3% 20.5%,41.7% 18.9%,44.2% 17.3%,47.0% 15.8%,50.0% 14.5%,53.2% 13.2%,56.7% 12.2%,60.3% 11.4%,64.2% 10.9%,68.2% 10.9%,72.2% 11.5%,76.2% 12.6%,79.8% 14.5%,82.9% 17.1%,85.5% 20.2%,87.4% 23.8%,88.5% 27.8%,89.1% 31.8%,89.1% 35.8%,88.6% 39.7%,87.8% 43.3%,86.8% 46.8%); }
  83.08% { clip-path: polygon(85.5% 50.0%,84.2% 53.0%,82.7% 55.8%,81.3% 58.4%,79.7% 60.8%,78.1% 63.1%,76.5% 65.3%,74.8% 67.3%,73.0% 69.3%,71.2% 71.2%,69.3% 73.0%,67.3% 74.8%,65.3% 76.5%,63.1% 78.1%,60.8% 79.7%,58.4% 81.3%,55.8% 82.7%,53.0% 84.2%,50.0% 85.5%,46.8% 86.7%,43.3% 87.8%,39.7% 88.6%,35.8% 89.0%,31.8% 89.1%,27.7% 88.5%,23.8% 87.4%,20.2% 85.5%,17.0% 83.0%,14.5% 79.8%,12.6% 76.2%,11.5% 72.3%,10.9% 68.2%,11.0% 64.2%,11.4% 60.3%,12.2% 56.7%,13.3% 53.2%,14.5% 50.0%,15.8% 47.0%,17.3% 44.2%,18.7% 41.6%,20.3% 39.2%,21.9% 36.9%,23.5% 34.7%,25.2% 32.7%,27.0% 30.7%,28.8% 28.8%,30.7% 27.0%,32.7% 25.2%,34.7% 23.5%,36.9% 21.9%,39.2% 20.3%,41.6% 18.7%,44.2% 17.3%,47.0% 15.8%,50.0% 14.5%,53.2% 13.3%,56.7% 12.2%,60.3% 11.4%,64.2% 11.0%,68.2% 10.9%,72.3% 11.5%,76.2% 12.6%,79.8% 14.5%,83.0% 17.0%,85.5% 20.2%,87.4% 23.8%,88.5% 27.7%,89.1% 31.8%,89.0% 35.8%,88.6% 39.7%,87.8% 43.3%,86.7% 46.8%); }
  85.71% { clip-path: polygon(85.5% 50.0%,84.2% 53.0%,82.7% 55.8%,81.2% 58.4%,79.6% 60.8%,78.0% 63.1%,76.4% 65.2%,74.7% 67.3%,72.9% 69.2%,71.1% 71.1%,69.2% 72.9%,67.3% 74.7%,65.2% 76.4%,63.1% 78.0%,60.8% 79.6%,58.4% 81.2%,55.8% 82.7%,53.0% 84.2%,50.0% 85.5%,46.8% 86.8%,43.3% 87.8%,39.7% 88.6%,35.8% 89.1%,31.8% 89.1%,27.7% 88.5%,23.8% 87.4%,20.2% 85.5%,17.0% 83.0%,14.5% 79.8%,12.6% 76.2%,11.5% 72.3%,10.9% 68.2%,10.9% 64.2%,11.4% 60.3%,12.2% 56.7%,13.2% 53.2%,14.5% 50.0%,15.8% 47.0%,17.3% 44.2%,18.8% 41.6%,20.4% 39.2%,22.0% 36.9%,23.6% 34.8%,25.3% 32.7%,27.1% 30.8%,28.9% 28.9%,30.8% 27.1%,32.7% 25.3%,34.8% 23.6%,36.9% 22.0%,39.2% 20.4%,41.6% 18.8%,44.2% 17.3%,47.0% 15.8%,50.0% 14.5%,53.2% 13.2%,56.7% 12.2%,60.3% 11.4%,64.2% 10.9%,68.2% 10.9%,72.3% 11.5%,76.2% 12.6%,79.8% 14.5%,83.0% 17.0%,85.5% 20.2%,87.4% 23.8%,88.5% 27.7%,89.1% 31.8%,89.1% 35.8%,88.6% 39.7%,87.8% 43.3%,86.8% 46.8%); }
  86.81% { clip-path: polygon(84.7% 50.0%,83.8% 53.0%,83.1% 55.8%,82.3% 58.7%,80.9% 61.3%,78.9% 63.5%,76.7% 65.4%,74.8% 67.3%,73.1% 69.4%,71.7% 71.7%,70.2% 74.1%,68.2% 76.0%,65.8% 77.4%,63.2% 78.4%,60.8% 79.5%,58.3% 81.0%,55.8% 82.8%,53.0% 84.8%,50.0% 86.2%,46.8% 86.9%,43.5% 87.0%,40.1% 87.0%,36.5% 87.2%,32.6% 87.4%,28.5% 87.3%,24.5% 86.4%,21.2% 84.4%,18.6% 81.4%,16.6% 78.0%,14.9% 74.6%,13.4% 71.2%,12.1% 67.7%,11.4% 64.0%,11.6% 60.3%,12.8% 56.6%,14.1% 53.1%,15.3% 50.0%,16.2% 47.0%,16.9% 44.2%,17.7% 41.3%,19.1% 38.7%,21.1% 36.5%,23.3% 34.6%,25.2% 32.7%,26.9% 30.6%,28.3% 28.3%,29.8% 25.9%,31.8% 24.0%,34.2% 22.6%,36.8% 21.6%,39.2% 20.5%,41.7% 19.0%,44.2% 17.2%,47.0% 15.2%,50.0% 13.8%,53.2% 13.1%,56.5% 13.0%,59.9% 13.0%,63.5% 12.8%,67.4% 12.6%,71.5% 12.7%,75.5% 13.6%,78.8% 15.6%,81.4% 18.6%,83.4% 22.0%,85.1% 25.4%,86.6% 28.8%,87.9% 32.3%,88.6% 36.0%,88.4% 39.7%,87.2% 43.4%,85.9% 46.9%); }
  87.91% { clip-path: polygon(83.0% 50.0%,83.0% 52.9%,83.8% 56.0%,84.4% 59.2%,83.3% 62.1%,80.4% 64.2%,77.3% 65.8%,75.0% 67.5%,73.6% 69.8%,72.9% 72.9%,72.0% 76.3%,70.0% 78.5%,66.9% 79.3%,63.6% 79.1%,60.7% 79.4%,58.2% 80.6%,55.8% 83.1%,53.1% 85.9%,50.0% 87.4%,46.8% 87.1%,43.8% 85.4%,40.9% 84.1%,37.7% 83.8%,34.0% 84.3%,29.8% 85.0%,25.8% 84.5%,23.0% 82.2%,21.6% 78.4%,20.5% 74.8%,19.0% 71.7%,16.9% 69.1%,14.3% 66.6%,12.3% 63.7%,12.1% 60.2%,13.8% 56.4%,15.8% 53.0%,17.0% 50.0%,17.0% 47.1%,16.2% 44.0%,15.6% 40.8%,16.7% 37.9%,19.6% 35.8%,22.7% 34.2%,25.0% 32.5%,26.4% 30.2%,27.1% 27.1%,28.0% 23.7%,30.0% 21.5%,33.1% 20.7%,36.4% 20.9%,39.3% 20.6%,41.8% 19.4%,44.2% 16.9%,46.9% 14.1%,50.0% 12.6%,53.2% 12.9%,56.2% 14.6%,59.1% 15.9%,62.3% 16.2%,66.0% 15.7%,70.2% 15.0%,74.2% 15.5%,77.0% 17.8%,78.4% 21.6%,79.5% 25.2%,81.0% 28.3%,83.1% 30.9%,85.7% 33.4%,87.7% 36.3%,87.9% 39.8%,86.2% 43.6%,84.2% 47.0%); }
  89.01% { clip-path: polygon(81.6% 50.0%,82.3% 52.8%,84.4% 56.1%,86.3% 59.7%,85.4% 62.9%,81.8% 64.8%,77.9% 66.1%,75.2% 67.6%,73.9% 70.1%,73.9% 73.9%,73.7% 78.2%,71.5% 80.7%,67.8% 80.9%,63.9% 79.7%,60.6% 79.2%,58.1% 80.3%,55.9% 83.2%,53.2% 86.9%,50.0% 88.5%,46.7% 87.3%,44.0% 84.1%,41.5% 81.6%,38.8% 80.8%,35.2% 81.7%,30.9% 83.1%,26.9% 82.9%,24.5% 80.4%,24.1% 75.9%,23.9% 71.9%,22.6% 69.2%,20.0% 67.3%,16.2% 65.8%,13.0% 63.5%,12.5% 60.1%,14.8% 56.2%,17.3% 52.9%,18.4% 50.0%,17.7% 47.2%,15.6% 43.9%,13.7% 40.3%,14.6% 37.1%,18.2% 35.2%,22.1% 33.9%,24.8% 32.4%,26.1% 29.9%,26.1% 26.1%,26.3% 21.8%,28.5% 19.3%,32.2% 19.1%,36.1% 20.3%,39.4% 20.8%,41.9% 19.7%,44.1% 16.8%,46.8% 13.1%,50.0% 11.5%,53.3% 12.7%,56.0% 15.9%,58.5% 18.4%,61.2% 19.2%,64.8% 18.3%,69.1% 16.9%,73.1% 17.1%,75.5% 19.6%,75.9% 24.1%,76.1% 28.1%,77.4% 30.8%,80.0% 32.7%,83.8% 34.2%,87.0% 36.5%,87.5% 39.9%,85.2% 43.8%,82.7% 47.1%); }
  90.11% { clip-path: polygon(80.8% 50.0%,81.9% 52.8%,84.8% 56.1%,87.4% 60.0%,86.6% 63.3%,82.7% 65.2%,78.2% 66.3%,75.3% 67.7%,74.2% 70.3%,74.5% 74.5%,74.6% 79.4%,72.5% 82.1%,68.4% 81.9%,64.0% 80.1%,60.6% 79.1%,58.1% 80.1%,55.9% 83.4%,53.3% 87.6%,50.0% 89.2%,46.7% 87.5%,44.1% 83.3%,42.0% 80.0%,39.4% 79.0%,36.0% 80.0%,31.6% 81.8%,27.6% 81.9%,25.5% 79.2%,25.7% 74.3%,26.0% 70.2%,24.9% 67.6%,21.9% 66.2%,17.4% 65.2%,13.5% 63.3%,12.7% 60.0%,15.3% 56.1%,18.2% 52.8%,19.2% 50.0%,18.1% 47.2%,15.2% 43.9%,12.6% 40.0%,13.4% 36.7%,17.3% 34.8%,21.8% 33.7%,24.7% 32.3%,25.8% 29.7%,25.5% 25.5%,25.4% 20.6%,27.5% 17.9%,31.6% 18.1%,36.0% 19.9%,39.4% 20.9%,41.9% 19.9%,44.1% 16.6%,46.7% 12.4%,50.0% 10.8%,53.3% 12.5%,55.9% 16.7%,58.0% 20.0%,60.6% 21.0%,64.0% 20.0%,68.4% 18.2%,72.4% 18.1%,74.5% 20.8%,74.3% 25.7%,74.0% 29.8%,75.1% 32.4%,78.1% 33.8%,82.6% 34.8%,86.5% 36.7%,87.3% 40.0%,84.7% 43.9%,81.8% 47.2%); }
  91.43% { clip-path: polygon(80.4% 50.0%,81.7% 52.8%,84.9% 56.2%,87.9% 60.2%,87.2% 63.5%,83.0% 65.4%,78.4% 66.4%,75.3% 67.7%,74.3% 70.4%,74.7% 74.7%,75.1% 79.9%,72.9% 82.7%,68.7% 82.4%,64.1% 80.3%,60.6% 79.1%,58.0% 80.0%,55.9% 83.4%,53.3% 87.8%,50.0% 89.5%,46.7% 87.5%,44.2% 82.9%,42.1% 79.3%,39.7% 78.2%,36.3% 79.3%,31.9% 81.3%,27.9% 81.5%,25.9% 78.7%,26.4% 73.6%,26.9% 69.4%,25.8% 66.9%,22.7% 65.8%,17.9% 65.0%,13.7% 63.2%,12.8% 60.0%,15.6% 56.1%,18.6% 52.8%,19.6% 50.0%,18.3% 47.2%,15.1% 43.8%,12.1% 39.8%,12.8% 36.5%,17.0% 34.6%,21.6% 33.6%,24.7% 32.3%,25.7% 29.6%,25.3% 25.3%,24.9% 20.1%,27.1% 17.3%,31.3% 17.6%,35.9% 19.7%,39.4% 20.9%,42.0% 20.0%,44.1% 16.6%,46.7% 12.2%,50.0% 10.5%,53.3% 12.5%,55.8% 17.1%,57.9% 20.7%,60.3% 21.8%,63.7% 20.7%,68.1% 18.7%,72.1% 18.5%,74.1% 21.3%,73.6% 26.4%,73.1% 30.6%,74.2% 33.1%,77.3% 34.2%,82.1% 35.0%,86.3% 36.8%,87.2% 40.0%,84.4% 43.9%,81.4% 47.2%); }
  92.97% { clip-path: polygon(80.5% 50.0%,81.7% 52.8%,84.9% 56.2%,87.8% 60.1%,87.1% 63.5%,83.0% 65.4%,78.4% 66.4%,75.3% 67.7%,74.3% 70.4%,74.7% 74.7%,75.0% 79.8%,72.8% 82.6%,68.6% 82.3%,64.1% 80.2%,60.6% 79.1%,58.1% 80.1%,55.9% 83.4%,53.3% 87.8%,50.0% 89.4%,46.7% 87.5%,44.2% 83.0%,42.1% 79.5%,39.7% 78.4%,36.3% 79.4%,31.9% 81.4%,27.9% 81.6%,25.8% 78.8%,26.2% 73.8%,26.7% 69.5%,25.6% 67.1%,22.5% 65.9%,17.8% 65.0%,13.6% 63.2%,12.8% 60.0%,15.5% 56.1%,18.5% 52.8%,19.5% 50.0%,18.3% 47.2%,15.1% 43.8%,12.2% 39.9%,12.9% 36.5%,17.0% 34.6%,21.6% 33.6%,24.7% 32.3%,25.7% 29.6%,25.3% 25.3%,25.0% 20.2%,27.2% 17.4%,31.4% 17.7%,35.9% 19.8%,39.4% 20.9%,41.9% 19.9%,44.1% 16.6%,46.7% 12.2%,50.0% 10.6%,53.3% 12.5%,55.8% 17.0%,57.9% 20.5%,60.3% 21.6%,63.7% 20.6%,68.1% 18.6%,72.1% 18.4%,74.2% 21.2%,73.8% 26.2%,73.3% 30.5%,74.4% 32.9%,77.5% 34.1%,82.2% 35.0%,86.4% 36.8%,87.2% 40.0%,84.5% 43.9%,81.5% 47.2%); }
  94.95% { clip-path: polygon(80.7% 50.0%,81.9% 52.8%,84.8% 56.1%,87.5% 60.0%,86.7% 63.4%,82.7% 65.2%,78.3% 66.3%,75.3% 67.7%,74.2% 70.3%,74.5% 74.5%,74.7% 79.4%,72.5% 82.1%,68.5% 82.0%,64.0% 80.1%,60.6% 79.1%,58.1% 80.1%,55.9% 83.4%,53.3% 87.6%,50.0% 89.2%,46.7% 87.5%,44.1% 83.2%,42.0% 80.0%,39.5% 78.9%,36.0% 79.9%,31.6% 81.8%,27.7% 81.9%,25.5% 79.1%,25.8% 74.2%,26.1% 70.1%,25.0% 67.5%,22.0% 66.2%,17.5% 65.2%,13.5% 63.3%,12.7% 60.0%,15.4% 56.1%,18.2% 52.8%,19.3% 50.0%,18.1% 47.2%,15.2% 43.9%,12.5% 40.0%,13.3% 36.6%,17.3% 34.8%,21.7% 33.7%,24.7% 32.3%,25.8% 29.7%,25.5% 25.5%,25.3% 20.6%,27.5% 17.9%,31.5% 18.0%,36.0% 19.9%,39.4% 20.9%,41.9% 19.9%,44.1% 16.6%,46.7% 12.4%,50.0% 10.8%,53.3% 12.5%,55.9% 16.8%,58.0% 20.0%,60.5% 21.1%,64.0% 20.1%,68.4% 18.2%,72.3% 18.1%,74.5% 20.9%,74.2% 25.8%,73.9% 29.9%,75.0% 32.5%,78.0% 33.8%,82.5% 34.8%,86.5% 36.7%,87.3% 40.0%,84.6% 43.9%,81.8% 47.2%); }
  97.36% { clip-path: polygon(80.9% 50.0%,81.9% 52.8%,84.7% 56.1%,87.3% 60.0%,86.5% 63.3%,82.6% 65.2%,78.2% 66.3%,75.3% 67.7%,74.2% 70.3%,74.4% 74.4%,74.5% 79.2%,72.4% 81.9%,68.4% 81.8%,64.0% 80.1%,60.6% 79.1%,58.1% 80.1%,55.9% 83.4%,53.3% 87.5%,50.0% 89.1%,46.7% 87.4%,44.1% 83.4%,41.9% 80.2%,39.4% 79.2%,35.9% 80.2%,31.5% 82.0%,27.6% 82.1%,25.4% 79.3%,25.5% 74.5%,25.8% 70.3%,24.6% 67.8%,21.7% 66.4%,17.3% 65.3%,13.4% 63.3%,12.7% 60.0%,15.3% 56.1%,18.1% 52.8%,19.1% 50.0%,18.1% 47.2%,15.3% 43.9%,12.7% 40.0%,13.5% 36.7%,17.4% 34.8%,21.8% 33.7%,24.7% 32.3%,25.8% 29.7%,25.6% 25.6%,25.5% 20.8%,27.6% 18.1%,31.6% 18.2%,36.0% 19.9%,39.4% 20.9%,41.9% 19.9%,44.1% 16.6%,46.7% 12.5%,50.0% 10.9%,53.3% 12.6%,55.9% 16.6%,58.1% 19.8%,60.6% 20.8%,64.1% 19.8%,68.5% 18.0%,72.4% 17.9%,74.6% 20.7%,74.5% 25.5%,74.2% 29.7%,75.4% 32.2%,78.3% 33.6%,82.7% 34.7%,86.6% 36.7%,87.3% 40.0%,84.7% 43.9%,81.9% 47.2%); }
  100.00% { clip-path: polygon(80.8% 50.0%,81.9% 52.8%,84.7% 56.1%,87.3% 60.0%,86.6% 63.3%,82.6% 65.2%,78.2% 66.3%,75.3% 67.7%,74.2% 70.3%,74.4% 74.4%,74.6% 79.3%,72.4% 82.0%,68.4% 81.9%,64.0% 80.1%,60.6% 79.1%,58.1% 80.1%,55.9% 83.4%,53.3% 87.5%,50.0% 89.1%,46.7% 87.5%,44.1% 83.3%,41.9% 80.1%,39.4% 79.1%,36.0% 80.1%,31.6% 81.9%,27.6% 82.0%,25.4% 79.3%,25.6% 74.4%,25.9% 70.3%,24.7% 67.7%,21.8% 66.3%,17.3% 65.2%,13.4% 63.3%,12.7% 60.0%,15.3% 56.1%,18.1% 52.8%,19.2% 50.0%,18.1% 47.2%,15.3% 43.9%,12.7% 40.0%,13.4% 36.7%,17.4% 34.8%,21.8% 33.7%,24.7% 32.3%,25.8% 29.7%,25.6% 25.6%,25.4% 20.7%,27.6% 18.0%,31.6% 18.1%,36.0% 19.9%,39.4% 20.9%,41.9% 19.9%,44.1% 16.6%,46.7% 12.5%,50.0% 10.9%,53.3% 12.5%,55.9% 16.7%,58.1% 19.9%,60.6% 20.9%,64.0% 19.9%,68.4% 18.1%,72.4% 18.0%,74.6% 20.7%,74.4% 25.6%,74.1% 29.7%,75.3% 32.3%,78.2% 33.7%,82.7% 34.8%,86.6% 36.7%,87.3% 40.0%,84.7% 43.9%,81.9% 47.2%); }
}
.osk-shapemorph{margin-left:4px;vertical-align:text-bottom}
"""

EXTRA_WIDE = {"segments", "pingpong", "knight"}
EXTRA_DISPLAY = {
    k: "inline-flex"
    for k in (
        "squarejump",
        "rain",
        "spectrum",
        "bars3",
        "binary",
        "segments",
        "traffic",
        "thought",
        "diamonds",
        "snow",
    )
}
EXTRA_DISPLAY.update({"matrix": "inline-grid", "quad": "inline-grid"})

_TRACE = 'd="{d}"'


def _trace(cls, vb, d):
    return (
        f'<span class="osk-{cls}"><svg viewBox="{vb}" aria-hidden="true">'
        f'<path class="t" d="{d}"/><path class="a" pathLength="100" d="{d}"/></svg></span>'
    )


EXTRA_MARKUP = "".join(
    [
        f'<span class="osk-spiral">{_s(8)}</span>',
        '<span class="osk-target"></span>',
        f'<span class="osk-squarejump">{_s(3)}</span>',
        '<span class="osk-seesaw"></span>',
        '<span class="osk-propeller"></span>',
        '<span class="osk-cog"></span>',
        '<span class="osk-dotted"></span>',
        f'<span class="osk-ios">{_s(12)}</span>',
        f'<span class="osk-comet">{_s(6)}</span>',
        '<span class="osk-marquee"></span>',
        '<span class="osk-flame"></span>',
        '<span class="osk-drop"></span>',
        f'<span class="osk-rain">{_s(5)}</span>',
        '<span class="osk-fill"></span>',
        '<span class="osk-battery"><span></span></span>',
        '<span class="osk-moon"></span>',
        f'<span class="osk-sun">{_s(8)}</span>',
        '<span class="osk-heart"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 21s-8-5.2-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.8-8 11-8 11z"/></svg></span>',
        '<span class="osk-star"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l2.9 6.9 7.1.6-5.4 4.7 1.7 7.1L12 17.6 5.7 21.3l1.7-7.1L2 9.5l7.1-.6z"/></svg></span>',
        f'<span class="osk-spectrum">{_s(7)}</span>',
        f'<span class="osk-bars3">{_s(3)}</span>',
        f'<span class="osk-swap">{_s(2)}</span>',
        f'<span class="osk-trio">{_s(3)}</span>',
        '<span class="osk-satellite"><span></span></span>',
        f'<span class="osk-atom">{_s(3)}</span>',
        f'<span class="osk-binary">{_s(5)}</span>',
        f'<span class="osk-segments">{_s(6)}</span>',
        '<span class="osk-zigzag"><svg viewBox="0 0 24 12" aria-hidden="true"><path pathLength="50" d="M0 10L4 2L8 10L12 2L16 10L20 2L24 10"/></svg></span>',
        _trace("squaretrace", "0 0 16 16", "M2.5 2.5H13.5V13.5H2.5Z"),
        _trace("hexagon", "0 0 16 16", "M8 1.5L14 5V11L8 14.5L2 11V5Z"),
        '<span class="osk-pingpong"><span></span></span>',
        f'<span class="osk-traffic">{_s(3)}</span>',
        '<span class="osk-search"></span>',
        f'<span class="osk-matrix">{_s(16)}</span>',
        '<span class="osk-rotsq"></span>',
        f'<span class="osk-quad">{_s(4)}</span>',
        '<span class="osk-knight"></span>',
        f'<span class="osk-thought">{_s(3)}</span>',
        f'<span class="osk-diamonds">{_s(3)}</span>',
        f'<span class="osk-snow">{_s(4)}</span>',
    ]
)

# Too wide for the small Thinking header icon.
_WIDE = {"progress", "stripes", "pacman", "typewriter"} | EXTRA_WIDE
MORE_DISPLAY = {k: "inline-block" for k in MORE_STYLE_NAMES}
for _k in ("dna", "dotwave", "chart", "lines", "stairs", "cradle"):
    MORE_DISPLAY[_k] = "inline-flex"
MORE_DISPLAY["squares"] = "inline-grid"
MORE_DISPLAY.update(EXTRA_DISPLAY)
MORE_DISPLAY.update({"domino": "inline-flex", "pulsesq": "inline-flex"})


def _sorted_names(d, first):
    head = {k: d[k] for k in first if k in d}
    rest = sorted(
        ((k, v) for k, v in d.items() if k not in head), key=lambda kv: kv[1].lower()
    )
    return {**head, **dict(rest)}


STYLE_NAMES.update(MORE_STYLE_NAMES)
STYLE_NAMES["random"] = "Random (new each message)"
THINK_NAMES["random"] = "Random (new each time)"
THINK_NAMES.update({k: v for k, v in MORE_STYLE_NAMES.items() if k not in _WIDE})
DISPLAY.update(MORE_DISPLAY)
NEW_STYLES.extend(MORE_STYLE_NAMES)
STYLE_NAMES = _sorted_names(STYLE_NAMES, ("default", "random"))
THINK_NAMES = _sorted_names(THINK_NAMES, ("default", "none", "random"))
STYLE_LITERAL = Literal[tuple(STYLE_NAMES)]
THINK_LITERAL = Literal[tuple(THINK_NAMES)]

MORE_MARKUP = "".join(
    [
        '<span class="osk-dualring"></span>',
        f'<span class="osk-chase">{_s(8)}</span>',
        f'<span class="osk-dna">{_s(5)}</span>',
        '<span class="osk-pendulum"><span></span></span>',
        f'<span class="osk-cradle">{_s(5)}</span>',
        '<span class="osk-progress"><span></span></span>',
        '<span class="osk-stripes"></span>',
        '<span class="osk-hourglass"><svg viewBox="0 0 12 16" aria-hidden="true"><path d="M1 1h10M1 15h10M2 1c0 5 4 5 4 7s-4 2-4 7M10 1c0 5-4 5-4 7s4 2 4 7"/></svg></span>',
        '<span class="osk-clock"></span>',
        '<span class="osk-radar"></span>',
        '<span class="osk-pulsering"></span>',
        f'<span class="osk-squares">{_s(4)}</span>',
        '<span class="osk-diamond"></span>',
        '<span class="osk-sine"><svg viewBox="0 0 32 12" aria-hidden="true"><path pathLength="50" d="M0 6Q4 0 8 6T16 6T24 6T32 6"/></svg></span>',
        f'<span class="osk-dotwave">{_s(5)}</span>',
        f'<span class="osk-chart">{_s(4)}</span>',
        '<span class="osk-typewriter"><span></span></span>',
        '<span class="osk-underscore"></span>',
        f'<span class="osk-lines">{_s(3)}</span>',
        '<span class="osk-pacman"></span>',
        '<span class="osk-infinity"><svg viewBox="0 0 24 12" aria-hidden="true"><path class="t" d="M12 6C9 0 3 0 3 6S9 12 12 6S21 0 21 6S15 12 12 6Z"/><path class="a" pathLength="100" d="M12 6C9 0 3 0 3 6S9 12 12 6S21 0 21 6S15 12 12 6Z"/></svg></span>',
        '<span class="osk-triangle"><svg viewBox="0 0 16 16" aria-hidden="true"><path class="t" d="M8 2L14.5 13.5H1.5Z"/><path class="a" pathLength="100" d="M8 2L14.5 13.5H1.5Z"/></svg></span>',
        '<span class="osk-morph"></span>',
        f'<span class="osk-dotring">{_s(12)}</span>',
        f'<span class="osk-bubbles">{_s(3)}</span>',
        f'<span class="osk-stairs">{_s(4)}</span>',
        '<span class="osk-wifi"><svg viewBox="0 0 16 14" aria-hidden="true"><path d="M1 5Q8 -2 15 5"/><path d="M3.5 7.5Q8 3.5 12.5 7.5"/><path d="M6 10Q8 8.2 10 10"/><circle cx="8" cy="12.5" r="1.2"/></svg></span>',
        '<span class="osk-bolt"><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M9.5 0L2 9h5l-1.5 7L14 6.5H9z"/></svg></span>',
        f'<span class="osk-twinkle">{_s(4)}</span>',
        '<span class="osk-gradient"></span>',
        EXTRA_MARKUP,
        V2_MARKUP,
        V3_MARKUP,
    ]
)


def _ring_css(cls, n, r, d, dur, anim):
    h = d / 2
    out = [
        f".osk-{cls}{{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}}",
        f".osk-{cls}>span{{position:absolute;left:50%;top:50%;width:{d:g}px;height:{d:g}px;margin:-{h:g}px 0 0 -{h:g}px;border-radius:9999px;background:var(--osk-m);animation:{anim} {dur:g}s linear infinite}}",
    ]
    for i in range(n):
        out.append(
            f".osk-{cls}>span:nth-child({i + 1}){{transform:rotate({i * 360 / n:g}deg) translateY(-{r:g}px);animation-delay:-{dur * i / n:.3f}s}}"
        )
    return "\n".join(out)


MORE_CSS_STATIC = r"""
.osk-dualring{position:relative;box-sizing:border-box;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;border:2px solid transparent;border-top-color:var(--osk-m);border-bottom-color:var(--osk-m);border-radius:9999px;animation:osk-spin 1s linear infinite}
.osk-dualring::after{content:"";position:absolute;top:1px;right:1px;bottom:1px;left:1px;border:2px solid transparent;border-left-color:var(--osk-s);border-right-color:var(--osk-s);border-radius:9999px;animation:osk-spin .7s linear infinite reverse}
.osk-dna{align-items:center;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-dna>span{display:block;width:3px;height:3px;border-radius:9999px;background:var(--osk-m);animation:osk-dna 1.2s ease-in-out infinite}
.osk-dna>span:nth-child(even){background:var(--osk-s)}
.osk-dna>span:nth-child(2){animation-delay:-.15s}
.osk-dna>span:nth-child(3){animation-delay:-.3s}
.osk-dna>span:nth-child(4){animation-delay:-.45s}
.osk-dna>span:nth-child(5){animation-delay:-.6s}
.osk-pendulum{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-pendulum>span{position:absolute;top:0;left:50%;width:1.5px;height:11px;margin-left:-.75px;background:var(--osk-m);transform-origin:50% 0;animation:osk-swing 1s ease-in-out infinite alternate}
.osk-pendulum>span::after{content:"";position:absolute;left:-2.25px;bottom:-4px;width:6px;height:6px;border-radius:9999px;background:var(--osk-m)}
.osk-cradle{align-items:center;height:14px;margin:0 8px;vertical-align:text-bottom}
.osk-cradle>span{display:block;width:5px;height:5px;border-radius:9999px;background:var(--osk-m)}
.osk-cradle>span:first-child{animation:osk-cla 1.2s ease-in-out infinite}
.osk-cradle>span:last-child{animation:osk-clb 1.2s ease-in-out infinite}
.osk-progress{position:relative;width:48px;height:4px;margin-left:4px;vertical-align:middle;overflow:hidden;border-radius:2px;background:var(--osk-t)}
.osk-progress>span{position:absolute;top:0;left:0;height:100%;border-radius:2px;background:var(--osk-m);animation:osk-prog 1.6s ease-in-out infinite}
.osk-stripes{width:44px;height:6px;margin-left:4px;vertical-align:middle;border-radius:3px;background:repeating-linear-gradient(45deg,var(--osk-m) 0 4px,var(--osk-t) 4px 8px);background-size:11.314px 11.314px;animation:osk-stripe .6s linear infinite}
.osk-hourglass{width:10px;height:14px;margin:0 4px;vertical-align:text-bottom;color:var(--osk-m);animation:osk-hg 2s ease-in-out infinite}
.osk-hourglass>svg{display:block;width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:1.3;stroke-linecap:round}
.osk-clock{position:relative;box-sizing:border-box;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;border:1.5px solid var(--osk-m);border-radius:9999px}
.osk-clock::before,.osk-clock::after{content:"";position:absolute;left:50%;bottom:50%;width:1.5px;margin-left:-.75px;border-radius:1px;background:var(--osk-m);transform-origin:50% 100%}
.osk-clock::before{height:5px;animation:osk-spin 1s linear infinite}
.osk-clock::after{height:3.5px;animation:osk-spin 12s linear infinite}
.osk-radar{box-sizing:border-box;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;border:1.5px solid var(--osk-m);border-radius:9999px;background:conic-gradient(from 0deg,transparent 0 250deg,color-mix(in oklab,var(--osk-m) 75%,transparent) 360deg);animation:osk-spin 1.4s linear infinite}
.osk-pulsering{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-pulsering::before{content:"";position:absolute;left:50%;top:50%;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:9999px;background:var(--osk-s);animation:osk-breathe 1.2s ease-in-out infinite}
.osk-pulsering::after{content:"";position:absolute;top:0;right:0;bottom:0;left:0;box-sizing:border-box;border:2px solid var(--osk-m);border-radius:9999px;opacity:0;animation:osk-ripple 1.2s ease-out infinite}
.osk-squares{grid-template-columns:repeat(2,5px);gap:2px;margin-left:4px;vertical-align:text-bottom}
.osk-squares>span{display:block;width:5px;height:5px;border-radius:1px;background:var(--osk-m);animation:osk-sq 1.2s ease-in-out infinite}
.osk-squares>span:nth-child(2){animation-delay:.15s}
.osk-squares>span:nth-child(4){animation-delay:.3s}
.osk-squares>span:nth-child(3){animation-delay:.45s}
.osk-diamond{width:9px;height:9px;margin:0 5px;vertical-align:middle;background:var(--osk-m);animation:osk-dia 1.6s ease-in-out infinite}
.osk-sine{width:28px;height:12px;margin-left:4px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-sine>svg{display:block;width:100%;height:100%;overflow:visible}
.osk-sine path{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-dasharray:50;stroke-dashoffset:50;animation:osk-ecg 1.6s linear infinite}
.osk-dotwave{align-items:center;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-dotwave>span{display:block;width:4px;height:4px;border-radius:9999px;background:var(--osk-m);animation:osk-dw 1s ease-in-out infinite}
.osk-dotwave>span:nth-child(2){animation-delay:-.12s}
.osk-dotwave>span:nth-child(3){animation-delay:-.24s}
.osk-dotwave>span:nth-child(4){animation-delay:-.36s}
.osk-dotwave>span:nth-child(5){animation-delay:-.48s}
.osk-chart{align-items:flex-end;gap:2px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-chart>span{display:block;width:3px;height:100%;border-radius:1px;background:var(--osk-m);transform-origin:50% 100%;animation:osk-bar 1.4s ease-in-out infinite}
.osk-chart>span:nth-child(2){animation-delay:-.35s}
.osk-chart>span:nth-child(3){animation-delay:-.7s}
.osk-chart>span:nth-child(4){animation-delay:-1.05s}
.osk-typewriter{width:48px;height:12px;margin-left:4px;vertical-align:text-bottom}
.osk-typewriter>span{display:block;width:0;height:100%;box-sizing:border-box;border-right:2px solid var(--osk-s);background:repeating-linear-gradient(90deg,var(--osk-m) 0 4px,transparent 4px 6px) 0 50%/100% 3px no-repeat;animation:osk-type 2s steps(8) infinite}
.osk-underscore{width:8px;height:2px;margin-left:3px;vertical-align:baseline;background:var(--osk-m);animation:osk-blink 1s steps(1,end) infinite}
.osk-lines{flex-direction:column;justify-content:center;gap:3px;width:22px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-lines>span{display:block;height:2px;border-radius:1px;background:var(--osk-m);transform-origin:0 50%;animation:osk-roll 1.4s ease-in-out infinite}
.osk-lines>span:nth-child(2){animation-delay:-.25s}
.osk-lines>span:nth-child(3){animation-delay:-.5s}
.osk-pacman{position:relative;width:40px;height:14px;margin-left:4px;vertical-align:text-bottom;overflow:hidden}
.osk-pacman::before{content:"";position:absolute;left:0;top:0;width:14px;height:14px;border-radius:9999px;background:var(--osk-m);animation:osk-chomp .5s ease-in-out infinite alternate}
.osk-pacman::after{content:"";position:absolute;top:50%;left:18px;width:calc(100% + 8px);height:3px;margin-top:-1.5px;background:radial-gradient(circle,var(--osk-m) 1.4px,transparent 1.6px) 0 0/8px 3px repeat-x;animation:osk-dots .5s linear infinite}
.osk-infinity{width:24px;height:12px;margin-left:4px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-triangle{width:16px;height:16px;margin:0 3px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-infinity>svg,.osk-triangle>svg{display:block;width:100%;height:100%;overflow:visible}
.osk-infinity path,.osk-triangle path{fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.osk-infinity .t,.osk-triangle .t{opacity:.25}
.osk-infinity .a,.osk-triangle .a{stroke-dasharray:30 70;animation:osk-dash 1.4s linear infinite}
.osk-morph{width:12px;height:12px;margin:0 5px;vertical-align:middle;background:var(--osk-m);border-radius:60% 40% 30% 70%/60% 30% 70% 40%;animation:osk-morph 2.4s ease-in-out infinite}
.osk-bubbles{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-bubbles>span{position:absolute;bottom:0;box-sizing:border-box;border:1.5px solid var(--osk-m);border-radius:9999px;opacity:0;animation:osk-rise 1.8s ease-in infinite}
.osk-bubbles>span:nth-child(1){left:1px;width:5px;height:5px}
.osk-bubbles>span:nth-child(2){left:6px;width:4px;height:4px;animation-delay:.6s}
.osk-bubbles>span:nth-child(3){left:10px;width:5px;height:5px;animation-delay:1.2s}
.osk-stairs{align-items:flex-end;gap:2px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-stairs>span{display:block;width:3px;border-radius:1px;background:var(--osk-m);animation:osk-seq 1.2s ease-in-out infinite}
.osk-stairs>span:nth-child(1){height:4px}
.osk-stairs>span:nth-child(2){height:7px;animation-delay:.15s}
.osk-stairs>span:nth-child(3){height:10px;animation-delay:.3s}
.osk-stairs>span:nth-child(4){height:14px;animation-delay:.45s}
.osk-wifi{width:16px;height:14px;margin:0 3px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-wifi>svg{display:block;width:100%;height:100%;overflow:visible}
.osk-wifi path{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;animation:osk-seq 1.4s ease-in-out infinite}
.osk-wifi path:nth-child(1){animation-delay:.4s}
.osk-wifi path:nth-child(2){animation-delay:.2s}
.osk-wifi circle{fill:currentColor}
.osk-bolt{width:14px;height:14px;margin:0 3px;vertical-align:text-bottom;color:var(--osk-m);animation:osk-bolt 1.4s linear infinite}
.osk-bolt>svg{display:block;width:100%;height:100%}
.osk-twinkle{position:relative;width:18px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-twinkle>span{position:absolute;background:var(--osk-m);clip-path:polygon(50% 0,62% 38%,100% 50%,62% 62%,50% 100%,38% 62%,0 50%,38% 38%);animation:osk-tw 1.4s ease-in-out infinite}
.osk-twinkle>span:nth-child(1){left:1px;top:8px;width:5px;height:5px}
.osk-twinkle>span:nth-child(2){left:7px;top:0;width:6px;height:6px;animation-delay:.35s}
.osk-twinkle>span:nth-child(3){left:13px;top:8px;width:4px;height:4px;animation-delay:.7s}
.osk-twinkle>span:nth-child(4){left:6px;top:10px;width:4px;height:4px;animation-delay:1.05s}
.osk-gradient{width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;border-radius:9999px;background:conic-gradient(from 0deg,transparent,var(--osk-s));-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 2.5px),#000 calc(100% - 2px));mask:radial-gradient(farthest-side,transparent calc(100% - 2.5px),#000 calc(100% - 2px));animation:osk-spin .9s linear infinite}
@keyframes osk-fade{0%{opacity:1}100%{opacity:.15}}
@keyframes osk-tail{0%{opacity:1}50%,100%{opacity:.15}}
@keyframes osk-dna{0%,100%{transform:translateY(-5px) scale(.7)}50%{transform:translateY(5px) scale(1.2)}}
@keyframes osk-swing{from{transform:rotate(-35deg)}to{transform:rotate(35deg)}}
@keyframes osk-cla{0%,100%{transform:translateX(-6px)}25%,75%{transform:translateX(0)}}
@keyframes osk-clb{0%,25%,75%,100%{transform:translateX(0)}50%{transform:translateX(6px)}}
@keyframes osk-prog{0%{left:0;width:0}50%{left:0;width:75%}100%{left:100%;width:0}}
@keyframes osk-stripe{to{background-position:11.314px 0}}
@keyframes osk-hg{0%,40%{transform:rotate(0)}60%,100%{transform:rotate(180deg)}}
@keyframes osk-sq{0%,100%{opacity:.2;transform:scale(.7)}40%{opacity:1;transform:scale(1)}}
@keyframes osk-dia{0%,100%{transform:rotate(45deg);border-radius:1px}50%{transform:rotate(225deg) scale(.8);border-radius:50%}}
@keyframes osk-dw{0%,100%{transform:translateY(3px)}50%{transform:translateY(-3px)}}
@keyframes osk-bar{0%,100%{transform:scaleY(.25)}25%{transform:scaleY(1)}50%{transform:scaleY(.5)}75%{transform:scaleY(.8)}}
@keyframes osk-type{0%{width:0}75%,100%{width:100%}}
@keyframes osk-roll{0%,100%{transform:scaleX(.3)}50%{transform:scaleX(1)}}
@keyframes osk-chomp{from{clip-path:polygon(0 0,100% 0,100% 20%,50% 50%,100% 80%,100% 100%,0 100%)}to{clip-path:polygon(0 0,100% 0,100% 49%,50% 50%,100% 51%,100% 100%,0 100%)}}
@keyframes osk-dots{to{transform:translateX(-8px)}}
@keyframes osk-dash{to{stroke-dashoffset:-100}}
@keyframes osk-morph{0%,100%{border-radius:60% 40% 30% 70%/60% 30% 70% 40%;transform:rotate(0)}50%{border-radius:30% 60% 70% 40%/50% 60% 30% 60%;transform:rotate(180deg)}}
@keyframes osk-rise{0%{transform:translateY(0) scale(.6);opacity:0}20%{opacity:1}100%{transform:translateY(-13px) scale(1);opacity:0}}
@keyframes osk-bolt{0%,100%{opacity:.25;transform:scale(.85)}10%{opacity:1;transform:scale(1.1)}20%{opacity:.4}30%{opacity:1}60%{opacity:.25}}
@keyframes osk-tw{0%,100%{transform:scale(.3);opacity:.2}50%{transform:scale(1);opacity:1}}
"""


def _radial(cls, n, span_css, tf, container_extra=""):
    out = [
        f".osk-{cls}{{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;{container_extra}}}",
        f".osk-{cls}>span{{position:absolute;left:50%;top:50%;{span_css}}}",
    ]
    out += [f".osk-{cls}>span:nth-child({i + 1}){{{tf(i)}}}" for i in range(n)]
    return "\n".join(out)


def _delays(cls, values):
    return "\n".join(
        f".osk-{cls}>span:nth-child({i + 1}){{animation-delay:{v:g}s}}"
        for i, v in enumerate(values)
        if v
    )


_DOT = "border-radius:9999px;background:var(--osk-m)"
_ARC = [1, 0.65, 0.35]

EXTRA_CSS_STATIC = r"""
.osk-target{width:6px;height:6px;margin:0 7px;vertical-align:middle;border-radius:9999px;background:var(--osk-s);box-shadow:0 0 0 3px var(--osk-t),0 0 0 4.5px var(--osk-m);animation:osk-breathe 1.4s ease-in-out infinite}
.osk-squarejump{align-items:flex-end;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-squarejump>span{display:block;width:4px;height:4px;border-radius:1px;background:var(--osk-m);animation:osk-jump 1s ease-in-out infinite}
.osk-seesaw{position:relative;width:20px;height:12px;margin-left:4px;vertical-align:text-bottom}
.osk-seesaw::before{content:"";position:absolute;left:0;right:0;top:50%;height:2px;margin-top:-1px;border-radius:1px;background:var(--osk-m);animation:osk-rock 1.2s ease-in-out infinite alternate}
.osk-seesaw::after{content:"";position:absolute;left:50%;bottom:0;margin-left:-3px;border-left:3px solid transparent;border-right:3px solid transparent;border-bottom:5px solid var(--osk-t)}
.osk-propeller{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;animation:osk-spin .9s linear infinite}
.osk-propeller::before,.osk-propeller::after{content:"";position:absolute;left:50%;top:1px;bottom:1px;width:2px;margin-left:-1px;border-radius:1px;background:var(--osk-m)}
.osk-propeller::after{transform:rotate(90deg);opacity:.5}
.osk-cog{box-sizing:border-box;width:14px;height:14px;margin:0 4px;vertical-align:text-bottom;border:3px dashed var(--osk-m);border-radius:9999px;animation:osk-spin 3s linear infinite}
.osk-dotted{box-sizing:border-box;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;border:2px dotted var(--osk-m);border-radius:9999px;animation:osk-spin 2s linear infinite reverse}
.osk-marquee{width:28px;height:6px;margin-left:4px;vertical-align:middle;background:radial-gradient(circle,var(--osk-m) 1.6px,transparent 1.8px) 0 0/7px 6px repeat-x;animation:osk-mq .5s linear infinite}
.osk-flame{width:9px;height:13px;margin:0 4px;vertical-align:text-bottom;background:linear-gradient(to top,var(--osk-s),var(--osk-m));border-radius:50% 50% 50% 50%/70% 70% 30% 30%;transform-origin:50% 100%;animation:osk-flame .9s ease-in-out infinite alternate}
.osk-drop{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-drop::before{content:"";position:absolute;left:50%;top:0;width:5px;height:6px;margin-left:-2.5px;background:var(--osk-m);border-radius:50% 50% 50% 50%/70% 70% 30% 30%;animation:osk-fall 1.2s ease-in infinite}
.osk-drop::after{content:"";position:absolute;left:50%;bottom:0;width:14px;height:5px;margin-left:-7px;box-sizing:border-box;border:1.5px solid var(--osk-m);border-radius:50%;opacity:0;animation:osk-splash 1.2s ease-out infinite}
.osk-rain{align-items:flex-start;gap:3px;height:14px;margin-left:4px;overflow:hidden;vertical-align:text-bottom}
.osk-rain>span{display:block;width:1.5px;height:5px;border-radius:1px;background:var(--osk-m);animation:osk-rain .9s linear infinite}
.osk-fill{position:relative;box-sizing:border-box;width:10px;height:14px;margin:0 5px;vertical-align:text-bottom;border:1.5px solid var(--osk-m);border-radius:2px;overflow:hidden}
.osk-fill::before{content:"";position:absolute;left:0;right:0;bottom:0;height:100%;background:var(--osk-m);transform-origin:50% 100%;animation:osk-fill 1.6s ease-in-out infinite}
.osk-battery{position:relative;box-sizing:border-box;width:20px;height:10px;margin:0 6px 0 4px;vertical-align:text-bottom;padding:1px;border:1.5px solid var(--osk-m);border-radius:2px}
.osk-battery::after{content:"";position:absolute;right:-4px;top:50%;width:2px;height:4px;margin-top:-2px;border-radius:0 1px 1px 0;background:var(--osk-m)}
.osk-battery>span{display:block;width:0;height:100%;background:var(--osk-m);animation:osk-batt 1.6s steps(4) infinite}
.osk-moon{box-sizing:border-box;width:12px;height:12px;margin:0 5px;vertical-align:middle;border:1px solid var(--osk-m);border-radius:9999px;background:var(--osk-t);animation:osk-moon 1.6s ease-in-out infinite alternate}
.osk-sun::after{content:"";position:absolute;left:50%;top:50%;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:9999px;background:var(--osk-s);animation:osk-breathe 1.6s ease-in-out infinite}
.osk-heart{width:14px;height:14px;margin:0 4px;vertical-align:text-bottom;color:var(--osk-m);animation:osk-heart 1.2s ease-in-out infinite}
.osk-star{width:14px;height:14px;margin:0 4px;vertical-align:text-bottom;color:var(--osk-m);animation:osk-star 1.6s ease-in-out infinite}
.osk-heart>svg,.osk-star>svg{display:block;width:100%;height:100%}
.osk-spectrum{align-items:center;gap:2px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-spectrum>span{display:block;width:2px;height:100%;border-radius:1px;background:var(--osk-m);animation:osk-wave .9s ease-in-out infinite}
.osk-bars3{align-items:center;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-bars3>span{display:block;width:4px;height:100%;border-radius:2px;background:var(--osk-m);animation:osk-wave .8s ease-in-out infinite}
.osk-swap{position:relative;width:20px;height:7px;margin-left:4px;vertical-align:middle}
.osk-swap>span{position:absolute;top:0;width:7px;height:7px;border-radius:9999px}
.osk-swap>span:nth-child(1){left:0;background:var(--osk-m);animation:osk-sw 1s ease-in-out infinite}
.osk-swap>span:nth-child(2){left:13px;background:var(--osk-s);animation:osk-sw2 1s ease-in-out infinite}
.osk-satellite{position:relative;box-sizing:border-box;width:18px;height:18px;margin-left:4px;vertical-align:text-bottom;border:1px solid var(--osk-t);border-radius:9999px}
.osk-satellite::before{content:"";position:absolute;left:50%;top:50%;width:5px;height:5px;margin:-2.5px 0 0 -2.5px;border-radius:9999px;background:var(--osk-s)}
.osk-satellite>span{position:absolute;top:0;right:0;bottom:0;left:0;animation:osk-spin 1.4s linear infinite}
.osk-satellite>span::after{content:"";position:absolute;left:50%;top:-3px;width:4px;height:4px;margin-left:-2px;border-radius:9999px;background:var(--osk-m)}
.osk-atom{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;animation:osk-spin 2.4s linear infinite}
.osk-atom>span{position:absolute;left:0;top:50%;box-sizing:border-box;width:16px;height:6px;margin-top:-3px;border:1px solid var(--osk-m);border-radius:50%}
.osk-atom>span:nth-child(2){transform:rotate(60deg)}
.osk-atom>span:nth-child(3){transform:rotate(120deg)}
.osk-atom::after{content:"";position:absolute;left:50%;top:50%;width:3px;height:3px;margin:-1.5px 0 0 -1.5px;border-radius:9999px;background:var(--osk-s)}
.osk-binary{align-items:center;gap:1px;height:14px;margin-left:4px;vertical-align:text-bottom;font:600 10px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--osk-m)}
.osk-binary>span{display:block;animation:osk-seq 1.2s ease-in-out infinite}
.osk-binary>span::before{content:"0"}
.osk-binary>span:nth-child(1)::before,.osk-binary>span:nth-child(3)::before,.osk-binary>span:nth-child(4)::before{content:"1"}
.osk-segments{align-items:center;gap:2px;height:6px;margin-left:4px;vertical-align:middle}
.osk-segments>span{display:block;width:5px;height:4px;border-radius:1px;background:var(--osk-m);animation:osk-seq 1.2s ease-in-out infinite}
.osk-zigzag{width:24px;height:12px;margin-left:4px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-zigzag>svg{display:block;width:100%;height:100%;overflow:visible}
.osk-zigzag path{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:50;stroke-dashoffset:50;animation:osk-ecg 1.6s linear infinite}
.osk-squaretrace,.osk-hexagon{width:16px;height:16px;margin:0 3px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-squaretrace>svg,.osk-hexagon>svg{display:block;width:100%;height:100%;overflow:visible}
.osk-squaretrace path,.osk-hexagon path{fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.osk-squaretrace .t,.osk-hexagon .t{opacity:.25}
.osk-squaretrace .a,.osk-hexagon .a{stroke-dasharray:30 70;animation:osk-dash 1.4s linear infinite}
.osk-pingpong{position:relative;width:30px;height:10px;margin-left:4px;vertical-align:text-bottom}
.osk-pingpong::before,.osk-pingpong::after{content:"";position:absolute;top:0;bottom:0;width:2px;border-radius:1px;background:var(--osk-t)}
.osk-pingpong::before{left:0}
.osk-pingpong::after{right:0}
.osk-pingpong>span{position:absolute;left:4px;top:50%;width:4px;height:4px;margin-top:-2px;border-radius:9999px;background:var(--osk-s);animation:osk-pp .7s linear infinite alternate}
.osk-traffic{flex-direction:column;align-items:center;justify-content:center;gap:1px;width:6px;height:16px;margin:0 6px;vertical-align:text-bottom}
.osk-traffic>span{display:block;width:4px;height:4px;border-radius:9999px;background:var(--osk-m);animation:osk-seq 1.2s ease-in-out infinite}
.osk-search{position:relative;box-sizing:border-box;width:10px;height:10px;margin:0 7px 0 3px;vertical-align:middle;border:1.5px solid var(--osk-m);border-radius:9999px;animation:osk-wob 1.2s ease-in-out infinite alternate}
.osk-search::after{content:"";position:absolute;left:6.5px;top:6.5px;width:5px;height:1.5px;border-radius:1px;background:var(--osk-m);transform-origin:0 50%;transform:rotate(45deg)}
.osk-matrix{grid-template-columns:repeat(4,3px);gap:2px;margin-left:4px;vertical-align:text-bottom}
.osk-matrix>span{display:block;width:3px;height:3px;border-radius:1px;background:var(--osk-m);animation:osk-grid 1.2s ease-in-out infinite}
.osk-rotsq{width:9px;height:9px;margin:0 5px;vertical-align:middle;border-radius:2px;background:var(--osk-m);animation:osk-rsq 1.4s ease-in-out infinite}
.osk-quad{grid-template-columns:repeat(2,5px);gap:2px;margin:0 3px 0 4px;vertical-align:text-bottom;animation:osk-quad 1.6s ease-in-out infinite}
.osk-quad>span{display:block;width:5px;height:5px;border-radius:1px;background:var(--osk-m)}
.osk-quad>span:nth-child(2),.osk-quad>span:nth-child(3){background:var(--osk-s)}
.osk-knight{position:relative;width:35px;height:6px;margin-left:4px;vertical-align:middle;background:radial-gradient(circle,var(--osk-t) 2px,transparent 2.2px) 0 0/7px 6px repeat-x}
.osk-knight::after{content:"";position:absolute;top:0;right:0;bottom:0;left:0;background:radial-gradient(circle,var(--osk-s) 2px,transparent 2.2px) 0 0/7px 6px repeat-x;-webkit-mask:linear-gradient(90deg,transparent,#000,transparent) 0 0/16px 100% no-repeat;mask:linear-gradient(90deg,transparent,#000,transparent) 0 0/16px 100% no-repeat;animation:osk-kr 1s ease-in-out infinite alternate}
.osk-thought{align-items:flex-end;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-thought>span{display:block;border-radius:9999px;background:var(--osk-m);animation:osk-seq 1.2s ease-in-out infinite}
.osk-thought>span:nth-child(1){width:2px;height:2px}
.osk-thought>span:nth-child(2){width:3.5px;height:3.5px}
.osk-thought>span:nth-child(3){width:6px;height:6px}
.osk-diamonds{align-items:center;gap:4px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-diamonds>span{display:block;width:4px;height:4px;background:var(--osk-m);transform:rotate(45deg);animation:osk-dmd 1.2s ease-in-out infinite}
.osk-snow{align-items:flex-start;gap:4px;height:14px;margin-left:4px;overflow:hidden;vertical-align:text-bottom}
.osk-snow>span{display:block;width:3px;height:3px;border-radius:9999px;background:var(--osk-m);animation:osk-snow 1.8s linear infinite}
@keyframes osk-jump{0%,60%,100%{transform:translateY(0) rotate(0)}30%{transform:translateY(-8px) rotate(180deg)}}
@keyframes osk-rock{from{transform:rotate(-18deg)}to{transform:rotate(18deg)}}
@keyframes osk-mq{to{background-position:7px 0}}
@keyframes osk-flame{0%{transform:scale(1,.85) skewX(-4deg);opacity:.7}50%{transform:scale(.9,1.05) skewX(3deg);opacity:1}100%{transform:scale(1.05,.9) skewX(-2deg);opacity:.85}}
@keyframes osk-fall{0%{transform:translateY(0);opacity:1}55%{transform:translateY(8px);opacity:1}56%,100%{transform:translateY(8px);opacity:0}}
@keyframes osk-splash{0%,55%{transform:scale(.1);opacity:0}60%{opacity:1}100%{transform:scale(1);opacity:0}}
@keyframes osk-rain{0%{transform:translateY(-6px);opacity:0}30%{opacity:1}100%{transform:translateY(14px);opacity:0}}
@keyframes osk-fill{0%{transform:scaleY(0)}70%,100%{transform:scaleY(1)}}
@keyframes osk-batt{0%{width:0}100%{width:100%}}
@keyframes osk-moon{from{box-shadow:inset 0 0 0 0 var(--osk-m)}to{box-shadow:inset 13px 0 0 0 var(--osk-m)}}
@keyframes osk-heart{0%,60%,100%{transform:scale(1)}15%{transform:scale(1.25)}30%{transform:scale(1)}45%{transform:scale(1.18)}}
@keyframes osk-star{0%,100%{transform:rotate(0) scale(.8)}50%{transform:rotate(72deg) scale(1.1)}}
@keyframes osk-sw{0%,100%{transform:translateX(0)}50%{transform:translateX(13px) scale(.8)}}
@keyframes osk-sw2{0%,100%{transform:translateX(0)}50%{transform:translateX(-13px) scale(.8)}}
@keyframes osk-pp{from{transform:translateX(0)}to{transform:translateX(20px)}}
@keyframes osk-wob{from{transform:translate(-2px,-1px) rotate(-12deg)}to{transform:translate(2px,1px) rotate(12deg)}}
@keyframes osk-rsq{0%{transform:rotate(0) scale(1)}50%{transform:rotate(90deg) scale(.6)}100%{transform:rotate(180deg) scale(1)}}
@keyframes osk-quad{0%,15%{transform:rotate(0)}50%{transform:rotate(180deg) scale(.85)}85%,100%{transform:rotate(360deg)}}
@keyframes osk-kr{from{-webkit-mask-position:0 0;mask-position:0 0}to{-webkit-mask-position:100% 0;mask-position:100% 0}}
@keyframes osk-dmd{0%,100%{opacity:.25;transform:rotate(45deg) scale(.7)}40%{opacity:1;transform:rotate(45deg) scale(1.15)}}
@keyframes osk-snow{0%{transform:translate(0,-4px);opacity:0}20%{opacity:1}50%{transform:translate(2px,5px)}80%{opacity:1}100%{transform:translate(-1px,14px);opacity:0}}
"""

EXTRA_CSS = "\n".join(
    [
        EXTRA_CSS_STATIC.strip(),
        _radial(
            "spiral",
            8,
            f"width:2.5px;height:2.5px;margin:-1.25px 0 0 -1.25px;{_DOT};animation:osk-fade 1s linear infinite",
            lambda i: f"transform:rotate({i * 47}deg) translateY(-{1.2 + i * .85:.2f}px);animation-delay:-{i / 8:.3f}s",
        ),
        _radial(
            "ios",
            12,
            f"width:1.5px;height:4px;margin:-2px 0 0 -.75px;border-radius:1px;background:var(--osk-m);animation:osk-fade 1s linear infinite",
            lambda i: f"transform:rotate({i * 30}deg) translateY(-5px);animation-delay:-{i / 12:.3f}s",
        ),
        _radial(
            "comet",
            6,
            f"width:4px;height:4px;margin:-2px 0 0 -2px;{_DOT}",
            lambda i: f"transform:rotate(-{i * 24}deg) translateY(-6px) scale({1 - i * .13:.2f});opacity:{1 - i * .16:.2f}",
            "animation:osk-spin .9s linear infinite;",
        ),
        _radial(
            "sun",
            8,
            "width:1.5px;height:3.5px;margin:-1.75px 0 0 -.75px;border-radius:1px;background:var(--osk-m)",
            lambda i: f"transform:rotate({i * 45}deg) translateY(-7px)",
            "animation:osk-spin 6s linear infinite;",
        ),
        _radial(
            "trio",
            3,
            f"width:4px;height:4px;margin:-2px 0 0 -2px;{_DOT}",
            lambda i: f"transform:rotate({i * 120}deg) translateY(-6px);opacity:{_ARC[i]}",
            "animation:osk-spin .9s linear infinite;",
        ),
        _delays("squarejump", [0, 0.15, 0.3]),
        _delays("rain", [0, -0.3, -0.6, -0.15, -0.45]),
        _delays("spectrum", [0, -0.5, -0.2, -0.7, -0.35, -0.1, -0.6]),
        _delays("bars3", [0, -0.15, -0.3]),
        _delays("binary", [0, 0.15, 0.3, 0.45, 0.6]),
        _delays("segments", [0, 0.12, 0.24, 0.36, 0.48, 0.6]),
        _delays("traffic", [0, 0.2, 0.4]),
        _delays("matrix", [-((i * 7) % 11) * 0.1 for i in range(16)]),
        _delays("thought", [0, 0.2, 0.4]),
        _delays("diamonds", [0, 0.15, 0.3]),
        _delays("snow", [0, -0.45, -0.9, -1.35]),
    ]
)

MORE_CSS = "\n".join(
    [
        MORE_CSS_STATIC.strip(),
        _ring_css("chase", 8, 6, 3, 0.9, "osk-tail"),
        _ring_css("dotring", 12, 6.5, 2.2, 1.2, "osk-fade"),
        EXTRA_CSS,
        V2_CSS.strip(),
        V3_CSS.strip(),
    ]
)


OSK_CSS_BASE = r"""
.osk,.osk>span{display:none}
html[data-osk="bars"] #response-content-container>div:not(:first-child) .osk-host[data-osk-kind="cursor"],
html[data-osk="dot"] #response-content-container>div:not(:first-child) .osk-host[data-osk-kind="cursor"],
html[data-osk="shimmer"] #response-content-container>div:not(:first-child) .osk-host[data-osk-kind="cursor"]{display:none!important}
html[data-osk="bars"] .osk-host,
html[data-osk="block"] .osk-host,
html[data-osk="typing"] .osk-host,
html[data-osk="wave"] .osk-host,
html[data-osk="spinner"] .osk-host,
html[data-osk="shimmer"] .osk-host,
html[data-osk="dot"] .osk-host[data-osk-kind="cursor"],
html[data-osk="cursor"] .osk-host[data-osk-kind="dot"]{background:none!important;animation:none!important;opacity:1!important;margin:0!important;width:auto!important;height:auto!important;vertical-align:baseline!important}
html[data-osk="bars"] .osk-host,html[data-osk="shimmer"] .osk-host{display:block!important;width:100%!important}
html[data-osk="block"] .osk-host,html[data-osk="typing"] .osk-host,html[data-osk="wave"] .osk-host,html[data-osk="spinner"] .osk-host{display:inline-block!important}
html[data-osk="dot"] .osk-host[data-osk-kind="cursor"]{display:inline-flex!important}
html[data-osk="cursor"] .osk-host[data-osk-kind="dot"]{display:inline-block!important}
html[data-osk="bars"] .osk-host[data-osk-kind="dot"]>span:not(.osk),
html[data-osk="cursor"] .osk-host[data-osk-kind="dot"]>span:not(.osk),
html[data-osk="block"] .osk-host[data-osk-kind="dot"]>span:not(.osk),
html[data-osk="typing"] .osk-host[data-osk-kind="dot"]>span:not(.osk),
html[data-osk="wave"] .osk-host[data-osk-kind="dot"]>span:not(.osk),
html[data-osk="spinner"] .osk-host[data-osk-kind="dot"]>span:not(.osk),
html[data-osk="shimmer"] .osk-host[data-osk-kind="dot"]>span:not(.osk){display:none!important}
html[data-osk="bars"] .osk-host>.osk,html[data-osk="bars"] .osk>.osk-bars{display:block}
html[data-osk="shimmer"] .osk-host>.osk,html[data-osk="shimmer"] .osk>.osk-shimmer{display:block}
html[data-osk="block"] .osk-host>.osk,html[data-osk="block"] .osk>.osk-block{display:inline-block}
html[data-osk="spinner"] .osk-host>.osk,html[data-osk="spinner"] .osk>.osk-spinner{display:inline-block}
html[data-osk="typing"] .osk-host>.osk,html[data-osk="wave"] .osk-host>.osk{display:inline-block}
html[data-osk="typing"] .osk>.osk-typing,html[data-osk="wave"] .osk>.osk-wave{display:inline-flex}
html[data-osk="dot"] .osk-host[data-osk-kind="cursor"]>.osk,html[data-osk="dot"] .osk>.osk-dot{display:inline-flex}
html[data-osk="cursor"] .osk-host[data-osk-kind="dot"]>.osk,html[data-osk="cursor"] .osk>.osk-cursor{display:inline-block}
.osk-bars{width:100%;margin:8px 0}
.osk-bars-in{display:flex;flex-direction:column;gap:8px;animation:osk-pulse 2s cubic-bezier(.4,0,.6,1) infinite}
.osk-b{display:block;height:8px;border-radius:4px;background:var(--color-gray-200,#e5e5e5)}
html.dark .osk-b{background:var(--color-gray-600,#525252)}
.osk-r1{margin-right:3.5rem}
.osk-g3,.osk-g4{display:grid;gap:1rem}
.osk-g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.osk-g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.osk-s2{grid-column:span 2/span 2}
.osk-mr4{margin-right:1rem}
.osk-dot{position:relative;width:12px;height:12px;margin:8px 4px}
.osk-dot-ring{position:absolute;inset:0;border-radius:9999px;background:var(--color-gray-700,#404040);opacity:.75;animation:osk-pulse 2s cubic-bezier(.4,0,.6,1) infinite}
html.dark .osk-dot-ring{background:var(--color-gray-200,#e5e5e5)}
.osk-dot-core{position:relative;display:inline-flex;width:12px;height:12px;border-radius:9999px;background:#000;animation:osk-size 1.5s ease-in-out infinite}
html.dark .osk-dot-core{background:#fff}
.osk-cursor{width:2px;height:14px;margin-left:2px;vertical-align:text-bottom;background:var(--color-gray-400,#a3a3a3);animation:osk-pulse 2s cubic-bezier(.4,0,.6,1) infinite}
html.dark .osk-cursor{background:var(--color-gray-500,#737373)}
.osk-block{width:7px;height:14px;margin-left:2px;vertical-align:text-bottom;background:var(--color-gray-400,#a3a3a3);animation:osk-blink 1s steps(1,end) infinite}
html.dark .osk-block{background:var(--color-gray-500,#737373)}
.osk-typing{align-items:center;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-typing>span{display:block;width:5px;height:5px;border-radius:9999px;background:var(--color-gray-400,#a3a3a3);animation:osk-bounce 1.2s ease-in-out infinite}
html.dark .osk-typing>span{background:var(--color-gray-500,#737373)}
.osk-typing>span:nth-child(2){animation-delay:.15s}
.osk-typing>span:nth-child(3){animation-delay:.3s}
.osk-wave{align-items:center;gap:2px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-wave>span{display:block;width:2px;height:100%;border-radius:1px;background:var(--color-gray-400,#a3a3a3);animation:osk-wave 1s ease-in-out infinite}
html.dark .osk-wave>span{background:var(--color-gray-500,#737373)}
.osk-wave>span:nth-child(2){animation-delay:.15s}
.osk-wave>span:nth-child(3){animation-delay:.3s}
.osk-wave>span:nth-child(4){animation-delay:.45s}
.osk-spinner{box-sizing:border-box;width:12px;height:12px;margin-left:4px;vertical-align:text-bottom;border:2px solid var(--color-gray-200,#e5e5e5);border-top-color:var(--color-gray-500,#737373);border-radius:9999px;animation:osk-spin .8s linear infinite}
html.dark .osk-spinner{border-color:var(--color-gray-700,#404040);border-top-color:var(--color-gray-300,#d4d4d4)}
.osk-shimmer{width:100%;margin:8px 0}
.osk-shimmer-in{display:flex;flex-direction:column;gap:8px}
.osk-sh{display:block;height:8px;border-radius:4px;background:linear-gradient(90deg,var(--color-gray-200,#e5e5e5) 30%,var(--color-gray-50,#fafafa) 50%,var(--color-gray-200,#e5e5e5) 70%);background-size:200% 100%;animation:osk-shimmer 1.6s linear infinite}
html.dark .osk-sh{background-image:linear-gradient(90deg,var(--color-gray-700,#404040) 30%,var(--color-gray-500,#737373) 50%,var(--color-gray-700,#404040) 70%)}
.osk-sh:nth-child(2){width:85%}
.osk-sh:nth-child(3){width:60%}
.osk-pv{display:inline-flex;flex-shrink:0;align-items:center;width:56px;height:22px}
.osk-pv>span{display:none}
.osk-pv[data-pv="cursor"]>.osk-cursor,.osk-pv[data-pv="block"]>.osk-block,.osk-pv[data-pv="spinner"]>.osk-spinner{display:inline-block}
.osk-pv[data-pv="dot"]>.osk-dot,.osk-pv[data-pv="typing"]>.osk-typing,.osk-pv[data-pv="wave"]>.osk-wave{display:inline-flex}
.osk-pv[data-pv="bars"]>.osk-bars,.osk-pv[data-pv="shimmer"]>.osk-shimmer{display:block}
.osk-pv .osk-bars,.osk-pv .osk-shimmer{margin:0}
.osk-pv .osk-bars-in,.osk-pv .osk-shimmer-in{gap:3px}
.osk-pv .osk-b,.osk-pv .osk-sh{height:3px;border-radius:2px}
.osk-pv .osk-r1{margin-right:1rem}
.osk-pv .osk-g3,.osk-pv .osk-g4{gap:4px}
.osk-pv .osk-mr4{margin-right:4px}
.osk-pv .osk-dot{margin:0 4px}
.osk-pv .osk-cursor,.osk-pv .osk-block,.osk-pv .osk-typing,.osk-pv .osk-wave,.osk-pv .osk-spinner{margin-left:4px}
.osk-trigger{display:flex;align-items:center;gap:6px}
.osk-chev{width:12px;height:12px;flex-shrink:0}
.osk-menu{position:fixed;z-index:10000;min-width:13rem;max-height:min(24rem,calc(100dvh - 2rem));overflow-y:auto;padding:2px;border:1px solid var(--color-gray-100,#f5f5f5);border-radius:.75rem;background:#fff;color:var(--color-gray-900,#171717);box-shadow:0 10px 15px -3px rgb(0 0 0/.1),0 4px 6px -4px rgb(0 0 0/.1);outline:none}
html.dark .osk-menu{border-color:var(--color-gray-800,#262626);background:var(--color-gray-850,#1c1c1c);color:#fff}
.osk-opt{display:flex;align-items:center;gap:8px;min-height:1.875rem;padding:0 8px;border-radius:.75rem;font-size:.8125rem;cursor:pointer;outline:none}
.osk-opt:hover,.osk-opt:focus-visible{background:color-mix(in oklab,var(--color-gray-100,#f5f5f5) 70%,transparent)}
html.dark .osk-opt:hover,html.dark .osk-opt:focus-visible{background:color-mix(in oklab,var(--color-gray-800,#262626) 60%,transparent)}
.osk-opt-name{flex:1;min-width:0;white-space:nowrap}
.osk-opt-check{width:14px;height:14px;flex-shrink:0;visibility:hidden}
.osk-opt[aria-selected="true"] .osk-opt-check{visibility:visible}
@keyframes osk-pulse{50%{opacity:.5}}
@keyframes osk-size{0%,100%{transform:scale(1)}50%{transform:scale(1.25)}}
@keyframes osk-blink{50%{opacity:0}}
@keyframes osk-bounce{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-3px);opacity:1}}
@keyframes osk-wave{0%,100%{transform:scaleY(.35)}50%{transform:scaleY(1)}}
@keyframes osk-spin{to{transform:rotate(360deg)}}
@keyframes osk-shimmer{from{background-position:100% 0}to{background-position:-100% 0}}
"""

OSK_CSS_NEW = r"""
:root{--osk-c:var(--color-gray-400,#a3a3a3);--osk-m:var(--color-gray-500,#737373);--osk-t:var(--color-gray-200,#e5e5e5);--osk-s:var(--color-gray-700,#404040)}
html.dark{--osk-c:var(--color-gray-500,#737373);--osk-m:var(--color-gray-400,#a3a3a3);--osk-t:var(--color-gray-700,#404040);--osk-s:var(--color-gray-200,#e5e5e5)}
.osk-ellipsis{align-items:center;gap:3px;height:14px;margin-left:4px;vertical-align:text-bottom}
.osk-ellipsis>span{display:block;width:4px;height:4px;border-radius:9999px;background:var(--osk-m);animation:osk-seq 1.4s ease-in-out infinite}
.osk-ellipsis>span:nth-child(2){animation-delay:.2s}
.osk-ellipsis>span:nth-child(3){animation-delay:.4s}
.osk-scanner{position:relative;width:36px;height:4px;margin-left:4px;vertical-align:middle;overflow:hidden;border-radius:2px;background:var(--osk-t)}
.osk-scanner>span{position:absolute;top:0;left:0;width:40%;height:100%;border-radius:2px;background:var(--osk-m);animation:osk-scan 1.1s ease-in-out infinite alternate}
.osk-orbit{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom;animation:osk-spin 1.1s linear infinite}
.osk-orbit>span{position:absolute;left:50%;width:5px;height:5px;margin-left:-2.5px;border-radius:9999px;background:var(--osk-m)}
.osk-orbit>span:first-child{top:0}
.osk-orbit>span:last-child{bottom:0;opacity:.45}
.osk-ripple{position:relative;width:16px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-ripple>span{position:absolute;top:0;right:0;bottom:0;left:0;box-sizing:border-box;border:2px solid var(--osk-m);border-radius:9999px;opacity:0;animation:osk-ripple 1.6s ease-out infinite}
.osk-ripple>span:nth-child(2){animation-delay:.8s}
.osk-breathe{width:10px;height:10px;margin:0 5px;vertical-align:middle;border-radius:9999px;background:var(--osk-s);box-shadow:0 0 8px 2px color-mix(in oklab,var(--osk-s) 40%,transparent);animation:osk-breathe 2s ease-in-out infinite}
.osk-grid{grid-template-columns:repeat(3,3px);gap:2px;margin-left:4px;vertical-align:text-bottom}
.osk-grid>span{display:block;width:3px;height:3px;border-radius:1px;background:var(--osk-m);animation:osk-grid 1.2s ease-in-out infinite}
.osk-grid>span:nth-child(2),.osk-grid>span:nth-child(4){animation-delay:.1s}
.osk-grid>span:nth-child(3),.osk-grid>span:nth-child(5),.osk-grid>span:nth-child(7){animation-delay:.2s}
.osk-grid>span:nth-child(6),.osk-grid>span:nth-child(8){animation-delay:.3s}
.osk-grid>span:nth-child(9){animation-delay:.4s}
.osk-flip{width:10px;height:10px;margin:0 5px;vertical-align:middle;border-radius:2px;background:var(--osk-m);animation:osk-flip 1.2s ease-in-out infinite}
.osk-sparkle{width:14px;height:14px;margin:0 3px;vertical-align:text-bottom;color:var(--osk-m);animation:osk-sparkle 1.6s ease-in-out infinite}
.osk-sparkle>svg{display:block;width:100%;height:100%}
.osk-heartbeat{width:28px;height:14px;margin-left:4px;vertical-align:text-bottom;color:var(--osk-m)}
.osk-heartbeat>svg{display:block;width:100%;height:100%;overflow:visible}
.osk-heartbeat path{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:50;stroke-dashoffset:50;animation:osk-ecg 1.6s linear infinite}
.osk-ball{position:relative;width:12px;height:16px;margin-left:4px;vertical-align:text-bottom}
.osk-ball>span{position:absolute;left:2px;top:0;width:8px;height:8px;border-radius:9999px;background:var(--osk-m);animation:osk-ball .8s infinite}
@keyframes osk-seq{0%,100%{opacity:.15}40%,70%{opacity:1}}
@keyframes osk-scan{from{transform:translateX(0)}to{transform:translateX(150%)}}
@keyframes osk-ripple{0%{transform:scale(.2);opacity:.9}100%{transform:scale(1);opacity:0}}
@keyframes osk-breathe{0%,100%{transform:scale(.65);opacity:.55}50%{transform:scale(1.1);opacity:1}}
@keyframes osk-grid{0%,70%,100%{transform:scale(1);opacity:.3}35%{transform:scale(1.4);opacity:1}}
@keyframes osk-flip{0%{transform:perspective(60px) rotateX(0) rotateY(0)}50%{transform:perspective(60px) rotateX(-180.1deg) rotateY(0)}100%{transform:perspective(60px) rotateX(-180deg) rotateY(-179.9deg)}}
@keyframes osk-sparkle{0%,100%{transform:scale(.6) rotate(0);opacity:.5}50%{transform:scale(1.1) rotate(90deg);opacity:1}}
@keyframes osk-ecg{0%{stroke-dashoffset:50;opacity:1}55%{stroke-dashoffset:0;opacity:1}85%{stroke-dashoffset:0;opacity:0}100%{stroke-dashoffset:50;opacity:0}}
@keyframes osk-ball{0%{transform:translateY(0);animation-timing-function:ease-in}50%{transform:translateY(8px) scale(1.15,.85);animation-timing-function:ease-out}100%{transform:translateY(0)}}
"""


def _build_generated_css() -> str:
    """Selector lists for every style added in 1.2.0, plus the Thinking icon.

    Generated so adding a style is one entry in STYLE_NAMES, DISPLAY and
    NEW_STYLES instead of hand-editing a dozen long selector lists.
    """

    def join(template: str, keys) -> str:
        return ",".join(template.format(k=k) for k in keys)

    rules = [
        # Message hosts: strip Open WebUI's own cursor/dot look for new styles.
        join('html[data-osk="{k}"] .osk-host', NEW_STYLES)
        + "{background:none!important;animation:none!important;opacity:1!important;"
        "margin:0!important;width:auto!important;height:auto!important;"
        "vertical-align:baseline!important;display:inline-block!important}",
        join(
            'html[data-osk="{k}"] .osk-host[data-osk-kind="dot"]>span:not(.osk)',
            NEW_STYLES,
        )
        + "{display:none!important}",
    ]
    for k in NEW_STYLES:
        rules.append(f'html[data-osk="{k}"] .osk-host>.osk{{display:inline-block}}')
        rules.append(f'html[data-osk="{k}"] .osk>.osk-{k}{{display:{DISPLAY[k]}}}')
        rules.append(f'.osk-pv[data-pv="{k}"]>.osk-{k}{{display:{DISPLAY[k]}}}')

    # Thinking icon: our element sits next to Open WebUI's spinner svg and
    # takes over when a non-default style is chosen.
    rules += [
        ".osk-th{display:none}",
        ".osk-th>span{display:none;margin:0}",
        "html[data-osk-think] .osk-th{display:inline-flex;align-items:center;"
        "justify-content:center;flex-shrink:0;min-width:16px;height:16px}",
        'html[data-osk-think="none"] .osk-th{display:none}',
        "html[data-osk-think] svg[data-osk-n]{display:none!important}",
        # Thinking Indicator Size slider: scales our icon and the original spinner.
        ".osk-th,svg[data-osk-n]{zoom:var(--osk-think-size,1)}",
        # Message Indicator Size slider: scales the whole host (ours and the original).
        # Full-width skeleton styles are left alone (zoom would overflow their 100% width).
        '.osk-host{zoom:var(--osk-msg-size,1)}',
        'html[data-osk="bars"] .osk-host,html[data-osk="shimmer"] .osk-host{zoom:1}',
    ]
    for k, display in DISPLAY.items():
        rules.append(
            f'html[data-osk-think="{k}"] .osk-th>.osk-{k}{{display:{display}}}'
        )
    return "\n".join(rules)


# ---------------------------------------------------------------------------
# 2.0.0: Thinking Words. Replaces the "Thinking..." label with rotating words.
# 2.6.0: i18n refactor -> single compact pipe-delimited source (TW_PACKS_RAW).
# 2.7.0: nl completed + it/pt added -> order is en|fr|es|de|nl|it|pt.
# ---------------------------------------------------------------------------
LANG_ORDER = ["en", "fr", "es", "de", "nl", "it", "pt"]  # 1st segment = English (fallback)
TW_SEG_SEP = "|"

# Compact i18n source. Each pack phrase is ONE pipe-delimited line:
#   "english|french|spanish|german|dutch|italian|portuguese"
# Each label is {english_key: "french|...|portuguese"} (English is the key).
# To add a language: append its segment to every line and extend LANG_ORDER.
# An empty segment means "no translation for that language".

def _expand_pack(packs_raw, lang_order):
    """Return (en_dict, i18n_dict) from compact pipe-delimited pack lines.

    en_dict:   {pack: [english words]}
    i18n_dict: {lang: {pack: [words]}} for non-English langs.
    A language's list is index-aligned with the English list. Every language now
    ships the full set of phrases, so all seven decks share the same length and
    the rotation cycle is identical regardless of the active language (cycle
    parity). The empty-segment filter below is kept only as a defensive guard;
    it must no longer trigger for any language, including Dutch.
    """
    en_dict = {}
    i18n_dict = {}
    for pack, rows in packs_raw.items():
        en_dict[pack] = [r.split(TW_SEG_SEP)[0] for r in rows]
        for li, lang in enumerate(lang_order):
            if li == 0:
                continue  # English handled above
            words = []
            for r in rows:
                segs = r.split(TW_SEG_SEP)
                seg = segs[li] if li < len(segs) else ""
                if seg:
                    words.append(seg)
            if words:
                i18n_dict.setdefault(lang, {})[pack] = words
    return en_dict, i18n_dict


def _expand_labels(labels_raw, lang_order):
    """Return {lang: {english_key: translated_value}} from compact labels.

    labels_raw: {english_key: "fr|es|de|nl|it|pt"} (English is the key, not a segment).
    A language appears only if it has at least one non-empty segment. Within a
    present language, an empty segment falls back to the English key.
    """
    out = {}
    langs = lang_order[1:]  # skip English
    for li, lang in enumerate(langs):
        present = any(
            (v.split(TW_SEG_SEP)[li] if li < len(v.split(TW_SEG_SEP)) else "")
            for v in labels_raw.values()
        )
        if not present:
            continue
        d = {}
        for key, val in labels_raw.items():
            segs = val.split(TW_SEG_SEP)
            seg = segs[li] if li < len(segs) else ""
            d[key] = seg or key
        out[lang] = d
    return out


# Every phrase: "en|fr|es|de|nl|it|pt". Empty segment = no translation.
TW_PACKS_RAW = {
    'claude': [
        "Thinking this through|En train d'y réfléchir|Pensando en esto|Denke darüber nach|Aan het denken|Ci sto riflettendo|A pensar nisto",
        'Going over the details|Passage en revue des détails|Revisando los detalles|Gehe die Details durch|Bezig met nadenken|Rivedendo i dettagli|A rever os detalhes',
        'Pondering|Réflexion en cours|Meditando|Grüble|Bezig met reflecteren|Sto ponderando|A ponderar',
        'Trying harder|Effort de concentration|Esfuerzo mental|Mühevolle Anstrengung|Informatie verzamelen|Mi sto impegnando di più|A esforçar-me mais',
        'Mulling it over|Méditation sur le sujet|Dándole vueltas|Sinne darüber nach|Opties afwegen|La sto rimuginando|A ruminar a ideia',
        'Connecting the dots|Connexion des idées|Conectando ideas|Verbinde die Punkte|Verbanden leggen|Sto collegando i puntini|A ligar os pontos',
        'Chewing on that|Rumination de la question|Masticando la pregunta|Käue das durch|Overwegen|La sto masticando|A mastigar a ideia',
        'Weighing options|Pondération des options|Sopesando opciones|Wäge Optionen ab|Analyseren|Sto valutando le opzioni|A pesar opções',
        'Digging deeper|Approfondissement|Profundizando|Grabe tiefer|Dieper graven|Sto scavando più a fondo|A aprofundar',
        'Untangling this|Démêlage de ce problème|Desenredando esto|Entwirre das|Dit ontwarren|Sto districando la matassa|A desembrulhar isto',
        "Cooking up an answer|Préparation d'une réponse|Preparando una respuesta|Bringe eine Antwort zustande|Een antwoord bedenken|Sto preparando una risposta|A preparar uma resposta",
        'Working it out|Résolution en cours|Trabajando en ello|Arbeite es aus|Het uitwerken|Sto risolvendo|A resolvê-lo',
        'Reading between the lines|Lecture entre les lignes|Leyendo entre líneas|Zwischen den Zeilen lesen|Tussen de regels lezen|Leggo tra le righe|A ler entre linhas',
        'Considering angles|Étude des angles|Considerando ángulos|Betrachte Blickwinkel|Hoeken bekijken|Sto valutando gli aspetti|A considerar ângulos',
        'Double-checking|Vérification|Doble verificación|Doppelprüfung|Dubbel controleren|Sto ricontrollando|A verificar novamente',
        'Sharpening the answer|Peaufinage de la réponse|Puliendo la respuesta|Verfeinere die Antwort|Het antwoord slijpen|Sto affilando la risposta|A afiar a resposta',
        'Almost there|Presque prêt|Ya casi|Fast geschafft|Bijna klaar|Quasi fatto|Quase lá',
        'Gathering my thoughts|Rassemblement des pensées|Recogiendo pensamientos|Sammle meine Gedanken|Mijn gedachten verzamelen|Sto raccogliendo i pensieri|A reunir os pensamentos',
        'Turning it over|Examen sous toutes les coutures|Dándole la vuelta|Wälze das um|Het wentelen|La sto rigirando|A virar e revirar',
        'Following the thread|Suivi du fil conducteur|Siguiendo el hilo|Folge dem Faden|Het draadje volgen|Sto seguendo il filo|A seguir o fio',
        'Getting to the bottom of it|Recherche de la solution|Llegando al fondo|Gehe der Sache auf den Grund|De oorzaak achterhalen|Vado a fondo|A ir ao fundo',
        "Looking at the big picture|Vue d'ensemble|Viendo el panorama|Betrachte das Gesamtbild|Het grote geheel bekijken|Guardo il quadro generale|A ver a panorâmica",
        'Breaking it down|Décomposition du problème|Desglosando|Breche es herunter|Het opsplitsen|Lo sto scomponendo|A decompor',
        'Piecing it together|Assemblage des pièces|Ensamblando piezas|Setze die Teile zusammen|De stukken samenbrengen|Sto unendo i pezzi|A juntar as peças',
        'Taking a closer look|Examen attentif|Mirando más de cerca|Siehe genauer hin|Dichterbij kijken|Guardo più da vicino|A ver mais de perto',
        'Exploring possibilities|Exploration des possibilités|Explorando posibilidades|Erkunde Möglichkeiten|Mogelijkheden verkennen|Esploro le possibilità|A explorar possibilidades',
        'Checking my reasoning|Vérification du raisonnement|Revisando el razonamiento|Prüfe meine Logik|Mijn redenering controleren|Verifico il mio ragionamento|A verificar o meu raciocínio',
        'Putting it all together|Mise en commun|Uniéndolo todo|Füge alles zusammen|Alles samenbrengen|Sto unendo tutto|A juntar tudo',
        'Examining the evidence|Examen des indices|Examinando la evidencia|Untersuche die Hinweise|Het bewijs onderzoeken|Esamino gli indizi|A examinar as provas',
        'Sorting through ideas|Tri des idées|Ordenando ideas|Sortiere Ideen|Ideën sorteren|Sto setacciando le idee|A separar ideias',
        'Connecting the pieces|Reliure des éléments|Conectando piezas|Verbinde die Stücke|De stukken verbinden|Sto collegando i pezzi|A ligar as peças',
        'Thinking it over|Réflexion approfondie|Pensándolo bien|Denke es durch|Erover nadenken|Ci sto pensando|A pensar bem',
        'Giving this some thought|Attention portée au sujet|Poniéndole atención|Schenke dem Beachtung|Hierover nadenken|Ci sto dedicando attenzione|A dedicar atenção a isto',
        'Reflecting on this|Méditation sur ce point|Reflexionando sobre esto|Sinniere darüber|Hierover reflecteren|Rifletto su questo|A refletir sobre isto',
        'Analyzing the question|Analyse de la question|Analizando la pregunta|Analysiere die Frage|De vraag analyseren|Analizzo la domanda|A analisar a pergunta',
        'Looking at it from every side|Étude sous chaque angle|Mirándolo desde todos los lados|Betrachte von jeder Seite|Van alle kanten bekijken|La guardo da ogni angolo|A ver de todos os lados',
        "Trying another angle|Essai d'une autre approche|Probando otro ángulo|Versuche einen anderen Winkel|Een andere hoek proberen|Provo un'altra angolazione|A tentar outro ângulo",
        'Working through the logic|Travail logique|Trabajando la lógica|Arbeite die Logik durch|De logica doorlopen|Sto percorrendo la logica|A percorrer a lógica',
        'Making sense of it|Donner du sens|Dándole sentido|Bringe Sinn hinein|Er betekenis aan geven|Cerco di darci un senso|A dar-lhe sentido',
        'Searching my memory|Recherche en mémoire|Buscando en mi memoria|Suche in meiner Erinnerung|In mijn geheugen zoeken|Cerco nella memoria|A procurar na memória',
        'Narrowing it down|Affinage|Acotando|Grenze ein|Het verfijnen|Sto restringendo|A afunilar',
        'Drawing conclusions|Tirage de conclusions|Sacando conclusiones|Ziehe Schlüsse|Conclusies trekken|Traggo le conclusioni|A tirar conclusões',
        'Crafting a response|Rédaction de la réponse|Redactando la respuesta|Formuliere eine Antwort|Een antwoord formuleren|Sto scrivendo una risposta|A redigir uma resposta',
        'Organizing my thoughts|Organisation des pensées|Organizando mis pensamientos|Organisiere meine Gedanken|Mijn gedachten ordenen|Organizzo i pensieri|A organizar os pensamentos',
        'Finding the right words|Trouver les bons mots|Buscando las palabras correctas|Finde die richtigen Worte|De juiste woorden vinden|Cerco le parole giuste|A procurar as palavras certas',
        'Refining the answer|Raffinement de la réponse|Refinando la respuesta|Verfeinere die Antwort|Het antwoord verfijnen|Sto rifinendo la risposta|A refinar a resposta',
        'Polishing things up|Polissage|Puliendo detalles|Poliere auf|De details oppoetsen|Sto lucidando i dettagli|A polir os detalhes',
        'Checking the facts|Vérification des faits|Verificando hechos|Prüfe die Fakten|De feiten controleren|Verifico i fatti|A verificar os factos',
        'Considering the options|Étude des options|Considerando opciones|Berücksichtige Optionen|De opties afwegen|Considero le opzioni|A considerar as opções',
        'Balancing the details|Équilibrage des détails|Equilibrando detalles|Balanciere die Details|De details balanceren|Bilancio i dettagli|A equilibrar os detalhes',
        'Looking deeper|Approfondissement|Mirando más profundo|Blicke tiefer|Dieper kijken|Guardo più a fondo|A olhar mais fundo',
        'Thinking carefully|Réflexion soignée|Pensando con cuidado|Denke sorgfältig|Zorgvuldig nadenken|Penso con attenzione|A pensar com cuidado',
        "Giving it my full attention|Attention totale|Poniendo toda la atención|Volle Aufmerksamkeit|Alle aandacht eraan geven|Ci dedico tutta l'attenzione|Dou-lhe toda a atenção",
        'Doing the heavy lifting|Travail de fond|Haciendo el trabajo duro|Harte Arbeit|Het zware werk doen|Faccio il lavoro pesante|A fazer o trabalho pesado',
        "Running through scenarios|Simulation de scénarios|Recorriendo escenarios|Spiele Szenarien durch|Scenario's doorlopen|Simulo gli scenari|A percorrer cenários",
        "Testing a few ideas|Test d'idées|Probando ideas|Teste Ideen|Enkele ideeën testen|Provo qualche idea|A testar algumas ideias",
        'Zooming in|Zoom avant|Acercando|Hereinzoomen|Inzoomen|Sto ingrandendo|A aproximar',
        'Zooming out|Zoom arrière|Alejando|Herauszoomen|Uitzoomen|Sto allontanando|A afastar',
        'Rethinking this|Remise en question|Repensando esto|Überdenke das|Hierover opnieuw nadenken|Ci ripenso|A repensar',
        'Second-guessing myself|Auto-doute|Dudando de mí mismo|Selbstzweifel|Aan mezelf twijfelen|Mi metto in discussione|Duvido de mim mesmo',
        "Making a plan|Élaboration d'un plan|Haciendo un plan|Erstelle einen Plan|Een plan maken|Sto facendo un piano|A fazer um plano",
        'Mapping it out|Cartographie|Mapeando|Karte es auf|Het in kaart brengen|Lo sto mappando|A mapear',
        'Laying it all out|Exposition complète|Exponiendo todo|Lege alles dar|Alles op een rij zetten|Sto esponendo tutto|A expor tudo',
        "Digesting this|Digestion de l'info|Digiriendo esto|Verdaue das|Dit verteren|Sto digerendo|A digerir",
        'Absorbing the details|Absorption des détails|Absorbiendo detalles|Nehme Details auf|De details opnemen|Assorbo i dettagli|A absorver os detalhes',
        'Reading it again|Relecture|Releyendo|Lese erneut|Het opnieuw lezen|Lo rileggo|A reler',
        'Taking it step by step|Étape par étape|Paso a paso|Schritt für Schritt|Stap voor stap|Procedo per gradi|Passo a passo',
        'Thinking out loud|Pensée à voix haute|Pensando en voz alta|Denke laut|Hardop denken|Penso ad alta voce|A pensar em voz alta',
        'Thinking really hard|Effort intellectuel|Pensando muy fuerte|Denke sehr hart|Heel hard nadenken|Penso con tutte le forze|A pensar muito',
        'Brainstorming|Brainstorming|Lluvia de ideas|Brainstorming|Brainstormen|Brainstorming|Chuva de ideias',
        'Deliberating|Délibération|Deliberando|Berate|Overleggen|Sto deliberando|A deliberar',
        'Contemplating|Contemplation|Contemplando|Sinniere|Contempleren|Contemplo|A contemplar',
        'Ruminating|Rumination|Rumiando|Grüble nach|Herkawen|Rumino|A ruminar',
        'Cogitating|Cogitation|Cogitando|Kopfrechnen|Cogiteren|Cogito|A cogitar',
        'Noodling on it|Élaboration tranquille|Dándole al coco|Sinne ruhig darüber nach|Rustig eraan prutsen|Ci armeggio sopra|A ralar com isto',
        'Wrestling with this|Lutte avec le problème|Luchando con esto|Ringe mit dem Problem|Met dit worstelen|Lotto con questo|A debater-me com isto',
        "Doing some mental math|Calcul mental|Haciendo cuentas|Kopfrechnen|Een beetje hoofdrekenen|Faccio un po' di conti a mente|A fazer contas de cabeça",
        'Building the answer|Construction de la réponse|Construyendo la respuesta|Baue die Antwort|Het antwoord opbouwen|Costruisco la risposta|A construir a resposta',
        'Assembling my thoughts|Assemblage des pensées|Ensamblando pensamientos|Setze Gedanken zusammen|Mijn gedachten bundelen|Assemblo i pensieri|A juntar os pensamentos',
        "Looking for the best approach|Recherche de la meilleure approche|Buscando el mejor enfoque|Suche den besten Ansatz|De beste aanpak zoeken|Cerco l'approccio migliore|A procurar a melhor abordagem",
        'Choosing my words|Choix des mots|Eligiendo palabras|Wähle meine Worte|Mijn woorden kiezen|Scelgo le parole|A escolher as palavras',
        'Picking the best answer|Sélection de la meilleure réponse|Escogiendo la mejor respuesta|Wähle die beste Antwort|Het beste antwoord kiezen|Scegli la risposta migliore|A escolher a melhor resposta',
        'Putting in the effort|Effort soutenu|Poniendo esfuerzo|Gib Mühe|Mijn best doen|Ci metto impegno|A dedicar esforço',
        'Thinking deeply|Pensée profonde|Pensando a fondo|Denke tiefgründig|Diep nadenken|Penso a fondo|A pensar a fundo',
        'Staying with it|Persévérance|Siguiendo con ello|Bleibe dran|Dran blijven|Insisto|A insistir',
        'Going the extra mile|Excellence|Dando un paso más|Gehe die Extrameile|De extra mijl gaan|Faccio uno sforzo in più|A fazer um esforço extra',
        'Making sure it is right|Vérification de justesse|Asegurando que esté bien|Stelle sicher, dass es stimmt|Controleren of het klopt|Verifico che sia corretto|Garanto que está correto',
        'Cross-checking|Double vérification|Contraverificación|Kreuzprüfung|Kruislings controleren|Faccio una doppia verifica|Verificação cruzada',
        'Reviewing my notes|Revue des notes|Revisando mis notas|Überprüfe meine Notizen|Mijn notities doornemen|Ripasso i miei appunti|A rever as minhas notas',
        'Sketching it out|Esquisse|Bocetando|Skizziere es|Het schetsen|Lo schizzo|A esboçar',
        'Finding the pattern|Détection du motif|Encontrando el patrón|Finde das Muster|Het patroon vinden|Trovo il modello|A encontrar o padrão',
        "Spotting the catch|Repérage du piège|Detectando la trampa|Erkenne den Haken|Het addertje opsporen|Individuo l'inghippo|A detetar a armadilha",
        'Tracing the logic|Suivi de la logique|Siguiendo la lógica|Verfolge die Logik|De logica volgen|Ripercorro la logica|A seguir a lógica',
        "Chasing an idea|Poursuite d'une idée|Persiguiendo una idea|Jage einer Idee nach|Een idee najagen|Inseguo un'idea|A perseguir uma ideia",
        "Catching a thought|Saisie d'une pensée|Captando un pensamiento|Fange einen Gedanken|Een gedachte vangen|Catturo un pensiero|A captar um pensamento",
        'Letting ideas simmer|Laisser mijoter|Dejando reposar|Lass Ideen ziehen|Ideeën laten sudderen|Lascio sobbollire le idee|A deixar as ideias repousar',
        'Warming up|Échauffement|Entrando en calor|Aufwärmen|Opwarmen|Mi sto scaldando|A aquecer',
        'Getting my bearings|Prise de repères|Orientándome|Orientiere mich|Mijn weg vinden|Mi oriento|A orientar-me',
        'Gaining clarity|Gain de clarté|Ganando claridad|Gewinne Klarheid|Helderheid krijgen|Acquisto chiarezza|A ganhar clareza',
        'Seeing the whole picture|Vision globale|Viendo el cuadro completo|Sehe das ganze Bild|Het geheel zien|Vedo il quadro completo|A ver o quadro completo',
        'Getting the details right|Précision des détails|Cuidando los detalles|Bringe Details richtig|De details goed krijgen|Curo i dettagli|A cuidar dos detalhes',
        'Tying up loose ends|Finitions|Atando cabos|Verknüpfe lose Enden|Losse eindjes aan elkaar knopen|Sto annodando le parti in sospeso|A atar pontas soltas',
        'Weaving it together|Tissage|Tejiendo|Verwebe es|Het verweven|Intreccio il tutto|A tecer tudo',
        'Pulling it together|Rassemblement|Uniéndolo|Füge es zusammen|Het samenbrengen|Raccolgo il tutto|A reunir tudo',
        'Fine-tuning|Ajustement fin|Ajustando|Feinabstimmung|Fijnafstemmen|Perfeziono|A afinar',
        'One moment|Un instant|Un momento|Einen Moment|Een moment|Un momento|Um momento',
        'Hang tight|Patience|Espera|Geduld|Wacht even|Un attimo|Um instante',
        'Bear with me|Encore un peu|Ten paciencia|Hab Geduld|Nog even volhouden|Abbi pazienza|Tenha paciência',
        'Just a sec|Juste une seconde|Un segundito|Nur eine Sekunde|Slechts een seconde|Solo un secondo|Só um segundo',
        'Working on it|Travail en cours|Trabajando en ello|Arbeite daran|Eraan werken|Ci sto lavorando|A trabalhar nisso',
        'Give me a moment|Un moment svp|Dame un momento|Gib mir einen Moment|Geef me een moment|Datemi un momento|Dêem-me um momento',
        'Deep in thought|Absorbé par la réflexion|En profundas reflexiones|Vertieft in Gedanken|Verdiept in gedachten|Assorto nei pensieri|Absorto em pensamentos',
        'Lost in thought|Perdu dans mes pensées|Perdido en mis pensamientos|Versunken in Gedanken|Verloren in gedachten|Perso nei pensieri|Perdido em pensamentos',
        'Wheels turning|Rouages en marche|Engranajes girando|Räder drehen sich|De wielen draaien|Le ruote girano|As rodas a girar',
        'Gears turning|Engrenages actifs|Ruedas en movimiento|Zahnräder laufen|De tandwielen draaien|Gli ingranaggi girano|As engrenagens a girar',
        'Brain whirring|Cerveau en ébullition|Cerebro zumbando|Gehirn surrt|De hersenen zoemen|Il cervello ronza|O cérebro a zumbir',
        'Neurons firing|Neurones en action|Neuronas disparando|Neuronen feuern|Neuronen vuren|Neuroni in azione|Neurónios a disparar',
        'Lightbulb loading|Ampoule en chargement|Bombilla cargando|Glühbirne lädt|De gloeilamp laadt|Lampadina in caricamento|Lâmpada a carregar',
        'Coming up with something good|Préparation de quelque chose de bien|Algo bueno se acerca|Etwas Gutes entsteht|Iets goeds bedenken|Preparo qualcosa di buono|A preparar algo bom',
    ],
    'dev': [
        'Fixing bugs|Correction de bugs|Arreglando bugs|Behebe Bugs|Berekenen|Correggo bug|A corrigir bugs',
        'Compiling thoughts|Compilation des pensées|Compilando pensamientos|Kompiliere Gedanken|Logica controleren|Compilo pensieri|A compilar pensamentos',
        "Refactoring ideas|Refactoring d'idées|Refactorizando ideas|Refactoring von Ideen|Variabelen invullen|Rifattorizzo idee|A refatorar ideias",
        'Reading the docs|Lecture de la doc|Leyendo los docs|Lese die Doku|Cache lezen|Leggo la documentazione|A ler a documentação',
        'Rubber-ducking|Canard en plastique|Pato de goma|Gummientente|Data verwerken|Anatroccolo di gomma|Pato de borracha',
        'Running tests|Lancement des tests|Ejecutando tests|Führe Tests aus|Indexeren|Eseguo i test|A correr testes',
        'Resolving merge conflicts|Résolution de conflits git|Resolviendo conflictos git|Löse Merge-Konflikte|Merge-conflicten oplossen|Risolvo conflitti di merge|A resolver conflitos de merge',
        'Grepping my memory|grep de ma mémoire|grep de mi memoria|grep mein Gedächtnis|Geheugen doorzoeken|grep nella memoria|grep na memória',
        'Optimizing|Optimisation|Optimizando|Optimiere|Optimaliseren|Ottimizzo|A otimizar',
        'Checking edge cases|Vérification des cas limites|Revisando casos límite|Prüfe Randfälle|Randgevallen testen|Controllo i casi limite|A verificar casos-limite',
        'Linting my thoughts|Lint de mes pensées|Lint de mis pensamientos|Lint meine Gedanken|Gedachten linten|Lint dei miei pensieri|Lint dos meus pensamentos',
        'Clearing the cache|Vidage du cache|Limpiando la caché|Leere den Cache|Cache wissen|Svuoto la cache|A limpar a cache',
        'Reviewing the diff|Revue du diff|Revisando el diff|Reviewe den Diff|Diff bekijken|Rivedo il diff|A rever o diff',
        "Writing a unit test|Écriture d'un test unitaire|Escribiendo un test unitario|Schreibe einen Unit-Test|Unit-test schrijven|Scrivo un test unitario|A escrever um teste unitário",
        'Stack Overflow-ing|Stack Overflow|Stack Overflow|Stack Overflow|Stack Overflow|Stack Overflow|Stack Overflow',
        'Deploying an answer|Déploiement de la réponse|Desplegando una respuesta|Deploye eine Antwort|Antwoord uitrollen|Deploy della risposta|A publicar uma resposta',
        'Squashing commits|Squash de commits|Squashing commits|Squashe Commits|Commits samenvoegen|Squash dei commit|Squash de commits',
        'Profiling the problem|Profilage du problème|Profileando el problema|Profile das Problem|Probleem analyseren|Profilo il problema|A perfilar o problema',
        "Blaming the cache|C'est la faute du cache|Culpa de la caché|Schuld ist der Cache|Cache de schuld geven|La colpa è della cache|A culpa é da cache",
        'Shipping it|En production|A producción|Ab damit|Uitrollen|In produzione|Para produção',
    ],
    'playful': [
        "Consulting the oracle|Consultation de l'oracle|Consultando al oráculo|Befrage das Orakel|Hersenen opwarmen|Consulto l'oracolo|A consultar o oráculo",
        'Asking the hamsters|Demande aux hamsters|Preguntando a los hámsteres|Frage die Hamster|Tandwielen draaien|Chiedo ai criceti|A perguntar aos hamsteres',
        'Herding thoughts|Rassemblement des pensées|Pastoreando pensamientos|Hüte meine Gedanken|Even denken…|Raduno i pensieri|A pastorear pensamentos',
        'Warming up brain cells|Réchauffement des neurones|Calentando neuronas|Wärme Gehirnzellen auf|Brein aan het werk|Scaldo le cellule cerebrali|A aquecer células cerebrais',
        'Summoning wisdom|Invocation de sagesse|Invocando sabiduría|Beschwöre Weisheit|Synapsen knetteren|Evoco saggezza|A invocar sabedoria',
        'Shuffling neurons|Mélange des neurones|Barajando neuronas|Mische Neuronen|Neuronen door elkaar schudden|Mescolo i neuroni|A embaralhar neurónios',
        'Polishing the crystal ball|Polissage de la boule de cristal|Puliendo la bola de cristal|Poliere die Kristallkugel|Kristallen bol poetsen|Lustro la sfera di cristallo|A polir a bola de cristal',
        'Feeding the gremlins|Nourrissage des gremlins|Alimentando gremlins|Füttere die Gremlins|Gremlins voederen|Nutro i gremlin|A alimentar gremlins',
        'Stretching synapses|Étirement des synapses|Estirando sinapsis|Dehne Synapsen|Synapsen rekken|Stiro le sinapsi|A esticar sinapses',
        'Brewing coffee for neurons|Café pour neurones|Café para neuronas|Kaffee für Neuronen|Koffie zetten voor neuronen|Preparo caffè per i neuroni|A fazer café para neurónios',
        'Doing mental gymnastics|Gymnastique mentale|Gimnasia mental|Mentale Gymnastik|Mentale gymnastiek|Faccio ginnastica mentale|A fazer ginástica mental',
        'Waking the wizards|Réveil des sorciers|Despertando a los magos|Wecke die Zauberer|Tovenaars wakker maken|Sveglio i maghi|A acordar os magos',
        'Spinning the wheel|Rotation de la roue|Girando la ruleta|Drehe das Rad|Rad draaien|Faccio girare la ruota|A girar a roda',
        'Poking the idea box|Chatouillage de la boîte à idées|Haciendo cosquillas a la caja de ideas|Kitzle die Ideenbox|Ideeënbox porren|Solletico il barattolo delle idee|A fazer cócegas na caixa de ideias',
        'Tickling the hamster wheel|Faire craquer les jointures|Crujiendo nudillos|Knacke mit den Fingern|Hamsterrad kietelen|Solletico la ruota dei criceti|A fazer cócegas à roda dos hamsteres',
        'Cracking knuckles|Crac des doigts|Crujiendo los nudillos|Knacke die Fingerknöchel|Vingers kraken|Scrocchio le dita|A estalar os dedos',
    ],
    'science': [
        'Running the numbers|Calcul des chiffres|Calculando números|Berechne Zahlen|Hypothesen toetsen|Calcolo i numeri|A calcular os números',
        "Formulating hypotheses|Formulation d'hypothèses|Formulando hipótesis|Formuliere Hypothesen|Data analyseren|Formulo ipotesi|A formular hipóteses",
        'Calibrating|Calibrage|Calibrando|Kalibriere|Variabelen wegen|Calibro|A calibrar',
        'Simulating outcomes|Simulation de résultats|Simulando resultados|Simuliere Ergebnisse|Patronen herkennen|Simulo i risultati|A simular resultados',
        'Cross-referencing|Recoupement|Contrastando|Kreuzreferenziere|Experiment uitvoeren|Faccio incroci|A cruzar referências',
        'Testing theories|Test de théories|Probando teorías|Teste Theorien|Theorieën testen|Testo le teorie|A testar teorias',
        'Measuring twice|Double mesure|Midiendo dos veces|Zweimal messen|Twee keer meten|Misuro due volte|A medir duas vezes',
        'Crunching data|Traitement de données|Procesando datos|Verarbeite Daten|Data verwerken|Elaboro i dati|A processar dados',
        'Peer reviewing myself|Revue par les pairs interne|Revisión de pares interna|Peer-Review im Kopf|Peer review van mezelf|Peer review di me stesso|Revisão por pares interna',
        'Isolating variables|Isolation des variables|Aislando variables|Isoliere Variablen|Variabelen isoleren|Isolo le variabili|A isolar variáveis',
        "Balancing the equation|Équilibrage de l'équation|Equilibrando la ecuación|Balanciere die Gleichung|Vergelijking in balans brengen|Bilancio l'equazione|A equilibrar a equação",
        'Observing patterns|Observation de motifs|Observando patrones|Beobachte Muster|Patronen observeren|Osservo i modelli|A observar padrões',
    ],
    'hacker': [
        'Initializing neural net|Initialisation du réseau neuronal|Inicializando red neuronal|Initialisiere neuronales Netz|Denkproces initialiseren|Inizializzo la rete neurale|A inicializar a rede neural',
        'Decrypting the question|Déchiffrement de la question|Descifrando la pregunta|Entschlüssele die Frage|Inference starten|Decifro la domanda|A decifrar a pergunta',
        "Parsing intent|Analyse de l'intention|Parseando intención|Parse Intent|Neurale lagen activeren|Analizzo l'intento|A analisar a intenção",
        'Allocating brain|Allocation de cerveau|Asignando cerebro|Allokiere Gehirn|Tokens verwerken|Assegno cervello|A alocar cérebro',
        'Handshaking with logic|Poignée de main logique|Handshake con la lógica|Handshake mit Logik|Context laden|Handshake con la logica|Aperto de mão com a lógica',
        'Booting reasoning core|Démarrage du noyau de raisonnement|Arrancando núcleo de razonamiento|Starte Reasoning-Kern|Redeneerkern opstarten|Avvio il nucleo di ragionamento|A arrancar o núcleo de raciocínio',
        'Tracing the stack|Trace de la stack|Trazeando la stack|Trace den Stack|Stack volgen|Traccio lo stack|A rastrear a stack',
        "Injecting insight|Injection d'insight|Inyectando insight|Injiziere Insight|Inzicht injecteren|Inietto intuizione|A injetar perspicácia",
        'Compiling answer|Compilation de la réponse|Compilando respuesta|Kompiliere Antwort|Antwoord compileren|Compilo la risposta|A compilar a resposta',
        "Bypassing the obvious|Contournement de l'évident|Evitando lo obvio|Umgehe das Offensichtliche|Voor de hand liggende omzeilen|Evito l'ovvio|A contornar o óbvio",
        'Sudo thinking|sudo réfléchir|sudo pensar|sudo denken|sudo nadenken|sudo pensare|sudo pensar',
        "Opening a root shell|Ouverture d'un shell root|Abriendo shell root|Öffne Root-Shell|Root-shell openen|Apro una shell root|A abrir uma shell root",
    ],
    'zen': [
        'Breathing|Respiration|Respirando|Atme|Ademhalen|Respiro|A respirar',
        'Finding clarity|Recherche de clarté|Encontrando claridad|Finde Klarheit|Laat het zakken|Trovo chiarezza|A encontrar clareza',
        'Letting it settle|Laisser décanter|Dejando asentar|Lass es sich setzen|Stilte…|Lascio decantare|A deixar assentar',
        'Taking a moment|Prendre un moment|Tomándome un momento|Nimm dir einen Moment|In de flow|Prendo un momento|Tomo um momento',
        'Focusing|Concentration|Enfocándome|Fokussiere|Laten stromen|Mi concentro|A focar',
        "Seeking balance|Recherche d'équilibre|Buscando equilibrio|Suche Balance|In balans komen|Cerco l'equilibrio|A procurar equilíbrio",
        'Quieting the noise|Apaisement du bruit|Silenciando el ruido|Stille das Rauschen|Ruis dempen|Placo il rumore|A acalmar o ruído',
        'Listening closely|Écoute attentive|Escuchando atentamente|Höre aufmerksam zu|Aandachtig luisteren|Ascolto con attenzione|A ouvir com atenção',
    ],
    'minimal': [
        'Thinking|Réflexion|Pensando|Denke|Denken…|Pensiero|A pensar',
        'Reasoning|Raisonnement|Razonando|Logik|Nadenken…|Ragionamento|Raciocínio',
        'Working|Traitement|Trabajando|Arbeite|Wachten…|Lavoro|A trabalhar',
        'Processing|Analyse|Procesando|Verarbeite|Bezig…|Elaborazione|Processamento',
        'Considering|Étude|Considerando|Prüfe|Denkt…|Valutazione|A considerar',
    ],
}

TW_PACK_NAMES = {
    "default": "Default",
    "off": "Original \u201cThinking\u2026\u201d",
    "claude": "Claude-style",
    "dev": "Dev & Debug",
    "playful": "Playful",
    "science": "Science Lab",
    "hacker": "Hacker Terminal",
    "zen": "Zen",
    "minimal": "Minimal",
    "mix": "Random Mix (all packs)",
    "custom": "Custom (admin list)",
}
TW_GLYPHS = {
    "default": "Aa",
    "off": "\u2026",
    "claude": "\u273a",
    "dev": "</>",
    "playful": "\u2728",
    "science": "\u2697",
    "hacker": ">_",
    "zen": "\u262f",
    "minimal": "\u00b7",
    "mix": "\u221e",
    "custom": "\u270e",
}
TW_FX_NAMES = {
    "default": "Default",
    "random": "Random (changes every phrase)",
    "shimmer": "Shimmer Sweep",
    "gradient": "Gradient Flow",
    "rainbow": "Rainbow",
    "neon": "Neon Flicker",
    "glow": "Soft Glow",
    "fade": "Fade Rise",
    "slide": "Slot Slide",
    "typewriter": "Typewriter",
    "scramble": "Decode / Scramble",
    "blur": "Blur In",
    "wave": "Letter Wave",
    "bounce": "Letter Drop",
    "cascade": "Letter Cascade",
    "glitch": "Glitch",
    "pop": "Pop",
    "flip": "Flip In",
    "reveal": "Wipe Reveal",
    "pulse": "Soft Pulse",
    "plain": "Plain",
}
TW_FX_POOL = [k for k in TW_FX_NAMES if k not in ("default", "random", "plain")]
TW_FONTS = {
    "mono": "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace;font-size:.92em",
    "serif": "font-family:Georgia,'Times New Roman',serif",
    "italic": "font-family:'Palatino Linotype',Palatino,'Book Antiqua',Georgia,serif;font-style:italic",
    "rounded": "font-family:ui-rounded,'SF Pro Rounded',Nunito,Quicksand,'Varela Round',system-ui,sans-serif;font-weight:600",
    "hand": "font-family:'Segoe Print','Bradley Hand','Chalkboard SE','Comic Sans MS','Comic Neue',cursive;font-size:1.05em",
    "caps": "text-transform:uppercase;letter-spacing:.14em;font-size:.78em;font-weight:600",
    "small": "font-variant:small-caps;letter-spacing:.08em;font-size:1.05em",
}
TW_FONT_NAMES = {
    "default": "Default",
    "random": "Random (changes every phrase)",
    "theme": "Match Theme",
    "mono": "Monospace",
    "serif": "Serif",
    "italic": "Elegant Italic",
    "rounded": "Rounded",
    "hand": "Handwritten",
    "caps": "Wide Caps",
    "small": "Small Caps",
}
TW_FONT_POOL = ["theme"] + list(TW_FONTS)
TW_COLORS = {
    "orange": ("#d97757", "#ffb59a", "#b4532f"),
    "blue": ("#3b82f6", "#93c5fd", "#1d4ed8"),
    "purple": ("#8b5cf6", "#c4b5fd", "#6d28d9"),
    "green": ("#10b981", "#6ee7b7", "#047857"),
    "pink": ("#ec4899", "#f9a8d4", "#be185d"),
    "gold": ("#f59e0b", "#fde68a", "#b45309"),
    "cyan": ("#06b6d4", "#67e8f9", "#0e7490"),
    "red": ("#ef4444", "#fca5a5", "#b91c1c"),
    "tangerine": ("#f97316", "#fdba74", "#c2410c"),
    "yellow": ("#eab308", "#fde047", "#a16207"),
    "lime": ("#84cc16", "#bef264", "#4d7c0f"),
    "teal": ("#14b8a6", "#5eead4", "#0f766e"),
    "sky": ("#0ea5e9", "#7dd3fc", "#0369a1"),
    "indigo": ("#6366f1", "#a5b4fc", "#4338ca"),
    "violet": ("#7c3aed", "#c4b5fd", "#5b21b6"),
    "fuchsia": ("#d946ef", "#f0abfc", "#a21caf"),
    "rose": ("#f43f5e", "#fda4af", "#be123c"),
    "brown": ("#92400e", "#d97706", "#451a03"),
    "grey": ("#6b7280", "#9ca3af", "#4b5563"),
    "silver": ("#9ca3af", "#e5e7eb", "#6b7280"),
    "white": ("#ffffff", "#e5e7eb", "#9ca3af"),
    "black": ("#111827", "#4b5563", "#000000"),
}
# True multi-stop gradients (start, middle, end). Painted across the whole phrase.
TW_GRADIENTS = {
    "aurora": ("#34d399", "#60a5fa", "#a78bfa"),
    "sunset": ("#f97316", "#ec4899", "#8b5cf6"),
    "ocean": ("#22d3ee", "#3b82f6", "#4338ca"),
    "fire": ("#fde047", "#f97316", "#dc2626"),
    "candy": ("#f472b6", "#c084fc", "#60a5fa"),
    "forest": ("#bef264", "#22c55e", "#0f766e"),
    "twilight": ("#6366f1", "#a855f7", "#f472b6"),
    "peach": ("#fb7185", "#fb923c", "#fbbf24"),
    "citrus": ("#facc15", "#a3e635", "#22c55e"),
    "berry": ("#be185d", "#9333ea", "#4f46e5"),
    "rosegold": ("#fb7185", "#f9a8d4", "#fbbf24"),
    "cyberpunk": ("#22d3ee", "#a855f7", "#ec4899"),
}
TW_COLORS.update(TW_GRADIENTS)
TW_COLOR_NAMES = {
    "default": "Default",
    "custom": "Custom (pick any color)",
    "random": "Random (changes every phrase)",
    "theme": "Match Theme",
    "orange": "Claude Orange",
    "blue": "Blue",
    "purple": "Purple",
    "green": "Green",
    "pink": "Pink",
    "gold": "Gold",
    "cyan": "Cyan",
    "red": "Red",
    "tangerine": "Orange (bright)",
    "yellow": "Yellow",
    "lime": "Lime",
    "teal": "Teal",
    "sky": "Sky Blue",
    "indigo": "Indigo",
    "violet": "Violet",
    "fuchsia": "Fuchsia",
    "rose": "Rose",
    "brown": "Brown",
    "grey": "Grey",
    "silver": "Silver",
    "white": "White",
    "black": "Black",
    "aurora": "Aurora (gradient)",
    "sunset": "Sunset (gradient)",
    "ocean": "Ocean (gradient)",
    "fire": "Fire (gradient)",
    "candy": "Candy (gradient)",
    "forest": "Forest (gradient)",
    "twilight": "Twilight (gradient)",
    "peach": "Peach (gradient)",
    "citrus": "Citrus (gradient)",
    "berry": "Berry (gradient)",
    "rosegold": "Rose Gold (gradient)",
    "cyberpunk": "Cyberpunk (gradient)",
}
TW_RHYTHM_NAMES = {
    "default": "Default",
    "steady": "Steady",
    "natural": "Natural (varies +/-40%)",
}
TW_TIMER_NAMES = {"default": "Default", "off": "Off", "on": "Show seconds"}

# ---------------------------------------------------------------------------
# 2.5.0: i18n — translations for all user-facing labels in the injected UI.
# Keys match the English originals; values are per-language dicts.
# ---------------------------------------------------------------------------
# {english_key: "fr|es|de|nl|it|pt"}
I18N_UI_RAW = {
    'Message Loading Indicator': 'Indicateur de chargement|Indicador de carga|Nachrichten-Ladeanzeige|Indicator bericht laden|Indicatore di caricamento del messaggio|Indicador de carregamento da mensagem',
    'How a reply shows that it is still loading. Saved in this browser.': "Comment une réponse indique qu'elle est encore en cours de chargement. Sauvegardé dans ce navigateur.|Cómo una respuesta indica que aún se está cargando. Guardado en este navegador.|Wie eine Antwort anzeigt, dass sie noch lädt. In diesem Browser gespeichert.|Hoe een antwoord aangeeft dat het nog laadt. Opgeslagen in deze browser.|Come una risposta indica che è ancora in caricamento. Salvato in questo browser.|Como uma resposta indica que ainda está a carregar. Guardado neste navegador.",
    'Thinking Indicator': 'Indicateur de réflexion|Indicador de razonamiento|Denkanzeige|Denkindicator|Indicatore di ragionamento|Indicador de raciocínio',
    'The icon beside the Thinking header while a model reasons. Saved in this browser.': "L'icône à côté de l'en-tête Réflexion pendant que le modèle raisonne. Sauvegardé dans ce navigateur.|El icono junto al encabezado Razonamiento mientras el modelo razona. Guardado en este navegador.|Das Symbol neben dem Denken-Header, während ein Modell überlegt. In diesem Browser gespeichert.|Het icoon naast de Denken-header terwijl een model redeneert. Opgeslagen in deze browser.|L'icona accanto all'intestazione Ragionamento mentre il modello ragiona. Salvato in questo browser.|O ícone junto ao cabeçalho Raciocínio enquanto o modelo raciocina. Guardado neste navegador.",
    'Thinking Words': 'Mots de réflexion|Palabras de razonamiento|Denkwörter|Denkwoorden|Parole di ragionamento|Palavras de raciocínio',
    'Rotating words shown instead of the plain “Thinking…” label while a model reasons. Saved in this browser.': 'Mots rotatifs affichés à la place du libellé « Réflexion… » pendant que le modèle raisonne. Sauvegardé dans ce navigateur.|Palabras rotativas en lugar de la etiqueta «Razonando…» mientras el modelo razona. Guardado en este navegador.|Rotierende Wörter statt der Beschriftung „Denkt nach…“, während ein Modell überlegt. In diesem Browser gespeichert.|Roterende woorden in plaats van het label “Aan het denken…” terwijl een model redeneert. Opgeslagen in deze browser.|Parole rotanti mostrate al posto della semplice etichetta «Riflessione…» mentre il modello ragiona. Salvato in questo browser.|Palavras giratórias em vez da etiqueta simples “A pensar…” enquanto o modelo raciocina. Guardado neste navegador.',
    'Thinking label': 'Libellé Réflexion|Etiqueta Razonamiento|Denken-Beschriftung|Denken-label|Etichetta Ragionamento|Etiqueta Raciocínio',
    'Phrase Effect': 'Effet de phrase|Efecto de frase|Phraseneffekt|Zinseffect|Effetto della frase|Efeito da frase',
    'How each phrase animates in. Random picks a different effect every time the phrase changes.': 'Animation de chaque phrase. Aléatoire choisit un effet différent à chaque changement.|Cómo se anima cada frase. Aleatorio elige un efecto diferente en cada cambio.|Wie jede Phrase animiert wird. Zufällig wählt bei jedem Wechsel einen anderen Effekt.|Hoe elke zin animeert. Willekeurig kiest bij elke wissel een ander effect.|Come ogni frase appare animata. Casuale sceglie un effetto diverso a ogni cambio di frase.|Como cada frase é animada. Aleatório escolhe um efeito diferente a cada mudança de frase.',
    'Phrase Font': 'Police de phrase|Fuente de frase|Phrasenschrift|Zinlettertype|Carattere della frase|Fonte da frase',
    'Typeface for the thinking phrases (fonts already on your device).': 'Police des phrases de réflexion (polices déjà sur votre appareil).|Tipografía de las frases de razonamiento (fuentes ya en tu dispositivo).|Schriftart für Denkphrasen (Bereits auf Ihrem Gerät vorhandene Schriften).|Lettertype voor de denkzinnen (lettertypen al op uw apparaat).|Carattere per le frasi di ragionamento (font già presenti sul dispositivo).|Tipo de letra para as frases de raciocínio (fontes já no seu dispositivo).',
    'Phrase Color': 'Couleur de phrase|Color de frase|Pharbenfarbe|Zinskleur|Colore della frase|Cor da frase',
    'Color or gradient of the thinking phrases.': 'Couleur ou dégradé des phrases de réflexion.|Color o degradado de las frases de razonamiento.|Farbe oder Verlauf der Denkphrasen.|Kleur of verloop van de denkzinnen.|Colore o sfumatura delle frasi di ragionamento.|Cor ou degradê das frases de raciocínio.',
    'Change Interval': 'Intervalle de changement|Intervalo de cambio|Wechselintervall|Wisselinterval|Intervallo di cambio|Intervalo de mudança',
    'How long each thinking phrase stays on screen. Drag left for faster, right for slower.': "Durée d'affichage de chaque phrase. Glissez à gauche pour accélérer, à droite pour ralentir.|Duración de cada frase en pantalla. Arrastra a la izquierda para acelerar, a la derecha para ralentizar.|Wie lange jede Denkphrase angezeigt wird. Nach links für schneller, nach rechts für langsamer.|Hoe lang elke denkzin op scherm blijft. Sleep naar links voor sneller, rechts voor langzamer.|Permanenza di ogni frase di ragionamento sullo schermo. Trascina a sinistra per velocizzare, a destra per rallentare.|Duração de cada frase de raciocínio no ecrã. Arraste para a esquerda para acelerar, para a direita para abrandar.",
    'Reset': 'Réinitialiser|Restablecer|Zurücksetzen|Herstel|Ripristina|Repor',
    'Custom Color': 'Couleur personnalisée|Color personalizado|Eigene Farbe|Aangepaste kleur|Colore personalizzato|Cor personalizada',
    'Pick any color, then choose “Custom” in Phrase Color above to use it.': 'Choisissez une couleur, puis sélectionnez « Personnalisée » dans Couleur de phrase ci-dessus.|Elige un color, luego selecciona «Personalizado» en Color de frase arriba.|Wählen Sie eine Farbe, dann „Eigene“ bei Pharbenfarbe oben.|Kies een kleur, selecteer daarna “Aangepast” bij Zinskleur hierboven.|Scegli un colore, poi seleziona «Personalizzato» in Colore della frase sopra per usarlo.|Escolha uma cor e depois selecione “Personalizada” em Cor da frase acima para a usar.',
    'Change Rhythm': 'Rythme de changement|Ritmo de cambio|Wechselrhythmus|Wisselritme|Ritmo di cambio|Ritmo de mudança',
    'Steady changes at exactly the interval; Natural varies each phrase by up to 40%.': "Régulier : changement exact à l'intervalle ; Naturel : varie chaque phrase de 40% max.|Constante cambia exactamente en el intervalo; Natural varía cada frase hasta un 40%.|Gleichmäßig wechselt genau im Intervall; Natürlich variiert jede Phrase um bis zu 40%.|Gelijkmatig wisselt exact op het interval; Natuurlijk varieert elke zin tot 40%.|Regolare cambia esattamente all'intervallo; Naturale varia ogni frase fino al 40%.|Constante muda exatamente no intervalo; Natural varia cada frase até 40%.",
    'Thinking Indicator Size': "Taille de l'indicateur de réflexion|Tamaño del indicador de razonamiento|Größe der Denkanzeige|Grootte denkindicator|Dimensione dell'indicatore di ragionamento|Tamanho do indicador de raciocínio",
    'Scale the icon beside the Thinking header. Drag right for larger, left for smaller. Saved in this browser.': "Redimensionne l'icône à côté de l'en-tête Réflexion. Glissez à droite pour agrandir, à gauche pour réduire. Sauvegardé dans ce navigateur.|Escala el icono junto al encabezado Razonamiento. Arrastra a la derecha para agrandar, a la izquierda para reducir. Guardado en este navegador.|Skaliert das Symbol neben der Denken-Überschrift. Nach rechts ziehen zum Vergrößern, nach links zum Verkleinern. In diesem Browser gespeichert.|Schaalt het icoon naast de denkkop. Sleep naar rechts voor groter, naar links voor kleiner. Opgeslagen in deze browser.|Ridimensiona l'icona accanto all'intestazione Ragionamento. Trascina a destra per ingrandire, a sinistra per rimpicciolire. Salvato in questo browser.|Redimensiona o ícone junto ao cabeçalho Raciocínio. Arraste para a direita para aumentar, para a esquerda para reduzir. Guardado neste navegador.",
    'Message Indicator Size': "Taille de l'indicateur de message|Tamaño del indicador de mensaje|Größe der Nachrichtenanzeige|Grootte berichtindicator|Dimensione dell'indicatore del messaggio|Tamanho do indicador da mensagem",
    'Scale the loading indicator shown in a reply. Drag right for larger, left for smaller. Does not affect the full-width Legacy Bars and Shimmer Lines styles. Saved in this browser.': "Redimensionne l'indicateur de chargement d'une réponse. Glissez à droite pour agrandir, à gauche pour réduire. Sans effet sur les styles pleine largeur Legacy Bars et Shimmer Lines. Sauvegardé dans ce navigateur.|Escala el indicador de carga de una respuesta. Arrastra a la derecha para agrandar, a la izquierda para reducir. No afecta a los estilos de ancho completo Legacy Bars y Shimmer Lines. Guardado en este navegador.|Skaliert die Ladeanzeige einer Antwort. Nach rechts ziehen zum Vergrößern, nach links zum Verkleinern. Wirkt nicht auf die Vollbreiten-Stile Legacy Bars und Shimmer Lines. In diesem Browser gespeichert.|Schaalt de laadindicator van een antwoord. Sleep naar rechts voor groter, naar links voor kleiner. Geldt niet voor de volledige-breedte stijlen Legacy Bars en Shimmer Lines. Opgeslagen in deze browser.|Ridimensiona l'indicatore di caricamento mostrato in una risposta. Trascina a destra per ingrandire, a sinistra per rimpicciolire. Non influisce sugli stili a larghezza intera Legacy Bars e Shimmer Lines. Salvato in questo browser.|Redimensiona o indicador de carregamento mostrado numa resposta. Arraste para a direita para aumentar, para a esquerda para reduzir. Não afeta os estilos de largura total Legacy Bars e Shimmer Lines. Guardado neste navegador.",
    'Thinking Timer': 'Minuteur de réflexion|Temporizador de razonamiento|Denk-Timer|Denk-timer|Cronometro di ragionamento|Cronómetro de raciocínio',
    'Show a live seconds counter next to the words.': 'Affiche un compteur de secondes en direct à côté des mots.|Muestra un contador de segundos en vivo junto a las palabras.|Zeigt einen Live-Sekundenzähler neben den Wörtern an.|Toon een live secondenteller naast de woorden.|Mostra un contatore di secondi in tempo reale accanto alle parole.|Mostra um contador de segundos em direto junto às palavras.',
    'Language': 'Langue|Idioma|Sprache|Taal|Lingua|Idioma',
    'Choose the language for the thinking words and these settings. Saved in this browser.': 'Choisissez la langue des mots de réflexion et de ces réglages. Sauvegardé dans ce navigateur.|Elige el idioma de las palabras de razonamiento y de estos ajustes. Guardado en este navegador.|Sprache für Denkphrasen und diese Einstellungen wählen. In diesem Browser gespeichert.|Kies de taal voor de denkwoorden en deze instellingen. Opgeslagen in deze browser.|Scegli la lingua delle parole di ragionamento e di queste impostazioni. Salvato in questo browser.|Escolha o idioma das palavras de raciocínio e destas definições. Guardado neste navegador.',
    'Auto (detect)': 'Auto (détection)|Auto (detectar)|Auto (erkennen)|Auto (detectie)|Auto (rilevamento)|Auto (deteção)',
    'Default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
}

I18N_PACK_NAMES_RAW = {
    'default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
    'off': 'Original « Pensée… »|Original «Pensando…»|Original „Denkt nach…“|Origineel “Aan het denken…”|Originale «Pensiero…»|Original “Pensando…”',
    'claude': 'Style Claude|Estilo Claude|Claude-Stil|Claude-stijl|Stile Claude|Estilo Claude',
    'dev': 'Dev & Debug|Dev & Debug|Dev & Debug|Dev & Debug|Dev & Debug|Dev & Depuração',
    'playful': 'Ludique|Divertido|Verspielt|Speels|Giocoso|Divertido',
    'science': 'Labo scientifique|Laboratorio|Wissenschaftslabor|Wetenschapslab|Laboratorio scientifico|Laboratório científico',
    'hacker': 'Terminal Hacker|Terminal Hacker|Hacker-Terminal|Hacker-terminal|Terminale Hacker|Terminal Hacker',
    'zen': 'Zen|Zen|Zen|Zen|Zen|Zen',
    'minimal': 'Minimal|Mínimo|Minimal|Minimaal|Minimale|Mínimo',
    'mix': 'Mélange aléatoire (tous packs)|Mezcla aleatoria (todos)|Zufallsmix (alle Packs)|Willekeurige mix (alle packs)|Mix casuale (tutti i pack)|Mistura aleatória (todos os pacotes)',
    'custom': 'Personnalisé (liste admin)|Personalizado (lista admin)|Eigene (Admin-Liste)|Aangepast (adminlijst)|Personalizzato (lista admin)|Personalizado (lista admin)',
}

I18N_FX_NAMES_RAW = {
    'default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
    'random': 'Aléatoire (change à chaque phrase)|Aleatorio (cambia en cada frase)|Zufällig (wechselt bei jeder Phrase)|Willekeurig (wisselt bij elke zin)|Casuale (cambia a ogni frase)|Aleatório (muda a cada frase)',
    'shimmer': 'Balayage lumineux|Barrido brillante|Schimmer-Sweep|Glansveeg|Scintillio luminoso|Brilho deslizante',
    'gradient': 'Dégradé fluide|Degradado fluido|Farbverlauf|Kleurverloop|Gradiente fluido|Degradê fluido',
    'rainbow': 'Arc-en-ciel|Arcoíris|Regenbogen|Regenboog|Arcobaleno|Arco-íris',
    'neon': 'Néon clignotant|Neón parpadeante|Neon-Flackern|Neon-flikkering|Neon tremolante|Neon cintilante',
    'glow': 'Lueur douce|Resplandor suave|Weiches Leuchten|Zachte gloed|Bagliore morbido|Brilho suave',
    'fade': 'Fondu montant|Fundido ascendente|Aufblenden|Opkomende fade|Comparsa in dissolvenza|Surgir em desvanecimento',
    'slide': 'Glissement|Deslizamiento|Slot-Glide|Verschuiving|Scorrimento a slot|Deslizamento',
    'typewriter': 'Machine à écrire|Máquina de escribir|Schreibmaschine|Typmachine|Macchina da scrivere|Máquina de escrever',
    'scramble': 'Décodage / Brouillage|Descifrado / Barajar|Decodieren / Scramble|Decoderen / warrelen|Decodifica / Mescolamento|Decodificação / Embaralhado',
    'blur': "Flou d'entrée|Desenfoque de entrada|Weichzeichner|Vage ingang|Sfocatura in entrata|Desfoque de entrada",
    'wave': 'Vague de lettres|Ola de letras|Buchstabenwelle|Lettersgolf|Onda di lettere|Onda de letras',
    'bounce': 'Chute de lettres|Caída de letras|Buchstabenfall|Dalende letters|Caduta di lettere|Queda de letras',
    'cascade': 'Cascade de lettres|Cascada de letras|Buchstabenkaskade|Letterscascade|Cascata di lettere|Cascata de letras',
    'glitch': 'Glitch|Glitch|Glitch|Glitch|Glitch|Glitch',
    'pop': 'Pop|Pop|Pop|Pop|Pop|Pop',
    'flip': 'Retournement|Volteo|Drehen|Omdraaien|Capovolgimento|Virada',
    'reveal': 'Révélation|Revelado|Wisch-Enthüllung|Veegonthulling|Rivelazione a cancellino|Revelação com limpeza',
    'pulse': 'Pulsation douce|Pulso suave|Sanfter Puls|Zachte puls|Pulsazione morbida|Pulsação suave',
    'plain': 'Simple|Simple|Einfach|Eenvoudig|Semplice|Simples',
}

I18N_FONT_NAMES_RAW = {
    'default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
    'random': 'Aléatoire (change à chaque phrase)|Aleatorio (cambia en cada frase)|Zufällig (wechselt bei jeder Phrase)|Willekeurig (wisselt bij elke zin)|Casuale (cambia a ogni frase)|Aleatório (muda a cada frase)',
    'theme': 'Correspondre au thème|Coincide con el tema|Theme anpassen|Thema volgen|Abbina al tema|Corresponder ao tema',
    'mono': 'Monospace|Monoespaciada|Monospace|Monospace|Monospazio|Monoespaçada',
    'serif': 'Serif|Serif|Serif|Serif|Serif|Serifada',
    'italic': 'Italique élégant|Cursiva elegante|Elegante Kursiv|Elegant cursief|Corsivo elegante|Itálico elegante',
    'rounded': 'Arrondi|Redondeada|Abgerundet|Afgerond|Arrotondato|Arredondada',
    'hand': 'Manuscrit|Manuscrita|Handschrift|Handgeschreven|Scrittura a mano|Manuscrita',
    'caps': 'Capitales larges|Mayúsculas anchas|Breite Großbuchstaben|Brede hoofdletters|Maiuscole ampie|Maiúsculas largas',
    'small': 'Petites capitales|Pequeñas mayúsculas|Kapitälchen|Kleine kapitalen|Maiuscoletto|Maiúsculas pequenas',
}

I18N_RHYTHM_NAMES_RAW = {
    'default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
    'steady': 'Régulier|Constante|Gleichmäßig|Gelijkmatig|Regolare|Constante',
    'natural': 'Naturel (varie +/-40%)|Natural (varía +/-40%)|Natürlich (variiert +/-40%)|Natuurlijk (varieert +/-40%)|Naturale (varia +/-40%)|Natural (varia +/-40%)',
}

I18N_TIMER_NAMES_RAW = {
    'default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
    'off': 'Désactivé|Apagado|Aus|Uitgeschakeld|Disattivato|Desativado',
    'on': 'Afficher les secondes|Mostrar segundos|Sekunden anzeigen|Seconden tonen|Mostra i secondi|Mostrar segundos',
}

I18N_COLOR_NAMES_RAW = {
    'default': 'Par défaut|Por defecto|Standard|Standaard|Predefinito|Padrão',
    'custom': 'Personnalisé (choisir une couleur)|Personalizado (elige un color)|Eigene (Farbe wählen)|Aangepast (kies een kleur)|Personalizzato (scegli un colore)|Personalizado (escolha uma cor)',
    'random': 'Aléatoire (change à chaque phrase)|Aleatorio (cambia en cada frase)|Zufällig (wechselt bei jeder Phrase)|Willekeurig (wisselt bij elke zin)|Casuale (cambia a ogni frase)|Aleatório (muda a cada frase)',
    'theme': 'Correspondre au thème|Coincide con el tema|Theme anpassen|Thema volgen|Abbina al tema|Corresponder ao tema',
    'orange': 'Orange Claude|Naranja Claude|Claude Orange|Claude Oranje|Arancione Claude|Laranja Claude',
    'blue': 'Bleu|Azul|Blau|Blauw|Blu|Azul',
    'purple': 'Violet|Morado|Lila|Paars|Viola|Roxo',
    'green': 'Vert|Verde|Grün|Groen|Verde|Verde',
    'pink': 'Rose|Rosa|Rosa|Roze|Rosa|Rosa',
    'gold': 'Or|Dorado|Gold|Goud|Oro|Dourado',
    'cyan': 'Cyan|Cian|Cyan|Cyaan|Ciano|Ciano',
    'red': 'Rouge|Rojo|Rot|Rood|Rosso|Vermelho',
    'tangerine': 'Orange (vif)|Naranja (brillante)|Orange (hell)|Oranje (fel)|Arancione (vivace)|Laranja (brilhante)',
    'yellow': 'Jaune|Amarillo|Gelb|Geel|Giallo|Amarelo',
    'lime': 'Citron vert|Lima|Limette|Limoengroen|Lime|Verde-lima',
    'teal': 'Bleu-vert|Ver azulado|Blaugrün|Blauwgroen|Verde acqua|Verde-azulado',
    'sky': 'Bleu ciel|Azul cielo|Himmelblau|Hemelblauw|Azzurro|Azul-celeste',
    'indigo': 'Indigo|Índigo|Indigo|Indigo|Indaco|Índigo',
    'violet': 'Violet|Violeta|Violett|Violet|Violetto|Violeta',
    'fuchsia': 'Fuchsia|Fucsia|Fuchsia|Fuchsia|Fucsia|Fúcsia',
    'rose': 'Rose|Rosa|Rose|Roos|Rosa|Rosa',
    'brown': 'Marron|Marrón|Braun|Bruin|Marrone|Marrom',
    'grey': 'Gris|Gris|Grau|Grijs|Grigio|Cinza',
    'silver': 'Argent|Plata|Silber|Zilver|Argento|Prata',
    'white': 'Blanc|Blanco|Weiß|Wit|Bianco|Branco',
    'black': 'Noir|Negro|Schwarz|Zwart|Nero|Preto',
}

# ---------------------------------------------------------------------------
# 2.5.0: Translated thinking-word packs (FR, ES, DE, NL, IT, PT).
# Structure: TW_PACKS_I18N[lang][pack_name] = [words...]
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Expand the compact sources into the runtime shapes the JS + _loader_fragment
# depend on. These keep EXACTLY the same names/structure as before the refactor.
# ---------------------------------------------------------------------------
TW_PACKS, TW_PACKS_I18N = _expand_pack(TW_PACKS_RAW, LANG_ORDER)
I18N_UI = _expand_labels(I18N_UI_RAW, LANG_ORDER)
I18N_PACK_NAMES = _expand_labels(I18N_PACK_NAMES_RAW, LANG_ORDER)
I18N_FX_NAMES = _expand_labels(I18N_FX_NAMES_RAW, LANG_ORDER)
I18N_FONT_NAMES = _expand_labels(I18N_FONT_NAMES_RAW, LANG_ORDER)
I18N_COLOR_NAMES = _expand_labels(I18N_COLOR_NAMES_RAW, LANG_ORDER)
I18N_RHYTHM_NAMES = _expand_labels(I18N_RHYTHM_NAMES_RAW, LANG_ORDER)
I18N_TIMER_NAMES = _expand_labels(I18N_TIMER_NAMES_RAW, LANG_ORDER)

TW_PACK_LITERAL = Literal[tuple(k for k in TW_PACK_NAMES if k != "default")]
TW_FX_LITERAL = Literal[tuple(k for k in TW_FX_NAMES if k != "default")]
TW_FONT_LITERAL = Literal[tuple(k for k in TW_FONT_NAMES if k != "default")]
TW_COLOR_LITERAL = Literal[tuple(k for k in TW_COLOR_NAMES if k != "default")]
TW_RHYTHM_LITERAL = Literal[tuple(k for k in TW_RHYTHM_NAMES if k != "default")]

TW_CSS_BASE = r"""
:root{--tw-a:#6b7280;--tw-b:#111827;--tw-c:#9ca3af;--osk-tw-dur:2400ms}
html.dark{--tw-a:#8e8e93;--tw-b:#ffffff;--tw-c:#636366}
.osk-orig{display:none!important}
.osk-nosh{background:none!important;animation:none!important}
.osk-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.osk-tw{display:inline-flex;align-items:baseline;gap:0;vertical-align:baseline;max-width:100%}
.osk-tw[data-clip="1"]{clip-path:inset(0)}
.osk-tw-w,.osk-pv-s{display:inline-block;position:relative;white-space:nowrap;color:var(--tw-a);-webkit-text-fill-color:var(--tw-a);font-weight:500;line-height:1.3}
.osk-pv.osk-pv-t{width:88px}
.osk-pv.osk-pv-t>span{display:inline-block}
.osk-pv-s{--osk-tw-dur:2600ms;font-size:.8rem;margin-left:4px}
.osk-pv-t:has(.osk-pv-s[data-fx="slide"]){clip-path:inset(0)}
.osk-l{display:inline-block}
.osk-tw-d{display:none}
html[data-osk-tw-dots] .osk-tw-d{display:inline-flex;margin-left:.06em;letter-spacing:0;line-height:1.3}
.osk-tw-d i{font-style:normal;color:var(--tw-a);-webkit-text-fill-color:var(--tw-a);animation:osk-tw-dot 1.2s infinite}
.osk-tw-d i::before{content:'.'}
.osk-tw-d i:nth-child(2){animation-delay:.2s}
.osk-tw-d i:nth-child(3){animation-delay:.4s}
.osk-tw-t{display:none;margin-left:.3em;opacity:.55;font-size:.9em;font-variant-numeric:tabular-nums;-webkit-text-fill-color:currentColor}
html[data-osk-tw-timer="on"] .osk-tw-t{display:inline}
.osk-tw-t::before{content:'\00b7\00a0'}
.osk-heading{margin:.85rem 0 .5rem;font-size:.6875rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--color-gray-400,#9ca3af)}
.osk-range-row{display:flex;align-items:center;gap:8px}
.osk-range{width:128px;height:4px;cursor:pointer;accent-color:#d97757}
.osk-range-v{min-width:2.4rem;text-align:right;font-size:.75rem;font-variant-numeric:tabular-nums;color:var(--color-gray-500,#6b7280)}
.osk-range-r{padding:0;border:0;background:none;font-size:.6875rem;text-decoration:underline;cursor:pointer;color:var(--color-gray-400,#9ca3af)}
.osk-range-r[hidden]{display:none}
.osk-pv-s[data-color="random"]{--tw-a:#f87171;--tw-b:#fbbf24;--tw-c:#60a5fa}
.osk-pv-s[data-color="random"]{background:linear-gradient(90deg,var(--tw-a),var(--tw-b),var(--tw-c));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.osk-tw-w[data-grad="1"]{background-image:linear-gradient(90deg,var(--tw-a),var(--tw-b),var(--tw-c));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
@keyframes osk-tw-shim2{from{background-position:200% 0,0 0}to{background-position:-100% 0,0 0}}
@keyframes osk-tw-in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
@keyframes osk-tw-out{from{opacity:1;transform:none}to{opacity:0;transform:translateY(-5px)}}
@keyframes osk-tw-shim{from{background-position:200% 0}to{background-position:-100% 0}}
@keyframes osk-tw-flow{from{background-position:0 0}to{background-position:300% 0}}
@keyframes osk-tw-slidein{from{transform:translateY(115%);opacity:0}to{transform:none;opacity:1}}
@keyframes osk-tw-slideout{from{transform:none;opacity:1}to{transform:translateY(-115%);opacity:0}}
@keyframes osk-tw-type{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
@keyframes osk-tw-caret{50%{background:transparent}}
@keyframes osk-tw-blurin{from{filter:blur(10px);opacity:0}to{filter:none;opacity:1}}
@keyframes osk-tw-blurout{from{filter:none;opacity:1}to{filter:blur(10px);opacity:0}}
@keyframes osk-tw-glow{from{text-shadow:0 0 2px var(--tw-a),0 0 6px var(--tw-a)}to{text-shadow:0 0 7px var(--tw-b),0 0 18px var(--tw-a)}}
@keyframes osk-tw-flick{0%,19%,21%,23%,25%,54%,56%,100%{opacity:1}20%,24%,55%{opacity:.3}}
@keyframes osk-tw-bob{0%,60%,100%{transform:none}30%{transform:translateY(-3px)}}
@keyframes osk-tw-drop{from{transform:translateY(-1.1em);opacity:0}to{transform:none;opacity:1}}
@keyframes osk-tw-gl{0%,88%,100%{opacity:0;transform:none}91%{opacity:.9;transform:translate(-3px,1px)}95%{opacity:.9;transform:translate(3px,-1px)}}
@keyframes osk-tw-glm{0%,89%,100%{transform:none}91%{transform:translate(-2px,0) skewX(10deg)}94%{transform:translate(2px,1px) skewX(-8deg)}96%{transform:none}}
@keyframes osk-tw-pop{from{transform:scale(.5);opacity:0}to{transform:none;opacity:1}}
@keyframes osk-tw-flip{from{transform:perspective(220px) rotateX(-90deg);opacity:0}to{transform:perspective(220px) rotateX(0);opacity:1}}
@keyframes osk-tw-reveal{from{-webkit-mask-position:100% 0;mask-position:100% 0}to{-webkit-mask-position:0 0;mask-position:0 0}}
@keyframes osk-tw-pulse{0%,100%{opacity:.5}50%{opacity:1}}
@keyframes osk-tw-dot{0%,80%,100%{opacity:.2}40%{opacity:1}}
"""


def _tw_css() -> str:
    out = [TW_CSS_BASE.strip()]
    OUTD = "max(0s,calc(var(--osk-tw-dur) - .45s))"
    clip = "-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent"

    def fx(k, decl, pseudo="", child=""):
        out.append(
            f'.osk-tw-w[data-fx="{k}"]{child}{pseudo},.osk-pv-s[data-fx="{k}"]{child}{pseudo}{{{decl}}}'
        )

    fx(
        "shimmer",
        "background:linear-gradient(100deg,var(--tw-a) 38%,var(--tw-b) 50%,var(--tw-a) 62%) 200% 0/250% 100%;"
        + clip
        + ";animation:osk-tw-in .4s ease both,osk-tw-shim 1.8s linear infinite",
    )
    fx(
        "gradient",
        "background:linear-gradient(90deg,var(--tw-a),var(--tw-b),var(--tw-c),var(--tw-a)) 0 0/300% 100%;"
        + clip
        + ";animation:osk-tw-in .4s ease both,osk-tw-flow 3s linear infinite",
    )
    fx(
        "rainbow",
        "background:linear-gradient(90deg,#f87171,#fbbf24,#34d399,#60a5fa,#a78bfa,#f87171) 0 0/300% 100%;"
        + clip
        + ";animation:osk-tw-in .4s ease both,osk-tw-flow 3.5s linear infinite",
    )
    fx(
        "neon",
        "color:var(--tw-b);-webkit-text-fill-color:var(--tw-b);text-shadow:0 0 4px var(--tw-a),0 0 12px var(--tw-a),0 0 26px var(--tw-a);animation:osk-tw-in .3s ease both,osk-tw-flick 3s linear infinite",
    )
    fx(
        "glow",
        "color:var(--tw-b);-webkit-text-fill-color:var(--tw-b);animation:osk-tw-in .4s ease both,osk-tw-glow 1.6s ease-in-out infinite alternate",
    )
    fx(
        "fade",
        f"animation:osk-tw-in .4s ease both,osk-tw-out .4s ease-in {OUTD} forwards",
    )
    fx(
        "slide",
        f"animation:osk-tw-slidein .45s cubic-bezier(.2,.8,.2,1) both,osk-tw-slideout .4s ease-in {OUTD} forwards",
    )
    fx(
        "typewriter",
        "animation:osk-tw-type min(1s,calc(var(--osk-tw-dur)*.45)) steps(var(--n,12),end) both",
    )
    fx(
        "typewriter",
        "content:'';display:inline-block;width:.09em;height:1em;margin-left:2px;vertical-align:-.14em;background:var(--tw-a);-webkit-text-fill-color:initial;animation:osk-tw-caret .8s step-end infinite",
        "::after",
    )
    fx(
        "scramble",
        "font-variant-numeric:tabular-nums;letter-spacing:.02em;animation:osk-tw-in .2s ease both",
    )
    fx(
        "blur",
        f"animation:osk-tw-blurin .6s ease both,osk-tw-blurout .5s ease-in {OUTD} forwards",
    )
    fx("wave", "animation:osk-tw-in .4s ease both")
    fx(
        "wave",
        "animation:osk-tw-bob 1.4s ease-in-out infinite;animation-delay:calc(var(--i,0)*70ms)",
        child=" .osk-l",
    )
    fx(
        "bounce",
        "animation:osk-tw-drop .6s cubic-bezier(.3,1.6,.5,1) both;animation-delay:calc(var(--i,0)*45ms)",
        child=" .osk-l",
    )
    fx(
        "cascade",
        "animation:osk-tw-in .5s ease both;animation-delay:calc(var(--i,0)*40ms)",
        child=" .osk-l",
    )
    fx("glitch", "animation:osk-tw-in .3s ease both,osk-tw-glm 2.4s steps(1) infinite")
    g = "content:attr(data-text);position:absolute;left:0;top:0;opacity:0;pointer-events:none;-webkit-text-fill-color:currentColor"
    fx("glitch", g + ";color:#22d3ee;animation:osk-tw-gl 2.4s infinite", "::before")
    fx(
        "glitch",
        g + ";color:#f472b6;animation:osk-tw-gl 2.4s .08s infinite reverse",
        "::after",
    )
    fx("pop", "animation:osk-tw-pop .5s cubic-bezier(.3,1.7,.5,1) both")
    fx("flip", "transform-origin:50% 60%;animation:osk-tw-flip .6s ease both")
    fx(
        "reveal",
        "-webkit-mask-image:linear-gradient(90deg,#000 45%,transparent 65%);mask-image:linear-gradient(90deg,#000 45%,transparent 65%);-webkit-mask-size:300% 100%;mask-size:300% 100%;animation:osk-tw-reveal 1s ease both",
    )
    fx(
        "pulse",
        "animation:osk-tw-in .4s ease both,osk-tw-pulse 1.6s ease-in-out .4s infinite",
    )

    # Shimmer over a gradient: keep the gradient as base, sweep a highlight on top.
    out.append(
        '.osk-tw-w[data-fx="shimmer"][data-grad="1"]{'
        "background:linear-gradient(100deg,transparent 38%,rgba(255,255,255,.8) 50%,transparent 62%) 200% 0/250% 100% no-repeat,"
        "linear-gradient(90deg,var(--tw-a),var(--tw-b),var(--tw-c)) 0 0/100% 100% no-repeat;"
        + clip
        + ";animation:osk-tw-in .4s ease both,osk-tw-shim2 1.8s linear infinite}"
    )
    # Gradient colors in the dropdown preview.
    out.append(
        ",".join(f'.osk-pv-s[data-color="{k}"]' for k in TW_GRADIENTS)
        + "{background:linear-gradient(90deg,var(--tw-a),var(--tw-b),var(--tw-c));"
        + clip
        + "}"
    )

    for k, decl in TW_FONTS.items():
        out.append(f'.osk-tw-w[data-font="{k}"],.osk-pv-s[data-font="{k}"]{{{decl}}}')
    for k, (a, b, c) in TW_COLORS.items():
        out.append(
            f'html[data-osk-tw-color="{k}"],.osk-pv-s[data-color="{k}"]{{--tw-a:{a};--tw-b:{b};--tw-c:{c}}}'
        )
    # Custom color: the picker writes --osk-tw-custom-a/b/c on <html>.
    out.append(
        'html[data-osk-tw-color="custom"],.osk-pv-s[data-color="custom"]{'
        "--tw-a:var(--osk-tw-custom-a,#d97757);--tw-b:var(--osk-tw-custom-b,#ffb59a);--tw-c:var(--osk-tw-custom-c,#b4532f)}"
        ".osk-colorin{width:30px;height:20px;padding:0;border:1px solid var(--color-gray-300,#d1d5db);border-radius:4px;background:none;cursor:pointer}"
    )
    out.append(
        "@media (prefers-reduced-motion:reduce){.osk-tw-w,.osk-tw-w::before,.osk-tw-w::after,.osk-l,.osk-tw-d i,.osk-pv-s{"
        "animation:none!important;background:none!important;clip-path:none!important;filter:none!important;text-shadow:none!important;"
        "-webkit-mask-image:none!important;mask-image:none!important;-webkit-text-fill-color:var(--tw-a)!important}"
        ".osk-tw-w::before,.osk-tw-w::after{display:none}}"
    )
    return "\n".join(out)


TW_CSS = _tw_css()

OSK_CSS = "\n".join(
    [
        OSK_CSS_BASE.strip(),
        OSK_CSS_NEW.strip(),
        MORE_CSS,
        _build_generated_css(),
        TW_CSS,
    ]
)

LOADER_SCRIPT = r"""
(function () {
  'use strict';
  if (window.__owuiMessageIndicator) return;
  window.__owuiMessageIndicator = true;

  var CFG = __CONFIG__;
  var CSS = __CSS__;
  var ROOT = document.documentElement;

  // --- i18n: active language (user picker > admin valve (explicit only) > <html lang> > en) ---
  // A language counts if it has a UI pack OR a translated word pack (so e.g.
  // 'nl' resolves even before every UI string is translated).
  var hasPack = function (l) {
    return !!(l && ((CFG.i18n && CFG.i18n[l]) || (CFG.tw && CFG.tw.packsI18n && CFG.tw.packsI18n[l])));
  };
  var KEY_LANG = 'owui-language';
  function resolveLang() {
    // 1) Explicit user choice wins. 'default'/'auto' both mean auto-detect.
    var stored = null;
    try { stored = localStorage.getItem(KEY_LANG); } catch (e) {}
    if (stored && stored !== 'default' && stored !== 'auto' && (stored === 'en' || hasPack(stored))) return stored;
    // 2) Admin valve, but only when it forces an EXPLICIT language ('auto'/'default' = detect).
    var forced = CFG.language;
    if (forced && forced !== 'auto' && forced !== 'default') return forced;
    // 3) Open WebUI interface language = <html lang>. navigator.language is
    //    deliberately NOT consulted (browser language is not a source here).
    var htmlLang = (ROOT.getAttribute('lang') || '').slice(0, 2).toLowerCase();
    if (htmlLang && hasPack(htmlLang)) return htmlLang;
    // 4) Final fallback.
    return 'en';
  }
  var LANG = resolveLang();
  // Live switch: the language picker writes data-osk-language on <html>, and Open
  // WebUI sets <html lang> late (Svelte hydration). Observe BOTH attributes so
  // LANG re-resolves when OWUI changes the interface language, then force mounted
  // thinking words to re-render immediately (LANG is part of the thinking sig()).
  if (window.MutationObserver) {
    new MutationObserver(function () {
      var prev = LANG;
      LANG = resolveLang();
      if (LANG !== prev) { if (TW && TW.refresh) TW.refresh(); schedule(); }
    }).observe(ROOT, { attributes: true, attributeFilter: ['data-osk-language', 'lang'] });
  }
  // Helper: translate a UI label via CFG.i18n, fallback to the English key.
  function t(key) {
    return (CFG.i18n && CFG.i18n[LANG] && CFG.i18n[LANG][key]) || key;
  }
  // Helper: get localized names dict for a picker, fallback to English.
  function locNames(names, i18nDict) {
    if (LANG === 'en' || !i18nDict || !i18nDict[LANG]) return names;
    var out = {};
    Object.keys(names).forEach(function (k) {
      out[k] = (i18nDict[LANG][k] || names[k]);
    });
    return out;
  }
  // Localized style/picker names
  var NAMES_MSG = locNames(CFG.names, null); // style names not translated (technical)
  var NAMES_TW_PACK = locNames(CFG.tw.packNames, CFG.i18nPackNames);
  var NAMES_TW_FX = locNames(CFG.tw.fxNames, CFG.i18nFxNames);
  var NAMES_TW_FONT = locNames(CFG.tw.fontNames, CFG.i18nFontNames);
  var NAMES_TW_COLOR = locNames(CFG.tw.colorNames, CFG.i18nColorNames);
  var NAMES_TW_RHYTHM = locNames(CFG.tw.rhythmNames, CFG.i18nRhythmNames);
  var NAMES_TW_TIMER = locNames(CFG.tw.timerNames, CFG.i18nTimerNames);
  // Language picker names: language names stay in their own language (standard
  // practice for language pickers). ONE single auto entry: 'default' = auto
  // detection of the Open WebUI interface language (<html lang>). The old
  // duplicate 'auto' key is gone (legacy stored 'auto' falls back to 'default').
  var NAMES_LANGUAGE = {
    'default': t('Auto (detect)'),
    'en': 'English', 'fr': 'français', 'es': 'español', 'de': 'Deutsch',
    'nl': 'Nederlands', 'it': 'italiano', 'pt': 'português'
  };
  var MARKUP =
    '<span class="osk-bars"><span class="osk-bars-in">' +
    '<span class="osk-b osk-r1"></span>' +
    '<span class="osk-g3"><span class="osk-b osk-s2"></span><span class="osk-b"></span></span>' +
    '<span class="osk-g4"><span class="osk-b"></span><span class="osk-b osk-s2"></span><span class="osk-b osk-mr4"></span></span>' +
    '<span class="osk-b"></span>' +
    '</span></span>' +
    '<span class="osk-dot"><span class="osk-dot-ring"></span><span class="osk-dot-core"></span></span>' +
    '<span class="osk-cursor"></span>' +
    '<span class="osk-block"></span>' +
    '<span class="osk-typing"><span></span><span></span><span></span></span>' +
    '<span class="osk-wave"><span></span><span></span><span></span><span></span></span>' +
    '<span class="osk-spinner"></span>' +
    '<span class="osk-shimmer"><span class="osk-shimmer-in">' +
    '<span class="osk-sh"></span><span class="osk-sh"></span><span class="osk-sh"></span>' +
    '</span></span>' +
    '<span class="osk-ellipsis"><span></span><span></span><span></span></span>' +
    '<span class="osk-scanner"><span></span></span>' +
    '<span class="osk-orbit"><span></span><span></span></span>' +
    '<span class="osk-ripple"><span></span><span></span></span>' +
    '<span class="osk-breathe"></span>' +
    '<span class="osk-grid"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></span>' +
    '<span class="osk-flip"></span>' +
    '<span class="osk-sparkle"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 0c.6 6.6 4.8 11.4 12 12-7.2.6-11.4 5.4-12 12C11.4 17.4 6.6 12.6 0 12 6.6 11.4 11.4 6.6 12 0z"/></svg></span>' +
    '<span class="osk-heartbeat"><svg viewBox="0 0 28 14" aria-hidden="true"><path pathLength="50" d="M0 7h7l2-4 3 8 2-10 3 8 2-2h9"/></svg></span>' +
    '<span class="osk-ball"><span></span></span>' +
    __MORE_MARKUP__;
  var CHEVRON =
    '<svg class="osk-chev" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" aria-hidden="true">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5"/></svg>';
  var CHECK =
    '<svg class="osk-opt-check" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" aria-hidden="true">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5"/></svg>';
  var scheduled = false;
  var openPicker = null;

  // One picker = one setting row (trigger + dropdown) bound to one localStorage key
  // and one attribute on <html>. The message and thinking settings share this code.
  function makePicker(spec) {
    var NAMES = spec.names;
    var ORDER = Object.keys(NAMES);
    var trigger = null;
    var menu = null;
    var self = {};

    function choice() {
      var value = null;
      try { value = localStorage.getItem(spec.key); } catch (e) {}
      return ORDER.indexOf(value) === -1 ? 'default' : value;
    }

    function effective() {
      var value = choice();
      return value === 'default' ? spec.fallback : value;
    }

    var POOL = ORDER.filter(function (k) { return k !== 'default' && k !== 'none' && k !== 'random'; });

    function roll() {
      var cur = ROOT.getAttribute(spec.attr);
      var pick = cur;
      for (var tries = 0; tries < 8 && (pick === cur || !pick); tries++) pick = POOL[Math.floor(Math.random() * POOL.length)];
      ROOT.setAttribute(spec.attr, pick);
    }

    function apply() {
      var value = effective();
      if (value === 'random' && spec.roll) roll();
      else if (value === 'default') ROOT.removeAttribute(spec.attr);
      else ROOT.setAttribute(spec.attr, value);
    }

    function label(value) {
      if (value !== 'default' || spec.fallback === 'default') return NAMES[value];
      // Language picker: fallback is 'auto', which has no NAMES entry -> show
      // the single 'default' label ("Auto (détection)") without a redundant suffix.
      var fb = NAMES[spec.fallback];
      return fb ? NAMES.default + ' (' + fb + ')' : NAMES.default;
    }

    function preview(value) {
      var shown = value === 'default' ? spec.fallback : value;
      if (shown === 'default' && spec.defaultPreview) shown = spec.defaultPreview;
      if (spec.preview) return spec.preview(shown, value);
      var el = document.createElement('span');
      el.className = 'osk-pv';
      el.setAttribute('aria-hidden', 'true');
      if (shown === 'random') {
        el.textContent = '\uD83C\uDFB2';
        el.style.paddingLeft = '4px';
      } else if (shown !== 'default' && shown !== 'none') {
        el.setAttribute('data-pv', shown);
        el.innerHTML = MARKUP;
      }
      return el;
    }

    function renderTrigger() {
      if (!trigger) return;
      var value = choice();
      var mode = document.createElement('span');
      mode.id = spec.id + '-mode';
      mode.textContent = label(value);
      trigger.replaceChildren(preview(value), mode);
      trigger.insertAdjacentHTML('beforeend', CHEVRON);
    }

    function placeMenu() {
      if (!menu || !trigger) return;
      var rect = trigger.getBoundingClientRect();
      var gap = 4;
      var pad = 16;
      var height = menu.offsetHeight;
      var width = menu.offsetWidth;
      var below = window.innerHeight - rect.bottom - gap;
      var above = rect.top - gap;
      var top = below < height && above > below ? rect.top - gap - height : rect.bottom + gap;
      var left = Math.min(rect.right - width, window.innerWidth - width - pad);
      menu.style.top = Math.max(pad, top) + 'px';
      menu.style.left = Math.max(pad, left) + 'px';
    }

    function closeMenu(refocus) {
      if (!menu) return;
      menu.remove();
      menu = null;
      if (openPicker === self) openPicker = null;
      window.removeEventListener('keydown', onMenuKey, true);
      document.removeEventListener('pointerdown', onOutside, true);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', placeMenu, true);
      if (!trigger) return;
      trigger.setAttribute('aria-expanded', 'false');
      if (refocus && trigger.isConnected) trigger.focus();
    }

    function pick(value) {
      try { localStorage.setItem(spec.key, value); } catch (e) {}
      apply();
      renderTrigger();
      closeMenu(true);
    }

    function onOutside(evt) {
      if (menu && !menu.contains(evt.target) && !(trigger && trigger.contains(evt.target))) closeMenu(false);
    }

    function onResize() {
      closeMenu(false);
    }

    function onMenuKey(evt) {
      var items = menu ? Array.prototype.slice.call(menu.querySelectorAll('[role="option"]')) : [];
      var at = items.indexOf(document.activeElement);
      var to = -1;
      if (evt.key === 'Escape') closeMenu(true);
      else if (evt.key === 'Tab') { closeMenu(true); return; }
      else if (evt.key === 'ArrowDown') to = at < 0 ? 0 : Math.min(at + 1, items.length - 1);
      else if (evt.key === 'ArrowUp') to = at < 0 ? items.length - 1 : Math.max(at - 1, 0);
      else if (evt.key === 'Home') to = 0;
      else if (evt.key === 'End') to = items.length - 1;
      else if ((evt.key === 'Enter' || evt.key === ' ') && at >= 0) pick(items[at].getAttribute('data-value'));
      else return;
      evt.preventDefault();
      evt.stopPropagation();
      if (to >= 0) items[to].focus();
    }

    function openMenu() {
      if (menu || !trigger) return;
      if (openPicker && openPicker !== self) openPicker.closeMenu(false);
      openPicker = self;
      var current = choice();
      var selected = null;
      menu = document.createElement('div');
      menu.id = spec.id + '-menu';
      menu.className = 'osk-menu';
      menu.tabIndex = -1;
      menu.setAttribute('role', 'listbox');
      menu.setAttribute('aria-labelledby', spec.id + '-label');
      ORDER.forEach(function (value) {
        var item = document.createElement('div');
        item.className = 'osk-opt';
        item.tabIndex = -1;
        item.setAttribute('role', 'option');
        item.setAttribute('data-value', value);
        item.setAttribute('aria-selected', value === current ? 'true' : 'false');
        var name = document.createElement('span');
        name.className = 'osk-opt-name';
        name.textContent = label(value);
        item.appendChild(preview(value));
        item.appendChild(name);
        item.insertAdjacentHTML('beforeend', CHECK);
        item.addEventListener('click', function () { pick(value); });
        menu.appendChild(item);
        if (value === current) selected = item;
      });
      menu.addEventListener('mousedown', function (evt) { evt.stopPropagation(); });
      (trigger.closest('.modal') || document.body).appendChild(menu);
      trigger.setAttribute('aria-expanded', 'true');
      placeMenu();
      window.addEventListener('keydown', onMenuKey, true);
      document.addEventListener('pointerdown', onOutside, true);
      window.addEventListener('resize', onResize);
      window.addEventListener('scroll', placeMenu, true);
      (selected || menu).focus();
    }

    function ensureRow() {
      if (document.getElementById(spec.id)) return;
      var at = spec.place();
      if (!at) return;

      var block = document.createElement('div');
      block.id = spec.id;
      var line = document.createElement('div');
      line.className = at.rowClass || 'flex items-center justify-between gap-2.5';
      var name = document.createElement('div');
      name.id = spec.id + '-label';
      name.className = at.nameClass || 'min-w-0 text-xs text-gray-600 dark:text-gray-400';
      name.textContent = spec.title;
      closeMenu(false);
      trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'osk-trigger text-xs text-gray-500 transition-colors hover:text-gray-900 dark:text-gray-500 dark:hover:text-white';
      trigger.setAttribute('aria-labelledby', spec.id + '-label ' + spec.id + '-mode');
      trigger.setAttribute('aria-haspopup', 'listbox');
      trigger.setAttribute('aria-expanded', 'false');
      trigger.setAttribute('aria-controls', spec.id + '-menu');
      trigger.addEventListener('click', function () {
        if (menu) closeMenu(false);
        else openMenu();
      });
      trigger.addEventListener('keydown', function (evt) {
        if (menu || (evt.key !== 'ArrowDown' && evt.key !== 'ArrowUp')) return;
        evt.preventDefault();
        openMenu();
      });
      renderTrigger();
      line.appendChild(name);
      line.appendChild(trigger);
      var note = document.createElement('p');
      note.className = 'mt-1.5 text-[0.6875rem] text-gray-400 dark:text-gray-600';
      note.textContent = spec.note;
      if (spec.heading) {
        var head = document.createElement('div');
        head.className = 'osk-heading';
        head.textContent = spec.heading;
        block.appendChild(head);
      }
      block.appendChild(line);
      block.appendChild(note);
      at.parent.insertBefore(block, at.before);
    }

    function check() {
      if (menu && !(menu.isConnected && trigger && trigger.isConnected)) closeMenu(false);
    }

    window.addEventListener('storage', function (evt) {
      if (evt.key !== spec.key) return;
      apply();
      closeMenu(false);
      renderTrigger();
    });

    self.apply = apply;
    self.reroll = function () { if (spec.roll && effective() === 'random') roll(); };
    self.closeMenu = closeMenu;
    self.ensureRow = ensureRow;
    self.check = check;
    return self;
  }

  var message = makePicker({
    id: 'osk-setting',
    key: 'owui-message-loading-indicator',
    attr: 'data-osk',
    roll: true,
    names: CFG.names,
    fallback: CFG.fallback,
    defaultPreview: 'cursor',
    title: t('Message Loading Indicator'),
    note: t('How a reply shows that it is still loading. Saved in this browser.'),
    place: function () {
      var anchor = document.getElementById('chat-bubble-ui-label');
      if (!anchor || !anchor.closest('#tab-interface')) return null;
      var row = anchor.parentElement;
      var wrapper = row && row.parentElement;
      if (!wrapper || !wrapper.parentElement) return null;
      return {
        parent: wrapper.parentElement,
        before: wrapper.nextSibling,
        rowClass: row.className,
        nameClass: anchor.className
      };
    }
  });

  var think = makePicker({
    id: 'osk-think-setting',
    key: 'owui-thinking-indicator',
    attr: 'data-osk-think',
    roll: true,
    names: CFG.thinkNames,
    fallback: CFG.thinkFallback,
    defaultPreview: 'spinner',
    title: t('Thinking Indicator'),
    note: t('The icon beside the Thinking header while a model reasons. Saved in this browser.'),
    place: function () {
      var prev = document.getElementById('osk-setting');
      if (!prev || !prev.parentElement) return null;
      var label = document.getElementById('osk-setting-label');
      return {
        parent: prev.parentElement,
        before: prev.nextSibling,
        rowClass: prev.firstElementChild ? prev.firstElementChild.className : '',
        nameClass: label ? label.className : ''
      };
    }
  });

  // Thinking Indicator Size: scales the icon beside the Thinking header (0.5x - 3x).
  // Drives the --osk-think-size CSS variable (applied with `zoom`, so layout follows).
  var thinkSize = (function () {
    var id = 'osk-think-size';
    var KEY = 'owui-thinking-indicator-size';
    var MIN = 0.5;
    var MAX = 3;
    function fallback() {
      var v = parseFloat(CFG.thinkSize);
      return v >= MIN && v <= MAX ? v : 1;
    }
    function stored() {
      try {
        var v = parseFloat(localStorage.getItem(KEY));
        if (v >= MIN && v <= MAX) return v;
      } catch (e) {}
      return fallback();
    }
    function hasStored() { try { return localStorage.getItem(KEY) !== null; } catch (e) { return false; } }
    function fmt(v) { return v.toFixed(1) + '\u00d7'; }
    function apply() {
      var v = stored();
      if (v === 1) ROOT.style.removeProperty('--osk-think-size');
      else ROOT.style.setProperty('--osk-think-size', String(v));
    }
    function ensureRow() {
      if (document.getElementById(id)) return;
      var prev = document.getElementById('osk-think-setting');
      if (!prev || !prev.parentElement) return;
      var label = document.getElementById('osk-think-setting-label');
      var block = document.createElement('div');
      block.id = id;
      var line = document.createElement('div');
      line.className = (prev.firstElementChild && prev.firstElementChild.className) || 'flex items-center justify-between gap-2.5';
      var name = document.createElement('div');
      name.id = id + '-label';
      name.className = (label && label.className) || 'min-w-0 text-xs text-gray-600 dark:text-gray-400';
      name.textContent = t('Thinking Indicator Size');
      var right = document.createElement('div');
      right.className = 'osk-range-row';
      var input = document.createElement('input');
      input.type = 'range';
      input.className = 'osk-range';
      input.min = String(MIN);
      input.max = String(MAX);
      input.step = '0.1';
      input.value = String(stored());
      input.setAttribute('aria-labelledby', id + '-label');
      var val = document.createElement('span');
      val.className = 'osk-range-v';
      val.textContent = fmt(stored());
      var reset = document.createElement('button');
      reset.type = 'button';
      reset.className = 'osk-range-r';
      reset.textContent = t('Reset');
      reset.hidden = !hasStored();
      input.addEventListener('input', function () {
        var v = parseFloat(input.value);
        try { localStorage.setItem(KEY, String(v)); } catch (e) {}
        val.textContent = fmt(v);
        reset.hidden = false;
        apply();
      });
      reset.addEventListener('click', function () {
        try { localStorage.removeItem(KEY); } catch (e) {}
        input.value = String(stored());
        val.textContent = fmt(stored());
        reset.hidden = true;
        apply();
      });
      right.appendChild(input);
      right.appendChild(val);
      right.appendChild(reset);
      line.appendChild(name);
      line.appendChild(right);
      var note = document.createElement('p');
      note.className = 'mt-1.5 text-[0.6875rem] text-gray-400 dark:text-gray-600';
      note.textContent = t('Scale the icon beside the Thinking header. Drag right for larger, left for smaller. Saved in this browser.');
      block.appendChild(line);
      block.appendChild(note);
      prev.parentElement.insertBefore(block, prev.nextSibling);
    }
    window.addEventListener('storage', function (evt) { if (evt.key === KEY) apply(); });
    return { check: function () {}, ensureRow: ensureRow, apply: apply };
  })();

  // Message Indicator Size: scales the loading indicator in a reply (0.5x - 3x).
  // Drives the --osk-msg-size CSS variable (applied with `zoom`, so layout follows).
  var msgSize = (function () {
    var id = 'osk-msg-size';
    var KEY = 'owui-message-indicator-size';
    var MIN = 0.5;
    var MAX = 3;
    function fallback() {
      var v = parseFloat(CFG.msgSize);
      return v >= MIN && v <= MAX ? v : 1;
    }
    function stored() {
      try {
        var v = parseFloat(localStorage.getItem(KEY));
        if (v >= MIN && v <= MAX) return v;
      } catch (e) {}
      return fallback();
    }
    function hasStored() { try { return localStorage.getItem(KEY) !== null; } catch (e) { return false; } }
    function fmt(v) { return v.toFixed(1) + '\u00d7'; }
    function apply() {
      var v = stored();
      if (v === 1) ROOT.style.removeProperty('--osk-msg-size');
      else ROOT.style.setProperty('--osk-msg-size', String(v));
    }
    function ensureRow() {
      if (document.getElementById(id)) return;
      var prev = document.getElementById('osk-setting');
      if (!prev || !prev.parentElement) return;
      var label = document.getElementById('osk-setting-label');
      var block = document.createElement('div');
      block.id = id;
      var line = document.createElement('div');
      line.className = (prev.firstElementChild && prev.firstElementChild.className) || 'flex items-center justify-between gap-2.5';
      var name = document.createElement('div');
      name.id = id + '-label';
      name.className = (label && label.className) || 'min-w-0 text-xs text-gray-600 dark:text-gray-400';
      name.textContent = t('Message Indicator Size');
      var right = document.createElement('div');
      right.className = 'osk-range-row';
      var input = document.createElement('input');
      input.type = 'range';
      input.className = 'osk-range';
      input.min = String(MIN);
      input.max = String(MAX);
      input.step = '0.1';
      input.value = String(stored());
      input.setAttribute('aria-labelledby', id + '-label');
      var val = document.createElement('span');
      val.className = 'osk-range-v';
      val.textContent = fmt(stored());
      var reset = document.createElement('button');
      reset.type = 'button';
      reset.className = 'osk-range-r';
      reset.textContent = t('Reset');
      reset.hidden = !hasStored();
      input.addEventListener('input', function () {
        var v = parseFloat(input.value);
        try { localStorage.setItem(KEY, String(v)); } catch (e) {}
        val.textContent = fmt(v);
        reset.hidden = false;
        apply();
      });
      reset.addEventListener('click', function () {
        try { localStorage.removeItem(KEY); } catch (e) {}
        input.value = String(stored());
        val.textContent = fmt(stored());
        reset.hidden = true;
        apply();
      });
      right.appendChild(input);
      right.appendChild(val);
      right.appendChild(reset);
      line.appendChild(name);
      line.appendChild(right);
      var note = document.createElement('p');
      note.className = 'mt-1.5 text-[0.6875rem] text-gray-400 dark:text-gray-600';
      note.textContent = t('Scale the loading indicator shown in a reply. Drag right for larger, left for smaller. Does not affect the full-width Legacy Bars and Shimmer Lines styles. Saved in this browser.');
      block.appendChild(line);
      block.appendChild(note);
      prev.parentElement.insertBefore(block, prev.nextSibling);
    }
    window.addEventListener('storage', function (evt) { if (evt.key === KEY) apply(); });
    return { check: function () {}, ensureRow: ensureRow, apply: apply };
  })();

  // =====================================================================
  // v2: Thinking Words. Swaps Open WebUI's "Thinking..." text for rotating
  // words. The original text node is MOVED (not copied) into a hidden wrapper,
  // so Svelte keeps updating it and everything is restored when thinking ends.
  // =====================================================================
  var TW = (function () {
    var T = CFG.tw;
    var pickers = [];
    var timer = null;
    var pvTimer = null;
    var KEY_MS = 'owui-thinking-words-interval';
    var LETTERS = { wave: 1, bounce: 1, cascade: 1 };
    var GL = '!<>-_/[]{}=+*^?#abcdefghijklmnopqrstuvwxyz0123456789';
    var PALETTE = [
      ['#d97757', '#ffb59a', '#b4532f'], ['#3b82f6', '#93c5fd', '#1d4ed8'],
      ['#8b5cf6', '#c4b5fd', '#6d28d9'], ['#10b981', '#6ee7b7', '#047857'],
      ['#ec4899', '#f9a8d4', '#be185d'], ['#f59e0b', '#fde68a', '#b45309'],
      ['#06b6d4', '#67e8f9', '#0e7490'], ['#34d399', '#60a5fa', '#a78bfa'],
      ['#f97316', '#ec4899', '#8b5cf6']
    ];
    // Two matchers: the valve pattern anchored at the start (primary, matches the
    // documented behaviour) plus an unanchored fallback so multi-word localized
    // labels like "en train de réfléchir…" or "aan het denken" still match on a
    // keyword anywhere (e.g. "réfléchir", "denken").
    var re, reAny;
    try { re = new RegExp('^\\s*(?:' + T.pattern + ')', 'i'); reAny = new RegExp('(?:^|[\\s\\u00a0\\u200b])(?:' + T.pattern + ')', 'i'); } catch (e) { re = /^\s*(?:thinking|reasoning)/i; reAny = re; }
    if (T.dots) ROOT.setAttribute('data-osk-tw-dots', '1');

    function storedMs() {
      try {
        var v = parseFloat(localStorage.getItem(KEY_MS));
        if (v >= 0.3 && v <= 30) return Math.round(v * 1000);
      } catch (e) {}
      return Math.round(T.interval * 1000);
    }
    var baseMs = storedMs();

    function rand(list) { return list[Math.floor(Math.random() * list.length)]; }
    function pack() {
      var p = ROOT.getAttribute('data-osk-tw');
      return !p || p === 'off' ? 'default' : p;
    }
    function sig() {
      // LANG included so a language switch re-renders mounted words live.
      return [pack(), ROOT.getAttribute('data-osk-tw-fx'), ROOT.getAttribute('data-osk-tw-font'),
        ROOT.getAttribute('data-osk-tw-color'), ROOT.getAttribute('data-osk-tw-rhythm'), baseMs, LANG].join('|');
    }
    function holdFor() {
      return ROOT.getAttribute('data-osk-tw-rhythm') === 'natural'
        ? Math.round(baseMs * (0.6 + Math.random() * 0.8)) : baseMs;
    }
    function pickFx(last) {
      var f = ROOT.getAttribute('data-osk-tw-fx') || 'shimmer';
      if (f !== 'random') return f;
      var n = rand(T.fxPool);
      return n === last ? rand(T.fxPool) : n;
    }
    function pickFont() {
      var f = ROOT.getAttribute('data-osk-tw-font') || 'theme';
      return f === 'random' ? rand(T.fontPool) : f;
    }

    function wordsFor(p) {
      // Resolve the language-appropriate pack source.
      var src = T.packs;
      if (LANG !== 'en' && T.packsI18n && T.packsI18n[LANG]) {
        src = T.packsI18n[LANG];
      }
      var list = [];
      if (p === 'mix') {
        Object.keys(src).forEach(function (k) { list = list.concat(src[k]); });
      } else if (p === 'custom') {
        list = T.custom.length ? T.custom : (src.claude || T.packs.claude);
      } else {
        list = src[p] || T.packs[p] || T.packs.claude;
      }
      return list.length ? list : ['Thinking'];
    }
    function shuffle(a) {
      for (var i = a.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var t = a[i]; a[i] = a[j]; a[j] = t;
      }
      return a;
    }
    function next(st, list) {
      if (T.order === 'sequential') {
        st.i = (st.i + 1) % list.length;
        return list[st.i];
      }
      if (!st.deck.length || st.deckPack !== st.pack) {
        st.deck = shuffle(list.slice());
        st.deckPack = st.pack;
      }
      var w = st.deck.pop();
      if (w === st.last && st.deck.length) { var alt = st.deck.pop(); st.deck.unshift(w); w = alt; }
      st.last = w;
      return w;
    }

    // Decode effect: random glyphs resolve into the word. Uses a text node's
    // nodeValue so the page's MutationObserver is not woken on every frame.
    function scramble(node, text) {
      var tn = document.createTextNode('');
      node.textContent = '';
      node.appendChild(tn);
      var chars = Array.from(text);
      var n = chars.length;
      var total = 12 + n;
      var f = 0;
      var id = setInterval(function () {
        f++;
        if (f >= total || !tn.parentNode) { tn.nodeValue = text; clearInterval(id); return; }
        var reveal = Math.floor((f / total) * n * 1.2);
        var out = '';
        for (var i = 0; i < n; i++) out += (i < reveal || chars[i] === ' ') ? chars[i] : GL.charAt(Math.floor(Math.random() * GL.length));
        tn.nodeValue = out;
      }, 45);
    }

    // Per-letter color along a 3-stop gradient (t = 0..1). Letter effects animate
    // each letter with transforms, which breaks background-clip:text on the parent.
    function lc(t) {
      if (t <= 0.5) return 'color-mix(in oklab,var(--tw-a) ' + Math.round((1 - t * 2) * 100) + '%,var(--tw-b))';
      return 'color-mix(in oklab,var(--tw-b) ' + Math.round((1 - (t - 0.5) * 2) * 100) + '%,var(--tw-c))';
    }

    function build(node, text, fx) {
      node.setAttribute('data-text', text);
      node.style.setProperty('--n', String(Math.max(1, text.length)));
      if (LETTERS[fx]) {
        node.textContent = '';
        var chars = Array.from(text);
        var gl = node.getAttribute('data-grad') === 'l';
        for (var i = 0; i < chars.length; i++) {
          var l = document.createElement('span');
          l.className = 'osk-l';
          l.style.setProperty('--i', String(i));
          if (gl) {
            var lcol = lc(chars.length > 1 ? i / (chars.length - 1) : 0);
            l.style.color = lcol;
            l.style.setProperty('-webkit-text-fill-color', lcol);
          }
          l.textContent = chars[i] === ' ' ? '\u00a0' : chars[i];
          node.appendChild(l);
        }
      } else if (fx === 'scramble') {
        scramble(node, text);
      } else {
        node.textContent = text;
      }
    }

    function render(el) {
      var st = el._tw;
      st.pack = pack();
      var fx = pickFx(st.fx);
      st.fx = fx;
      var w = document.createElement('span');
      w.className = 'osk-tw-w';
      w.setAttribute('aria-hidden', 'true');
      w.setAttribute('dir', 'auto');
      w.setAttribute('data-fx', fx);
      w.setAttribute('data-font', pickFont());
      st.hold = holdFor();
      w.style.setProperty('--osk-tw-dur', st.hold + 'ms');
      if (T.gradients.indexOf(ROOT.getAttribute('data-osk-tw-color')) > -1 && fx !== 'neon' && fx !== 'glow') {
        w.setAttribute('data-grad', LETTERS[fx] ? 'l' : '1');
      }
      build(w, next(st, wordsFor(st.pack)), fx);
      if (ROOT.getAttribute('data-osk-tw-color') === 'random') {
        var c = rand(PALETTE);
        w.style.setProperty('--tw-a', c[0]);
        w.style.setProperty('--tw-b', c[1]);
        w.style.setProperty('--tw-c', c[2]);
      }
      el.setAttribute('data-clip', fx === 'slide' ? '1' : '');
      if (st.w && st.w.parentNode === el) el.replaceChild(w, st.w);
      else el.insertBefore(w, st.dots);
      st.w = w;
      st.sig = sig();
      st.at = Date.now();
    }

    function findLabel(svg) {
      // Language-agnostic by design: the thinking label is the text rendered
      // beside the spinner inside the header. We locate that text node
      // STRUCTURALLY and replace whatever it says, so Open WebUI changing its
      // translation ("en train de réfléchir…", "aan het denken", …) or the UI
      // being in a language we never listed cannot break the replacement.
      var header = svg.closest('button[aria-expanded]') || svg.closest('.shimmer') || svg.parentElement;
      if (!header) { console.log('[osk-diag] findLabel: NO header container for spinner svg'); return null; }
      // The label sits on the same "row" as the spinner: the direct child of the
      // header that contains the spinner also contains the label text. This is
      // what makes the pick translation-proof (works for any language).
      function rowOf(el) {
        var prev = el, cur = el;
        while (cur && cur !== header) { prev = cur; cur = cur.parentElement; }
        return cur === header ? prev : null;
      }
      var spinnerRow = rowOf(svg);
      var walker = document.createTreeWalker(header, NodeFilter.SHOW_TEXT, null);
      var node;
      var firstText = null;   // first eligible text node (last-resort pick)
      var adjacent = null;    // text node on the spinner's row
      var exact = null;       // text node the valve regex confirms (bonus signal)
      while ((node = walker.nextNode())) {
        var p = node.parentElement;
        if (!p || p.closest('svg, .osk-th, .osk-tw, .osk-orig')) continue;
        var txt = (node.nodeValue || '').trim();
        if (!txt) continue;
        if (!firstText) firstText = node;
        var row = rowOf(p);
        if (!adjacent && row && row === spinnerRow) adjacent = node;
        if (!exact && (re.test(txt) || reAny.test(txt))) exact = node;
      }
      // Priority: regex-confirmed > structurally adjacent to spinner > first text.
      var picked = exact || adjacent || firstText;
      console.log('[osk-diag] findLabel: container=' + header.tagName + ' exact=' + (exact ? JSON.stringify((exact.nodeValue || '').trim()) : 'no') + ' adjacent=' + (adjacent ? JSON.stringify((adjacent.nodeValue || '').trim()) : 'no') + ' first=' + (firstText ? JSON.stringify((firstText.nodeValue || '').trim()) : 'no') + ' -> picked=' + (picked ? JSON.stringify((picked.nodeValue || '').trim()) : 'none'));
      return picked;
    }

    function mount(svg, node) {
      var orig = document.createElement('span');
      orig.className = 'osk-orig';
      node.parentNode.insertBefore(orig, node);
      orig.appendChild(node);
      var el = document.createElement('span');
      el.className = 'osk-tw';
      var sr = document.createElement('span');
      sr.className = 'osk-sr';
      sr.textContent = (node.nodeValue || '').trim();
      var dots = document.createElement('span');
      dots.className = 'osk-tw-d';
      dots.setAttribute('aria-hidden', 'true');
      dots.innerHTML = '<i></i><i></i><i></i>';
      var tm = document.createElement('span');
      tm.className = 'osk-tw-t';
      tm.setAttribute('aria-hidden', 'true');
      var tt = document.createTextNode('0s');
      tm.appendChild(tt);
      el.appendChild(sr);
      el.appendChild(dots);
      el.appendChild(tm);
      orig.parentNode.insertBefore(el, orig.nextSibling);
      var host = el.closest('.shimmer');
      if (host) host.classList.add('osk-nosh');
      el._tw = { i: -1, deck: [], deckPack: '', last: '', fx: '', start: Date.now(), dots: dots, w: null, tm: tt, tmv: '', sig: '', at: 0, hold: baseMs, pack: pack() };
      el._oskSvg = svg;
      el._oskNode = node;
      el._oskOrig = orig;
      el._oskHost = host;
      svg._oskTwEl = el;
      render(el);
    }

    function teardown(el) {
      var node = el._oskNode;
      var orig = el._oskOrig;
      if (orig && orig.parentNode) {
        if (node && node.parentNode === orig) orig.parentNode.insertBefore(node, orig);
        orig.remove();
      }
      if (el._oskHost) el._oskHost.classList.remove('osk-nosh');
      if (el._oskSvg) el._oskSvg._oskTwEl = null;
      el.remove();
    }

    function tick() {
      var els = document.querySelectorAll('.osk-tw');
      if (!els.length) { clearInterval(timer); timer = null; return; }
      var now = Date.now();
      var timerOn = ROOT.getAttribute('data-osk-tw-timer') === 'on';
      var s0 = sig();
      for (var i = 0; i < els.length; i++) {
        var st = els[i]._tw;
        if (!st) continue;
        if (now - st.at >= st.hold || st.sig !== s0) render(els[i]);
        if (timerOn) {
          var s = Math.floor((now - st.start) / 1000);
          var v = s < 60 ? s + 's' : Math.floor(s / 60) + 'm ' + ('0' + (s % 60)).slice(-2) + 's';
          if (v !== st.tmv) { st.tmv = v; st.tm.nodeValue = v; }
        }
      }
    }

    // Called from scan() with every Thinking spinner svg currently on the page.
    function sync(svgs) {
      var on = pack() !== 'default';
      if (on) {
        for (var i = 0; i < svgs.length; i++) {
          var svg = svgs[i];
          if (svg._oskTwEl && svg._oskTwEl.isConnected) continue;
          var sheet = svg.querySelector('style');
          if (!sheet || sheet.textContent.indexOf('spinner_') === -1) continue;
          var node = findLabel(svg);
          if (node) mount(svg, node); else console.log('[osk-diag] sync: thinking spinner found but no label text node -> nothing mounted');
        }
      }
      var els = document.querySelectorAll('.osk-tw');
      for (var j = 0; j < els.length; j++) {
        var el = els[j];
        if (!on || !el._oskSvg || !el._oskSvg.isConnected) teardown(el);
      }
      var origs = document.querySelectorAll('.osk-orig');
      for (var k = 0; k < origs.length; k++) if (!origs[k].firstChild) origs[k].remove();
      if (!timer && document.querySelector('.osk-tw')) timer = setInterval(tick, 200);
    }

    // ---- settings rows -------------------------------------------------
    function after(prevId) {
      return function () {
        var prev = document.getElementById(prevId);
        var label = document.getElementById(prevId + '-label');
        if (!prev || !prev.parentElement || !label) return null;
        return { parent: prev.parentElement, before: prev.nextSibling, rowClass: label.parentElement.className, nameClass: label.className };
      };
    }

    // Dropdown previews replay every 2.6s so each effect shows its real motion.
    function restart(s) {
      build(s, s.getAttribute('data-text') || 'Thinking', s.getAttribute('data-fx'));
      s.style.animation = 'none';
      void s.offsetWidth;
      s.style.animation = '';
    }
    function pvLoop() {
      if (pvTimer) return;
      pvTimer = setInterval(function () {
        var list = document.querySelectorAll('.osk-pv-s[data-fx]');
        if (!list.length) { clearInterval(pvTimer); pvTimer = null; return; }
        for (var i = 0; i < list.length; i++) restart(list[i]);
      }, 2600);
    }
    function pv(text, attrs, fx) {
      var el = document.createElement('span');
      el.className = 'osk-pv osk-pv-t';
      el.setAttribute('aria-hidden', 'true');
      var s = document.createElement('span');
      s.className = 'osk-pv-s';
      for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) s.setAttribute(k, attrs[k]);
      if (fx) { build(s, text, fx); pvLoop(); } else s.textContent = text;
      el.appendChild(s);
      return el;
    }
    var DICE = '\uD83C\uDFB2';
    function add(id, key, attr, names, fallback, title, note, preview, heading, prev) {
      var p = makePicker({
        id: id, key: key, attr: attr, names: names, fallback: fallback, defaultPreview: null,
        title: title, note: note, preview: preview, heading: heading, place: after(prev)
      });
      pickers.push(p);
      return p;
    }

    // Language first: it controls the words + labels of every row below, so it
    // sits at the top of the Interface block (right after the size sliders).
    add('osk-language', 'owui-language', 'data-osk-language', NAMES_LANGUAGE, CFG.language,
      t('Language'), t('Choose the language for the thinking words and these settings. Saved in this browser.'),
      function (shown) {
        var l = shown === 'auto' ? LANG : shown;
        var deck = (CFG.tw && CFG.tw.packsI18n && CFG.tw.packsI18n[l]) || {};
        return pv((deck.minimal && deck.minimal[0]) || 'Thinking', {});
      }, null, 'osk-think-size');
    add('osk-tw-words', 'owui-thinking-words', 'data-osk-tw', NAMES_TW_PACK, T.fallbacks.pack,
      t('Thinking Words'), t('Rotating words shown instead of the plain \u201cThinking\u2026\u201d label while a model reasons. Saved in this browser.'),
      function (shown) { return pv(T.glyphs[shown] || 'Aa', {}); }, t('Thinking label'), 'osk-language');
    add('osk-tw-fx', 'owui-thinking-words-fx', 'data-osk-tw-fx', NAMES_TW_FX, T.fallbacks.fx,
      t('Phrase Effect'), t('How each phrase animates in. Random picks a different effect every time the phrase changes.'),
      function (shown) { return shown === 'random' ? pv(DICE, {}) : pv('Thinking', { 'data-fx': shown }, shown); }, null, 'osk-tw-words');
    add('osk-tw-font', 'owui-thinking-words-font', 'data-osk-tw-font', NAMES_TW_FONT, T.fallbacks.font,
      t('Phrase Font'), t('Typeface for the thinking phrases (fonts already on your device).'),
      function (shown) { return shown === 'random' ? pv(DICE, {}) : pv('Aa', { 'data-font': shown }); }, null, 'osk-tw-fx');
    add('osk-tw-color', 'owui-thinking-words-color', 'data-osk-tw-color', NAMES_TW_COLOR, T.fallbacks.color,
      t('Phrase Color'), t('Color or gradient of the thinking phrases.'),
      function (shown) { return pv('Abc', { 'data-color': shown }); }, null, 'osk-tw-font');

    // Slider: how long each word stays (0.4s - 10s).
    var slider = (function () {
      var id = 'osk-tw-interval';
      function fmt(ms) { return (ms / 1000).toFixed(1) + 's'; }
      function hasStored() { try { return localStorage.getItem(KEY_MS) !== null; } catch (e) { return false; } }
      function ensureRow() {
        if (document.getElementById(id)) return;
        var at = after('osk-tw-custom')();
        if (!at) return;
        var block = document.createElement('div');
        block.id = id;
        var line = document.createElement('div');
        line.className = at.rowClass || 'flex items-center justify-between gap-2.5';
        var name = document.createElement('div');
        name.id = id + '-label';
        name.className = at.nameClass || 'min-w-0 text-xs text-gray-600 dark:text-gray-400';
        name.textContent = t('Change Interval');
        var right = document.createElement('div');
        right.className = 'osk-range-row';
        var input = document.createElement('input');
        input.type = 'range';
        input.className = 'osk-range';
        input.min = '0.4';
        input.max = '10';
        input.step = '0.1';
        input.value = String(baseMs / 1000);
        input.setAttribute('aria-labelledby', id + '-label');
        var val = document.createElement('span');
        val.className = 'osk-range-v';
        val.textContent = fmt(baseMs);
        var reset = document.createElement('button');
        reset.type = 'button';
        reset.className = 'osk-range-r';
        reset.textContent = t('Reset');
        reset.hidden = !hasStored();
        input.addEventListener('input', function () {
          var v = parseFloat(input.value);
          baseMs = Math.round(v * 1000);
          try { localStorage.setItem(KEY_MS, String(v)); } catch (e) {}
          val.textContent = fmt(baseMs);
          reset.hidden = false;
        });
        reset.addEventListener('click', function () {
          try { localStorage.removeItem(KEY_MS); } catch (e) {}
          baseMs = storedMs();
          input.value = String(baseMs / 1000);
          val.textContent = fmt(baseMs);
          reset.hidden = true;
        });
        right.appendChild(input);
        right.appendChild(val);
        right.appendChild(reset);
        line.appendChild(name);
        line.appendChild(right);
        var note = document.createElement('p');
        note.className = 'mt-1.5 text-[0.6875rem] text-gray-400 dark:text-gray-600';
        note.textContent = t('How long each thinking phrase stays on screen. Drag left for faster, right for slower.');
        block.appendChild(line);
        block.appendChild(note);
        at.parent.insertBefore(block, at.before);
      }
      window.addEventListener('storage', function (evt) { if (evt.key === KEY_MS) baseMs = storedMs(); });
      return { check: function () {}, ensureRow: ensureRow, apply: function () { baseMs = storedMs(); } };
    })();
    // Custom color picker: any color. Used when Phrase Color is set to Custom.
    var KEY_CC = 'owui-thinking-words-custom-color';
    function customHex() {
      try {
        var v = localStorage.getItem(KEY_CC);
        if (v && /^#[0-9a-f]{6}$/i.test(v)) return v;
      } catch (e) {}
      return '#d97757';
    }
    function shade(hex, shadeAmt) {
      var n = parseInt(hex.slice(1), 16);
      var ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(function (v) {
        var tgt = shadeAmt > 0 ? 255 : 0;
        return Math.round(v + (tgt - v) * Math.abs(shadeAmt));
      });
      return '#' + ch.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join('');
    }
    function applyCustom() {
      var hex = customHex();
      ROOT.style.setProperty('--osk-tw-custom-a', hex);
      ROOT.style.setProperty('--osk-tw-custom-b', shade(hex, 0.45));
      ROOT.style.setProperty('--osk-tw-custom-c', shade(hex, -0.3));
    }
    applyCustom();
    var customRow = (function () {
      var id = 'osk-tw-custom';
      function ensureRow() {
        if (document.getElementById(id)) return;
        var at = after('osk-tw-color')();
        if (!at) return;
        var block = document.createElement('div');
        block.id = id;
        var line = document.createElement('div');
        line.className = at.rowClass || 'flex items-center justify-between gap-2.5';
        var name = document.createElement('div');
        name.id = id + '-label';
        name.className = at.nameClass || 'min-w-0 text-xs text-gray-600 dark:text-gray-400';
        name.textContent = t('Custom Color');
        var right = document.createElement('div');
        right.className = 'osk-range-row';
        var input = document.createElement('input');
        input.type = 'color';
        input.className = 'osk-colorin';
        input.value = customHex();
        input.setAttribute('aria-labelledby', id + '-label');
        var val = document.createElement('span');
        val.className = 'osk-range-v';
        val.textContent = input.value;
        input.addEventListener('input', function () {
          try { localStorage.setItem(KEY_CC, input.value); } catch (e) {}
          val.textContent = input.value;
          applyCustom();
        });
        right.appendChild(input);
        right.appendChild(val);
        line.appendChild(name);
        line.appendChild(right);
        var note = document.createElement('p');
        note.className = 'mt-1.5 text-[0.6875rem] text-gray-400 dark:text-gray-600';
        note.textContent = t('Pick any color, then choose \u201cCustom\u201d in Phrase Color above to use it.');
        block.appendChild(line);
        block.appendChild(note);
        at.parent.insertBefore(block, at.before);
      }
      window.addEventListener('storage', function (evt) { if (evt.key === KEY_CC) applyCustom(); });
      return { check: function () {}, ensureRow: ensureRow, apply: applyCustom };
    })();
    pickers.push(customRow);
    pickers.push(slider);

    add('osk-tw-rhythm', 'owui-thinking-words-rhythm', 'data-osk-tw-rhythm', NAMES_TW_RHYTHM, T.fallbacks.rhythm,
      t('Change Rhythm'), t('Steady changes at exactly the interval; Natural varies each phrase by up to 40%.'),
      function (shown) { return pv(shown === 'natural' ? '| || |' : '| | |', {}); }, null, 'osk-tw-interval');
    add('osk-tw-timer', 'owui-thinking-words-timer', 'data-osk-tw-timer', NAMES_TW_TIMER, T.fallbacks.timer,
      t('Thinking Timer'), t('Show a live seconds counter next to the words.'),
      function (shown) { return pv(shown === 'on' ? '0:07' : '\u2014', {}); }, null, 'osk-tw-rhythm');

    // Console helper: window.__owuiThinkingWords.dump() prints the Thinking header HTML.
    window.__owuiThinkingWords = {
      dump: function () {
        var out = [];
        var svgs = document.querySelectorAll('button[aria-expanded] svg, .shimmer svg');
        for (var i = 0; i < svgs.length; i++) {
          var st = svgs[i].querySelector('style');
          if (!st || st.textContent.indexOf('spinner_') === -1) continue;
          var h = svgs[i].closest('button[aria-expanded]') || svgs[i].parentElement;
          out.push(h.outerHTML.replace(/<style>[\s\S]*?<\/style>/g, '<style>\u2026</style>'));
        }
        console.log(out.join('\n\n') || 'No Thinking header with a spinner on screen right now.');
        return out;
      }
    };

    return {
      pickers: pickers,
      scan: sync,
      // Force mounted thinking words to re-render now (used when LANG changes
      // live: the sig() already includes LANG, this makes the chat follow at once).
      refresh: function () {
        var els = document.querySelectorAll('.osk-tw');
        for (var i = 0; i < els.length; i++) if (els[i]._tw) render(els[i]);
      },
      apply: function () { pickers.forEach(function (p) { p.apply(); }); }
    };
  })();

  function ensureStyle() {
    if (document.getElementById('owui-osk-style')) return;
    var style = document.createElement('style');
    style.id = 'owui-osk-style';
    style.textContent = CSS;
    (document.head || ROOT).appendChild(style);
  }

  function decorate(host, kind) {
    if (host.classList.contains('osk-host')) return;
    host.classList.add('osk-host');
    message.reroll();
    host.setAttribute('data-osk-kind', kind);
    var wrap = document.createElement('span');
    wrap.className = 'osk';
    wrap.setAttribute('aria-hidden', 'true');
    wrap.innerHTML = MARKUP;
    host.appendChild(wrap);
  }

  // Open WebUI's Thinking header shows a spinner svg (a <style> block defining
  // .spinner_xxxx keyframes). Add our own element beside it; CSS swaps them.
  function decorateThink(svg) {
    var host = svg.parentElement;
    if (!host || svg.hasAttribute('data-osk-n')) return;
    svg.setAttribute('data-osk-n', '1');
    think.reroll();
    var el = document.createElement('span');
    el.className = 'osk-th';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = MARKUP;
    el._oskSvg = svg;
    host.insertBefore(el, svg.nextSibling);
  }

  function inReply(node) {
    if (node.closest('#response-content-container')) return true;
    for (var el = node.parentElement; el; el = el.parentElement) {
      var first = el.firstElementChild;
      if (first && /^responses-container-/.test(first.id || '')) return true;
    }
    return false;
  }

  function scan() {
    scheduled = false;
    // 0.12.x renamed the cursor animation to animate-cursor-pulse; older builds use animate-pulse.
    var cursors = document.querySelectorAll('span.inline-block.align-text-bottom.animate-cursor-pulse, #response-content-container span.inline-block.animate-pulse.align-text-bottom');
    for (var i = 0; i < cursors.length; i++) if (inReply(cursors[i])) decorate(cursors[i], 'cursor');
    var dots = document.querySelectorAll('span.animate-size');
    for (var j = 0; j < dots.length; j++) {
      var outer = dots[j].parentElement;
      if (outer && outer.tagName === 'SPAN' && outer.classList.contains('relative') && inReply(outer)) decorate(outer, 'dot');
    }
    var spinners = document.querySelectorAll('.shimmer svg, button[aria-expanded] svg');
    for (var k = 0; k < spinners.length; k++) {
      var sheet = spinners[k].querySelector('style');
      if (sheet && sheet.textContent.indexOf('spinner_') !== -1) decorateThink(spinners[k]);
    }
    TW.scan(spinners);
    // The spinner is removed when thinking ends; drop the element we added beside it.
    var added = document.querySelectorAll('.osk-th');
    for (var m = 0; m < added.length; m++) {
      if (!added[m]._oskSvg || !added[m]._oskSvg.isConnected) added[m].remove();
    }
    message.check();
    think.check();
    thinkSize.check();
    msgSize.check();
    TW.pickers.forEach(function (p) { p.check(); });
    message.ensureRow();
    think.ensureRow();
    thinkSize.ensureRow();
    msgSize.ensureRow();
    TW.pickers.forEach(function (p) { p.ensureRow(); });
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(scan);
  }

  ensureStyle();
  message.apply();
  think.apply();
  thinkSize.apply();
  msgSize.apply();
  TW.apply();
  new MutationObserver(schedule).observe(ROOT, { childList: true, subtree: true });
  schedule();
})();
"""


class Event:
    class Valves(BaseModel):
        default_style: STYLE_LITERAL = Field(
            default="default",
            description="What Default means in the Message Loading Indicator setting for users who have not picked a style. 'default' keeps Open WebUI's own indicator and 'random' picks a different style for every message. Others: cursor, dot, bars (legacy loading bars), block (terminal block cursor), typing, wave (equalizer), spinner, shimmer (skeleton lines), ellipsis, scanner, orbit, ripple, breathe (breathing orb), grid (dot grid), flip (flipping square), sparkle, heartbeat, ball (bouncing ball).",
        )
        default_thinking_style: THINK_LITERAL = Field(
            default="default",
            description="What Default means in the Thinking Indicator setting, the icon beside the Thinking header while a model reasons. 'default' keeps Open WebUI's own spinner and 'none' hides the icon. The other values match the message styles of the same name.",
        )

        default_message_size: float = Field(
            default=1.0,
            ge=0.5,
            le=3.0,
            description="Default scale of the Message Loading Indicator (1.0 = normal size). Users can change it with the Message Indicator Size slider in Settings > Interface.",
        )
        default_thinking_size: float = Field(
            default=1.0,
            ge=0.5,
            le=3.0,
            description="Default scale of the Thinking icon (1.0 = normal size). Users can change it with the Thinking Indicator Size slider in Settings > Interface.",
        )
        default_thinking_words: TW_PACK_LITERAL = Field(
            default="claude",
            description="What Default means in the Thinking Words setting (the rotating words that replace the plain 'Thinking...' label). Packs: claude, dev, playful, science, hacker, zen, minimal, mix (everything), custom (uses custom_words below). 'off' keeps Open WebUI's original text.",
        )
        default_words_effect: TW_FX_LITERAL = Field(
            default="shimmer",
            description="Default animation for the thinking words: random (changes every phrase), shimmer, gradient, rainbow, neon, glow, fade, slide, typewriter, scramble, blur, wave, bounce, cascade, glitch, pop, flip, reveal, pulse, plain.",
        )
        default_words_font: TW_FONT_LITERAL = Field(
            default="theme",
            description="Default font for the thinking words: random, theme, mono, serif, italic, rounded, hand, caps, small.",
        )
        default_words_color: TW_COLOR_LITERAL = Field(
            default="orange",
            description="Default color for the thinking words: random (changes every phrase), theme, orange, blue, purple, green, pink, gold, cyan, red, tangerine, yellow, lime, teal, sky, indigo, violet, fuchsia, rose, brown, grey, silver, white, black, custom (uses each user's own color picker), or a gradient: aurora, sunset, ocean, fire, candy, forest, twilight, peach, citrus, berry, rosegold, cyberpunk.",
        )
        default_words_interval: float = Field(
            default=2.4,
            ge=0.4,
            le=15.0,
            description="Default seconds each thinking phrase stays on screen. Users can change it with the slider in Settings > Interface.",
        )
        default_words_rhythm: TW_RHYTHM_LITERAL = Field(
            default="steady",
            description="'steady' changes phrases at exactly the interval; 'natural' varies each one by up to 40%.",
        )
        default_words_timer: Literal["off", "on"] = Field(
            default="off",
            description="Default for the live seconds counter shown next to the thinking words.",
        )
        words_order: Literal["shuffle", "sequential"] = Field(
            default="shuffle",
            description="'shuffle' plays every word once in random order before repeating; 'sequential' plays them in list order.",
        )
        animated_dots: bool = Field(
            default=True,
            description="Show animated trailing dots after each thinking word.",
        )
        custom_words: str = Field(
            default="",
            description="Your own thinking words, one per line. Used by the 'Custom' pack (and falls back to Claude-style when empty).",
        )
        language: Literal["auto", "en", "fr", "es", "de", "it", "pt", "nl"] = Field(
            default="auto",
            description="Language for thinking words and UI labels. 'auto' follows the Open WebUI interface language (<html lang>); a user's explicit choice in Settings > Interface wins. Set explicitly to force a language.",
        )
        label_pattern: str = Field(
            default="thinking|reasoning|réflexion|réfléchir|en train|denken|aan het|nadenk|denkt|pensando|pensieri|riflessione|denk|redene|penser",
            description="Regex (case-insensitive) matching the start of Open WebUI's thinking label. Add your UI language here, e.g. 'thinking|reasoning|pensando|denkt'. Only labels that match are replaced.",
        )

    LOADER_BLOCK_START = "// owui-message-loading-indicator:start"
    LOADER_BLOCK_END = "// owui-message-loading-indicator:end"
    ASSET_KEY = "message-loading-indicator"
    ASSET_ORDER = 0

    _fragment_cache = None
    instance = None

    def __init__(self):
        self.valves = self.Valves()
        Event.instance = self
        reload_bootstrap()

    def _custom_words(self) -> list:
        lines = [ln.strip() for ln in (self.valves.custom_words or "").splitlines()]
        return [ln[:60] for ln in lines if ln][:200]

    def _loader_fragment(self) -> str:
        valves = self.valves
        dump = valves.model_dump() if hasattr(valves, "model_dump") else valves.dict()
        cache_key = _json.dumps(dump, sort_keys=True, default=str)
        cached = Event._fragment_cache
        if cached and cached[0] == cache_key:
            return cached[1]
        config = _json.dumps(
            {
                "fallback": valves.default_style,
                "thinkFallback": valves.default_thinking_style,
                "thinkSize": float(valves.default_thinking_size),
                "msgSize": float(valves.default_message_size),
                "names": STYLE_NAMES,
                "thinkNames": THINK_NAMES,
                "language": valves.language,
                "i18n": I18N_UI,
                "i18nPackNames": I18N_PACK_NAMES,
                "i18nFxNames": I18N_FX_NAMES,
                "i18nFontNames": I18N_FONT_NAMES,
                "i18nColorNames": I18N_COLOR_NAMES,
                "i18nRhythmNames": I18N_RHYTHM_NAMES,
                "i18nTimerNames": I18N_TIMER_NAMES,
                "tw": {
                    "packs": TW_PACKS,
                    "packsI18n": TW_PACKS_I18N,
                    "custom": self._custom_words(),
                    "order": valves.words_order,
                    "dots": bool(valves.animated_dots),
                    "pattern": valves.label_pattern or "thinking|reasoning",
                    "glyphs": TW_GLYPHS,
                    "gradients": list(TW_GRADIENTS),
                    "fxPool": TW_FX_POOL,
                    "fontPool": TW_FONT_POOL,
                    "interval": float(valves.default_words_interval),
                    "packNames": TW_PACK_NAMES,
                    "fxNames": TW_FX_NAMES,
                    "fontNames": TW_FONT_NAMES,
                    "colorNames": TW_COLOR_NAMES,
                    "rhythmNames": TW_RHYTHM_NAMES,
                    "timerNames": TW_TIMER_NAMES,
                    "fallbacks": {
                        "pack": valves.default_thinking_words,
                        "fx": valves.default_words_effect,
                        "font": valves.default_words_font,
                        "color": valves.default_words_color,
                        "rhythm": valves.default_words_rhythm,
                        "timer": valves.default_words_timer,
                    },
                },
            }
        )
        js = (
            LOADER_SCRIPT.strip()
            .replace("__CONFIG__", config)
            .replace("__CSS__", _json.dumps(OSK_CSS.strip()))
            .replace("__MORE_MARKUP__", _json.dumps(MORE_MARKUP))
        )
        fragment = f"{self.LOADER_BLOCK_START}\n{js}\n{self.LOADER_BLOCK_END}"
        Event._fragment_cache = (cache_key, fragment)
        return fragment

    def _publish(self, app) -> None:
        asset_register(
            app,
            LOADER_PATH,
            self.ASSET_KEY,
            self.LOADER_BLOCK_START,
            self.LOADER_BLOCK_END,
            lambda: Event.instance._loader_fragment() if reload_active(app) else "",
            order=self.ASSET_ORDER,
        )

    async def event(
        self,
        event: Optional[dict] = None,
        __event_name__: str = "",
        __app__: Any = None,
        **kwargs,
    ) -> None:
        if __app__ is not None:
            await reload_on_event(__app__, event, __event_name__)


def register(app: Any) -> None:
    Event.instance._publish(app)