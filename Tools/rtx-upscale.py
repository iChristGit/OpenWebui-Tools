"""
title: ComfyUI RTX Image Upscaler
description: >
  Upscale images using NVIDIA RTX Video Super Resolution via ComfyUI.
  Supports 1x, 2x, 3x, 4x scaling with ULTRA quality.
  The tool picks up the image automatically from the conversation history.
author: ichrist
version: 2.0.0
license: MIT
requirements: aiohttp
"""

import asyncio
import base64
import copy
import io
import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OWUI_INTERNAL_BASE = os.environ.get("OWUI_INTERNAL_BASE", "http://localhost:8080")


# ─── Workflow templates ───────────────────────────────────────────────────────
# NOTE: "resize_type.scale" is the literal key name used by the
# RTXVideoSuperResolution custom node — the dot is intentional and must NOT
# be changed to a nested dict.

WORKFLOW_WITH_UNLOAD: Dict[str, Any] = {
    "1": {
        "inputs": {
            "resize_type": "scale by multiplier",
            "resize_type.scale": 4,
            "quality": "ULTRA",
            "images": ["2", 0],
        },
        "class_type": "RTXVideoSuperResolution",
        "_meta": {"title": "RTX Video Super Resolution"},
    },
    "2": {
        "inputs": {"image": "PLACEHOLDER"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    },
    "3": {
        "inputs": {
            "filename_prefix": "upscaled",
            "images": ["7", 0],
        },
        "class_type": "SaveImage",
        "_meta": {"title": "Save Image"},
    },
    "7": {
        "inputs": {"value": ["1", 0]},
        "class_type": "UnloadAllModels",
        "_meta": {"title": "UnloadAllModels"},
    },
}

WORKFLOW_NO_UNLOAD: Dict[str, Any] = {
    "1": {
        "inputs": {
            "resize_type": "scale by multiplier",
            "resize_type.scale": 4,
            "quality": "ULTRA",
            "images": ["2", 0],
        },
        "class_type": "RTXVideoSuperResolution",
        "_meta": {"title": "RTX Video Super Resolution"},
    },
    "2": {
        "inputs": {"image": "PLACEHOLDER"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    },
    "3": {
        "inputs": {
            "filename_prefix": "upscaled",
            "images": ["1", 0],
        },
        "class_type": "SaveImage",
        "_meta": {"title": "Save Image"},
    },
}


# ─── Image resolution helpers ─────────────────────────────────────────────────


async def _bytes_from_url(url: str, owui_base: str) -> Optional[bytes]:
    """
    Fetch image bytes from any URL format OWUI uses:
      1. data:image/...;base64,<b64>  → decode inline
      2. /api/v1/files/{id}/content   → GET from OWUI internal base
      3. http(s)://...                → GET directly
    """
    if not url:
        return None

    # 1. Inline base64 data URI
    if url.startswith("data:"):
        try:
            payload = url.split(",", 1)[1]
            data = base64.b64decode(payload)
            logger.info("Decoded inline base64 image (%d bytes)", len(data))
            return data
        except Exception as exc:
            logger.warning("base64 decode failed: %s", exc)
            return None

    # 2. OWUI-relative path (internal file reference)
    if url.startswith("/"):
        full = owui_base.rstrip("/") + url
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(full) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        logger.info(
                            "Fetched OWUI-internal image %s (%d bytes)", url, len(data)
                        )
                        return data
                    logger.warning("OWUI internal fetch %s → HTTP %d", url, resp.status)
        except Exception as exc:
            logger.warning("OWUI internal fetch error for %s: %s", url, exc)
        return None

    # 3. Absolute HTTP(S) URL
    if url.startswith("http://") or url.startswith("https://"):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        logger.info("Fetched image from URL (%d bytes)", len(data))
                        return data
                    logger.warning("URL fetch → HTTP %d", resp.status)
        except Exception as exc:
            logger.warning("URL fetch error: %s", exc)
        return None

    logger.warning("Unrecognised image_url format: %.80s", url)
    return None


def _extract_image_urls_from_messages(messages: List[Dict[str, Any]]) -> List[str]:
    """
    Scan __messages__ for image_url content blocks, newest message first.
    OWUI multimodal structure:
      { "role": "user", "content": [
          { "type": "text",      "text": "..." },
          { "type": "image_url", "image_url": { "url": "..." } }
      ]}
    """
    found: List[str] = []
    for msg in reversed(messages):
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_url_obj = part.get("image_url") or {}
                    url = image_url_obj.get("url") or image_url_obj.get("src") or ""
                    if url:
                        found.append(url)
    return found


# ─── ComfyUI helpers ──────────────────────────────────────────────────────────


async def _upload_image_to_comfyui(
    http_url: str,
    image_bytes: bytes,
    filename: str,
) -> str:
    """Upload raw image bytes to ComfyUI /upload/image; return the stored filename."""
    form = aiohttp.FormData()
    form.add_field(
        "image",
        io.BytesIO(image_bytes),
        filename=filename,
        content_type="image/png",
    )
    form.add_field("type", "input")
    form.add_field("overwrite", "true")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{http_url.rstrip('/')}/upload/image", data=form
        ) as resp:
            resp.raise_for_status()
            stored = (await resp.json()).get("name", filename)
            logger.info("Image uploaded to ComfyUI as: %s", stored)
            return stored


async def _submit_and_wait(
    http_url: str,
    workflow: Dict[str, Any],
    client_id: str,
    max_wait: int,
) -> Dict[str, Any]:
    """
    Queue a ComfyUI workflow and wait for completion.
    Primary: WebSocket events  → fallback: HTTP polling.
    Handles both old ("executed"/"execution_cached") and newer
    ("execution_success") ComfyUI message types.
    """
    ws_base = http_url.replace("http://", "ws://").replace("https://", "wss://")
    start = asyncio.get_event_loop().time()
    prompt_id: Optional[str] = None

    async with aiohttp.ClientSession() as session:

        # ── Queue the prompt first (separate from WS, so we always have a
        #    prompt_id even if the WS connection fails immediately) ──────────
        async with session.post(
            f"{http_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"ComfyUI /prompt returned {resp.status}: {await resp.text()}"
                )
            rj = await resp.json()
            prompt_id = rj.get("prompt_id")
            if not prompt_id:
                raise RuntimeError("ComfyUI did not return a prompt_id")
            logger.info("Prompt queued — id: %s", prompt_id)

        # ── WebSocket listener ────────────────────────────────────────────────
        try:
            async with session.ws_connect(f"{ws_base}/ws?clientId={client_id}") as ws:
                last_poll = 0.0
                while True:
                    elapsed = asyncio.get_event_loop().time() - start
                    if elapsed > max_wait:
                        raise TimeoutError(f"Timed out after {max_wait}s")

                    # Periodic HTTP history poll as belt-and-suspenders
                    now = asyncio.get_event_loop().time()
                    if now - last_poll > 3.0:
                        last_poll = now
                        try:
                            async with session.get(
                                f"{http_url}/history/{prompt_id}"
                            ) as hr:
                                if hr.status == 200:
                                    h = await hr.json()
                                    if prompt_id in h:
                                        logger.info("Job complete (poll hit)")
                                        return h[prompt_id]
                        except Exception:
                            pass

                    # WS receive with short timeout so poll can still fire
                    try:
                        msg = await ws.receive(timeout=1.0)
                    except asyncio.TimeoutError:
                        continue

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            m = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue
                        t = m.get("type", "")
                        d = m.get("data", {})
                        pid = d.get("prompt_id", "")

                        if pid != prompt_id:
                            continue  # unrelated job

                        if t in ("execution_cached", "executed", "execution_success"):
                            # Fetch final result from history
                            async with session.get(
                                f"{http_url}/history/{prompt_id}"
                            ) as fr:
                                if fr.status == 200:
                                    h = await fr.json()
                                    if prompt_id in h:
                                        logger.info("Job complete (WS event: %s)", t)
                                        return h[prompt_id]

                        elif t == "execution_error":
                            raise RuntimeError(
                                f"ComfyUI error on node "
                                f"{d.get('node_id', '?')}: "
                                f"{d.get('exception_message', 'unknown error')}"
                            )

                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        logger.warning("WS closed/error — switching to pure polling")
                        break

        except (aiohttp.ClientError, OSError) as ws_exc:
            logger.warning("WS connect failed (%s) — polling only", ws_exc)

        # ── Pure HTTP polling fallback ─────────────────────────────────────────
        logger.info("Polling /history/%s …", prompt_id)
        while asyncio.get_event_loop().time() - start <= max_wait:
            await asyncio.sleep(2)
            try:
                async with session.get(f"{http_url}/history/{prompt_id}") as hr:
                    if hr.status == 200:
                        h = await hr.json()
                        if prompt_id in h:
                            logger.info("Job complete (polling)")
                            return h[prompt_id]
            except Exception:
                pass

        raise TimeoutError(f"Polling timed out after {max_wait}s")


def _extract_output_images(job: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return the list of SaveImage output entries from a ComfyUI history job."""
    images: List[Dict[str, str]] = []
    for node_output in job.get("outputs", {}).values():
        for img in node_output.get("images", []):
            if img.get("type") == "output":
                images.append(img)
    return images


# ─── OWUI image storage ───────────────────────────────────────────────────────


async def _fetch_from_comfyui(
    http_url: str, img_meta: Dict[str, str]
) -> Optional[bytes]:
    """Download the upscaled image bytes from ComfyUI /view."""
    params = {
        "filename": img_meta["filename"],
        "type": img_meta.get("type", "output"),
    }
    if img_meta.get("subfolder"):
        params["subfolder"] = img_meta["subfolder"]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{http_url.rstrip('/')}/view", params=params
            ) as resp:
                resp.raise_for_status()
                data = await resp.read()
                logger.info("Fetched upscaled image from ComfyUI (%d bytes)", len(data))
                return data
    except Exception as exc:
        logger.warning("Failed to fetch image from ComfyUI /view: %s", exc)
        return None


async def _upload_to_owui_rest(
    owui_base: str,
    image_bytes: bytes,
    filename: str,
    request: Any,
) -> Optional[str]:
    """
    Upload image bytes to OWUI's public file REST API (/api/v1/files/).
    Returns the content URL (/api/v1/files/{id}/content) on success, else None.

    Auth is forwarded from the original request's Authorization header, or the
    'token' cookie, whichever is present.  This avoids any dependency on
    internal OWUI Python APIs that may change between versions.
    """
    headers: Dict[str, str] = {"accept": "application/json"}

    if request is not None:
        # Try Authorization header first (Bearer token)
        auth = None
        try:
            auth = request.headers.get("Authorization") or request.headers.get(
                "authorization"
            )
        except Exception:
            pass
        if auth:
            headers["Authorization"] = auth
        else:
            # Fall back to cookie-based token
            try:
                token = request.cookies.get("token")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            except Exception:
                pass

    url = f"{owui_base.rstrip('/')}/api/v1/files/"
    form = aiohttp.FormData()
    form.add_field(
        "file",
        io.BytesIO(image_bytes),
        filename=filename,
        content_type="image/png",
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, headers=headers) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    file_id = data.get("id")
                    if file_id:
                        content_url = f"/api/v1/files/{file_id}/content"
                        logger.info("Image stored in OWUI files: %s", content_url)
                        return content_url
                    logger.warning(
                        "OWUI /api/v1/files/ response missing 'id': %s", data
                    )
                else:
                    body = await resp.text()
                    logger.warning(
                        "OWUI file upload failed — HTTP %d: %s",
                        resp.status,
                        body[:200],
                    )
    except Exception as exc:
        logger.warning("OWUI REST upload error: %s", exc)

    return None


def _to_data_uri(image_bytes: bytes) -> str:
    """Encode raw PNG bytes as a data: URI (fallback when OWUI upload fails)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def _resolve_display_url(
    http_url: str,
    img_meta: Dict[str, str],
    owui_base: str,
    request: Any,
    filename: str,
) -> str:
    """
    Build the best available display URL for the upscaled image:
      1. Try uploading to OWUI file store → /api/v1/files/{id}/content
      2. Fall back to inline base64 data URI (always works, larger payload)

    The ComfyUI /view URL is intentionally NOT used as the primary display URL
    because the browser may not have direct access to ComfyUI (e.g. Docker
    networking), and because the file disappears when ComfyUI is restarted.
    """
    image_bytes = await _fetch_from_comfyui(http_url, img_meta)
    if image_bytes is None:
        logger.error("Could not fetch image from ComfyUI; cannot display it.")
        return ""

    # Strategy 1: OWUI file store
    owui_url = await _upload_to_owui_rest(owui_base, image_bytes, filename, request)
    if owui_url:
        return owui_url

    # Strategy 2: base64 data URI
    logger.info("OWUI upload failed; using base64 data URI fallback")
    return _to_data_uri(image_bytes)


# ─── Main Tool class ──────────────────────────────────────────────────────────


class Tools:

    class Valves(BaseModel):
        comfyui_url: str = Field(
            default="http://localhost:8188",
            description="Base URL of your ComfyUI instance.",
        )
        owui_internal_base: str = Field(
            default="http://localhost:8080",
            description=(
                "Internal URL OWUI uses server-side to fetch/store files "
                "(e.g. http://localhost:8080). Must be reachable from the "
                "OWUI container/process."
            ),
        )
        unload_models_after_run: bool = Field(
            default=True,
            description=(
                "Run the UnloadAllModels node after upscaling to free VRAM. "
                "Disable to keep the RTX model loaded for faster back-to-back "
                "runs."
            ),
        )
        max_wait_seconds: int = Field(
            default=300,
            description="Maximum seconds to wait for ComfyUI to finish upscaling.",
        )

    class UserValves(BaseModel):
        default_scale: int = Field(
            default=4,
            description=(
                "Default upscale multiplier when the user doesn't specify one. "
                "Allowed values: 1, 2, 3, 4."
            ),
        )
        unload_models_after_run: bool = Field(
            default=True,
            description=(
                "Unload the RTX model from VRAM after each run to save memory. "
                "Disable to keep it loaded for faster consecutive upscales."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _should_unload(self, user_valves: Any) -> bool:
        if user_valves and hasattr(user_valves, "unload_models_after_run"):
            return user_valves.unload_models_after_run
        return self.valves.unload_models_after_run

    async def _emit_status(
        self,
        emitter: Optional[Callable],
        description: str,
        done: bool = False,
    ) -> None:
        if emitter:
            await emitter(
                {
                    "type": "status",
                    "data": {"description": description, "done": done},
                }
            )

    async def _emit_image(
        self,
        emitter: Optional[Callable],
        display_url: str,
        scale_label: str,
        vram_note: str,
    ) -> None:
        """
        Embed the upscaled image in chat using `type: "files"`.

        WHY "files" and NOT "message":
          The "message" event type appends markdown to the assistant message
          body.  In Native function-calling mode, Open WebUI replays successive
          "chat:completion" snapshots that overwrite the full message content,
          erasing anything injected via "message" events — causing the 1ms
          flash-then-disappear bug.

          The "files" / "chat:message:files" event type stores the image as a
          file attachment on the message object.  This is handled by a separate
          code path in the OWUI frontend that is NOT overwritten by completion
          snapshots, so the image persists reliably in both Default and Native
          function-calling modes.
        """
        if not emitter or not display_url:
            return

        await emitter(
            {
                "type": "files",
                "data": {
                    "files": [
                        {
                            "type": "image",
                            "url": display_url,
                            "name": f"upscaled_{scale_label.replace('×', 'x')}_ULTRA.png",
                            "collection_name": "",
                        }
                    ]
                },
            }
        )

    # ── Tool method ───────────────────────────────────────────────────────────

    async def upscale_image(
        self,
        image_url: str,
        scale: int = 4,
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        __user__: Optional[Dict[str, Any]] = None,
        __messages__: Optional[List[Dict[str, Any]]] = None,
        __request__: Optional[Any] = None,
    ) -> str:
        """
        Upscale the image from the conversation using NVIDIA RTX Video Super
        Resolution in ComfyUI.

        Call this when the user asks to upscale, enhance resolution, increase
        image size, or make a photo sharper / bigger.

        image_url parameter (REQUIRED):
          Pass the full image URL exactly as it appears in the conversation.
          It will be one of:
            • "data:image/png;base64,<very long base64 string>"
            • "/api/v1/files/<uuid>/content"
          Extract it from the image_url.url field of the image_url content
          block in the user's message. Do NOT shorten or omit it.

        scale parameter:
          IMPORTANT: Default is ALWAYS 4 (maximum quality, 4× upscale).
          ONLY use a lower value (1, 2, or 3) if the user EXPLICITLY requests
          it (e.g. "upscale 2x", "use scale 3"). If the user says "upscale",
          "enhance", "make bigger", or anything without a specific number →
          use 4.

        :param image_url: Full image URL from the message content (see above).
        :param scale: Upscale multiplier — 1, 2, 3, or 4. DEFAULT IS 4. Only
                      use a lower value when the user explicitly specifies it.
        """
        emitter = __event_emitter__
        user_valves = (__user__ or {}).get("valves")

        # ── Effective configuration ───────────────────────────────────────────
        owui_base = self.valves.owui_internal_base or OWUI_INTERNAL_BASE
        http_url = self.valves.comfyui_url.rstrip("/")

        # ── Resolve and validate scale ────────────────────────────────────────
        try:
            scale = int(scale)
        except (TypeError, ValueError):
            scale = 0

        if scale not in (1, 2, 3, 4):
            fallback = int(getattr(user_valves, "default_scale", 4) or 4)
            if fallback not in (1, 2, 3, 4):
                fallback = 4
            logger.info("Invalid scale %r — falling back to %d", scale, fallback)
            scale = fallback

        scale_label = f"{scale}×"
        unload = self._should_unload(user_valves)
        vram_note = " (VRAM freed)" if unload else " (model kept in VRAM)"

        # ── Resolve image bytes ───────────────────────────────────────────────
        await self._emit_status(emitter, "🔍 Resolving source image…")
        image_bytes: Optional[bytes] = None

        # Strategy 1: LLM-supplied image_url argument
        if image_url and image_url.strip():
            logger.info("Trying image_url arg (%.80s…)", image_url)
            image_bytes = await _bytes_from_url(image_url.strip(), owui_base)

        # Strategy 2: scan __messages__ as fallback
        if image_bytes is None and __messages__:
            logger.info(
                "Scanning __messages__ for image URLs (%d messages)",
                len(__messages__),
            )
            for url in _extract_image_urls_from_messages(__messages__):
                logger.info("Trying message URL (%.80s…)", url)
                image_bytes = await _bytes_from_url(url, owui_base)
                if image_bytes:
                    break

        if image_bytes is None:
            await self._emit_status(
                emitter, "❌ Could not load source image.", done=True
            )
            return (
                "❌ Could not load the source image. "
                "Please make sure an image is attached to this conversation "
                "and try again. "
                f"(image_url received: {(image_url or 'none')[:120]})"
            )

        logger.info("Source image resolved — %d bytes", len(image_bytes))

        # ── Upload source image to ComfyUI ────────────────────────────────────
        await self._emit_status(emitter, "📤 Uploading image to ComfyUI…")
        src_filename = f"owui_input_{uuid.uuid4().hex[:8]}.png"
        try:
            comfy_filename = await _upload_image_to_comfyui(
                http_url, image_bytes, src_filename
            )
        except Exception as exc:
            await self._emit_status(
                emitter, f"❌ ComfyUI upload failed: {exc}", done=True
            )
            return f"❌ Failed to upload image to ComfyUI: {exc}"

        # ── Build workflow ────────────────────────────────────────────────────
        workflow = copy.deepcopy(WORKFLOW_WITH_UNLOAD if unload else WORKFLOW_NO_UNLOAD)
        workflow["2"]["inputs"]["image"] = comfy_filename
        # "resize_type.scale" is a literal dot-separated key in the node's
        # input schema — this is NOT a nested dict; it must be set as-is.
        workflow["1"]["inputs"]["resize_type.scale"] = scale

        # ── Submit and wait ───────────────────────────────────────────────────
        client_id = str(uuid.uuid4())
        await self._emit_status(
            emitter,
            f"🚀 Running {scale_label} ULTRA upscale via RTX VSR…",
        )
        try:
            job_result = await _submit_and_wait(
                http_url,
                workflow,
                client_id,
                self.valves.max_wait_seconds,
            )
        except TimeoutError as exc:
            await self._emit_status(emitter, f"⏱️ Timed out: {exc}", done=True)
            return f"⏱️ {exc}"
        except Exception as exc:
            await self._emit_status(emitter, f"❌ ComfyUI error: {exc}", done=True)
            return f"❌ ComfyUI error: {exc}"

        # ── Extract output image metadata ─────────────────────────────────────
        output_images = _extract_output_images(job_result)
        if not output_images:
            await self._emit_status(
                emitter,
                "⚠️ ComfyUI finished but produced no output images.",
                done=True,
            )
            return (
                "⚠️ ComfyUI finished but produced no output images. "
                "Verify that the RTXVideoSuperResolution custom node is "
                "installed correctly and the GPU supports RTX VSR."
            )

        # ── Store image and emit into chat ────────────────────────────────────
        await self._emit_status(emitter, "💾 Storing upscaled image…")

        results: List[str] = []
        for idx, img_meta in enumerate(output_images):
            out_filename = f"upscaled_{scale}x_ULTRA_{uuid.uuid4().hex[:6]}.png"
            display_url = await _resolve_display_url(
                http_url, img_meta, owui_base, __request__, out_filename
            )
            if not display_url:
                logger.error("Could not obtain a display URL for image %d", idx)
                continue

            # KEY FIX: use "files" event, not "message".
            # See _emit_image() docstring for full explanation.
            await self._emit_image(emitter, display_url, scale_label, vram_note)
            results.append(display_url)

        if not results:
            await self._emit_status(
                emitter, "❌ Failed to retrieve upscaled image.", done=True
            )
            return (
                "❌ Upscaling completed in ComfyUI but the resulting image "
                "could not be retrieved or stored."
            )

        await self._emit_status(emitter, "✅ Upscaling complete!", done=True)

        # Return a concise instruction so the LLM does NOT re-embed the image
        # via markdown (it's already attached as a file).
        return (
            f"Image upscaled {scale_label} ULTRA successfully{vram_note}. "
            "The upscaled image has already been attached to this message as "
            "a file — do NOT include any markdown image syntax in your reply. "
            "Briefly confirm to the user that the upscale is done."
        )
