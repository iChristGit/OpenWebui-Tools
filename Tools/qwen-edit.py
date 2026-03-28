"""
title: ComfyUI Qwen Image Edit
description: >
  Edit images using the Qwen Image Edit 2511 model via ComfyUI.
  Accepts 1, 2, or 3 reference images — the correct workflow is selected
  automatically based on how many images are present in the conversation.
  Supports optional VRAM offloading of Ollama and llama.cpp before inference
  so the diffusion model gets the full GPU budget.
  Flow: LLM tool call → offload LLM → run ComfyUI workflow (UnloadAllModels
  at end) → image returned to chat.
author: ichrist
version: 1.0.0
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

# ─── Workflow templates ────────────────────────────────────────────────────────
#
# Each workflow mirrors the uploaded JSON exactly.  Placeholder values that
# will be replaced at runtime are marked with  <<<PLACEHOLDER>>>.
#
# Node map (shared across all three variants):
#   "78"       – LoadImage  → image1 (base image, passes through FluxKontextImageScale)
#   "436"      – LoadImage  → image2  (2-image and 3-image workflows only)
#   "437"      – LoadImage  → image3  (3-image workflow only)
#   "435"      – PrimitiveStringMultiline → user prompt text
#   "433:117"  – FluxKontextImageScale (wraps image1)
#   "433:111"  – TextEncodeQwenImageEditPlus (positive conditioning)
#   "433:110"  – TextEncodeQwenImageEditPlus (negative conditioning, empty prompt)
#   "433:88"   – VAEEncode
#   "433:3"    – KSampler
#   "433:8"    – VAEDecode
#   "438"      – UnloadAllModels  (wraps VAEDecode output → SaveImage reads from here)
#   "60"       – SaveImage


def _base_workflow() -> Dict[str, Any]:
    """Return nodes that are identical across all three workflow variants."""
    return {
        "60": {
            "inputs": {"filename_prefix": "qwen_edit", "images": ["438", 0]},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        },
        "78": {
            "inputs": {"image": "<<<IMAGE1>>>"},
            "class_type": "LoadImage",
            "_meta": {"title": "Load Image"},
        },
        "435": {
            "inputs": {"value": "<<<PROMPT>>>"},
            "class_type": "PrimitiveStringMultiline",
            "_meta": {"title": "Prompt"},
        },
        "438": {
            "inputs": {"value": ["433:8", 0]},
            "class_type": "UnloadAllModels",
            "_meta": {"title": "UnloadAllModels"},
        },
        "433:75": {
            "inputs": {"strength": 1, "model": ["433:66", 0]},
            "class_type": "CFGNorm",
            "_meta": {"title": "CFGNorm"},
        },
        "433:39": {
            "inputs": {"vae_name": "qwen_image_vae.safetensors"},
            "class_type": "VAELoader",
            "_meta": {"title": "Load VAE"},
        },
        "433:38": {
            "inputs": {
                "clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "type": "qwen_image",
                "device": "default",
            },
            "class_type": "CLIPLoader",
            "_meta": {"title": "Load CLIP"},
        },
        "433:37": {
            "inputs": {
                "unet_name": "qwen_image_edit_2511_fp8mixed.safetensors",
                "weight_dtype": "default",
            },
            "class_type": "UNETLoader",
            "_meta": {"title": "Load Diffusion Model"},
        },
        "433:66": {
            "inputs": {"shift": 3, "model": ["433:89", 0]},
            "class_type": "ModelSamplingAuraFlow",
            "_meta": {"title": "ModelSamplingAuraFlow"},
        },
        "433:89": {
            "inputs": {
                "lora_name": "Qwen-Image-Lightning-4steps-V2.0.safetensors",
                "strength_model": 1,
                "model": ["433:37", 0],
            },
            "class_type": "LoraLoaderModelOnly",
            "_meta": {"title": "Load LoRA"},
        },
        "433:117": {
            "inputs": {"image": ["78", 0]},
            "class_type": "FluxKontextImageScale",
            "_meta": {"title": "FluxKontextImageScale"},
        },
        "433:88": {
            "inputs": {"pixels": ["433:117", 0], "vae": ["433:39", 0]},
            "class_type": "VAEEncode",
            "_meta": {"title": "VAE Encode"},
        },
        "433:8": {
            "inputs": {"samples": ["433:3", 0], "vae": ["433:39", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        },
        "433:3": {
            "inputs": {
                "seed": 0,  # replaced at runtime
                "steps": 4,
                "cfg": 1,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1,
                "model": ["433:75", 0],
                "positive": ["433:111", 0],
                "negative": ["433:110", 0],
                "latent_image": ["433:88", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        },
    }


def _workflow_1_image() -> Dict[str, Any]:
    wf = _base_workflow()
    wf["433:111"] = {
        "inputs": {
            "prompt": ["435", 0],
            "clip": ["433:38", 0],
            "vae": ["433:39", 0],
            "image1": ["433:117", 0],
        },
        "class_type": "TextEncodeQwenImageEditPlus",
        "_meta": {"title": "TextEncodeQwenImageEditPlus"},
    }
    wf["433:110"] = {
        "inputs": {
            "prompt": "",
            "clip": ["433:38", 0],
            "vae": ["433:39", 0],
            "image1": ["433:117", 0],
        },
        "class_type": "TextEncodeQwenImageEditPlus",
        "_meta": {"title": "TextEncodeQwenImageEditPlus"},
    }
    return wf


def _workflow_2_images() -> Dict[str, Any]:
    wf = _base_workflow()
    wf["436"] = {
        "inputs": {"image": "<<<IMAGE2>>>"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    }
    wf["433:111"] = {
        "inputs": {
            "prompt": ["435", 0],
            "clip": ["433:38", 0],
            "vae": ["433:39", 0],
            "image1": ["433:117", 0],
            "image2": ["436", 0],
        },
        "class_type": "TextEncodeQwenImageEditPlus",
        "_meta": {"title": "TextEncodeQwenImageEditPlus"},
    }
    wf["433:110"] = {
        "inputs": {
            "prompt": "",
            "clip": ["433:38", 0],
            "vae": ["433:39", 0],
            "image1": ["433:117", 0],
            "image2": ["436", 0],
        },
        "class_type": "TextEncodeQwenImageEditPlus",
        "_meta": {"title": "TextEncodeQwenImageEditPlus"},
    }
    return wf


def _workflow_3_images() -> Dict[str, Any]:
    wf = _base_workflow()
    wf["436"] = {
        "inputs": {"image": "<<<IMAGE2>>>"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    }
    wf["437"] = {
        "inputs": {"image": "<<<IMAGE3>>>"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    }
    wf["433:111"] = {
        "inputs": {
            "prompt": ["435", 0],
            "clip": ["433:38", 0],
            "vae": ["433:39", 0],
            "image1": ["433:117", 0],
            "image2": ["436", 0],
            "image3": ["437", 0],
        },
        "class_type": "TextEncodeQwenImageEditPlus",
        "_meta": {"title": "TextEncodeQwenImageEditPlus"},
    }
    wf["433:110"] = {
        "inputs": {
            "prompt": "",
            "clip": ["433:38", 0],
            "vae": ["433:39", 0],
            "image1": ["433:117", 0],
            "image2": ["436", 0],
            "image3": ["437", 0],
        },
        "class_type": "TextEncodeQwenImageEditPlus",
        "_meta": {"title": "TextEncodeQwenImageEditPlus"},
    }
    return wf


# ─── Image helpers ─────────────────────────────────────────────────────────────


async def _bytes_from_url(url: str, owui_base: str) -> Optional[bytes]:
    """
    Resolve image bytes from any URL format Open-WebUI can produce:
      1. data:image/...;base64,...  → decode inline
      2. /api/v1/files/{id}/content → GET from OWUI server-side base
      3. http(s)://...              → GET directly
    """
    if not url:
        return None

    if url.startswith("data:"):
        try:
            data = base64.b64decode(url.split(",", 1)[1])
            logger.info("Decoded inline base64 image (%d bytes)", len(data))
            return data
        except Exception as exc:
            logger.warning("base64 decode failed: %s", exc)
            return None

    if url.startswith("/"):
        full = owui_base.rstrip("/") + url
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(full) as r:
                    if r.status == 200:
                        data = await r.read()
                        logger.info("Fetched OWUI-internal image (%d bytes)", len(data))
                        return data
                    logger.warning("OWUI internal fetch %s → HTTP %d", url, r.status)
        except Exception as exc:
            logger.warning("OWUI internal fetch error: %s", exc)
        return None

    if url.startswith("http://") or url.startswith("https://"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.read()
                        logger.info("Fetched image from URL (%d bytes)", len(data))
                        return data
        except Exception as exc:
            logger.warning("URL fetch error: %s", exc)
        return None

    logger.warning("Unrecognised image URL format: %.80s", url)
    return None


def _extract_image_urls_from_messages(messages: List[Dict[str, Any]]) -> List[str]:
    """
    Walk __messages__ newest-first and collect all image_url content blocks.
    Returns URLs in discovery order (newest message first, then in-message order).
    """
    found: List[str] = []
    for msg in reversed(messages):
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    obj = part.get("image_url") or {}
                    url = obj.get("url") or obj.get("src") or ""
                    if url:
                        found.append(url)
    return found


# ─── ComfyUI helpers ───────────────────────────────────────────────────────────


async def _upload_image_to_comfyui(
    http_url: str, image_bytes: bytes, filename: str
) -> str:
    """Upload raw image bytes to ComfyUI /upload/image; return stored filename."""
    form = aiohttp.FormData()
    form.add_field(
        "image",
        io.BytesIO(image_bytes),
        filename=filename,
        content_type="image/png",
    )
    form.add_field("type", "input")
    form.add_field("overwrite", "true")

    async with aiohttp.ClientSession() as s:
        async with s.post(f"{http_url.rstrip('/')}/upload/image", data=form) as r:
            r.raise_for_status()
            stored = (await r.json()).get("name", filename)
            logger.info("Uploaded to ComfyUI as: %s", stored)
            return stored


async def _submit_and_wait(
    http_url: str,
    workflow: Dict[str, Any],
    client_id: str,
    max_wait: int,
) -> Dict[str, Any]:
    """
    Queue a ComfyUI workflow and wait for completion.
    Primary path: WebSocket events.  Fallback: HTTP polling every 3 s.
    """
    ws_base = http_url.replace("http://", "ws://").replace("https://", "wss://")
    start = asyncio.get_event_loop().time()
    prompt_id: Optional[str] = None

    async with aiohttp.ClientSession() as session:
        # Queue the prompt first so we always have a prompt_id
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

        # WebSocket listener with periodic HTTP poll as belt-and-suspenders
        try:
            async with session.ws_connect(f"{ws_base}/ws?clientId={client_id}") as ws:
                last_poll = 0.0
                while True:
                    elapsed = asyncio.get_event_loop().time() - start
                    if elapsed > max_wait:
                        raise TimeoutError(f"Timed out after {max_wait}s")

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
                                        logger.info("Job complete (poll)")
                                        return h[prompt_id]
                        except Exception:
                            pass

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
                            continue

                        if t in (
                            "execution_cached",
                            "executed",
                            "execution_success",
                        ):
                            async with session.get(
                                f"{http_url}/history/{prompt_id}"
                            ) as fr:
                                if fr.status == 200:
                                    h = await fr.json()
                                    if prompt_id in h:
                                        logger.info("Job complete (WS: %s)", t)
                                        return h[prompt_id]

                        elif t == "execution_error":
                            raise RuntimeError(
                                f"ComfyUI error on node "
                                f"{d.get('node_id', '?')}: "
                                f"{d.get('exception_message', 'unknown')}"
                            )

                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        logger.warning("WS closed/error — switching to polling")
                        break

        except (aiohttp.ClientError, OSError) as exc:
            logger.warning("WS connect failed (%s) — polling only", exc)

        # Pure HTTP polling fallback
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
    """Return all SaveImage output entries from a ComfyUI history job."""
    images: List[Dict[str, str]] = []
    for node_output in job.get("outputs", {}).values():
        for img in node_output.get("images", []):
            if img.get("type") == "output":
                images.append(img)
    return images


# ─── OWUI file storage ─────────────────────────────────────────────────────────


async def _fetch_from_comfyui(
    http_url: str, img_meta: Dict[str, str]
) -> Optional[bytes]:
    """Download output image bytes from ComfyUI /view."""
    params: Dict[str, str] = {
        "filename": img_meta["filename"],
        "type": img_meta.get("type", "output"),
    }
    if img_meta.get("subfolder"):
        params["subfolder"] = img_meta["subfolder"]

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{http_url.rstrip('/')}/view", params=params) as r:
                r.raise_for_status()
                data = await r.read()
                logger.info("Fetched output from ComfyUI (%d bytes)", len(data))
                return data
    except Exception as exc:
        logger.warning("Failed to fetch image from ComfyUI: %s", exc)
        return None


async def _upload_to_owui_rest(
    owui_base: str,
    image_bytes: bytes,
    filename: str,
    request: Any,
) -> Optional[str]:
    """
    Store image in OWUI's file REST API.
    Returns /api/v1/files/{id}/content on success, else None.
    """
    headers: Dict[str, str] = {"accept": "application/json"}
    if request is not None:
        try:
            auth = request.headers.get("Authorization") or request.headers.get(
                "authorization"
            )
            if auth:
                headers["Authorization"] = auth
            else:
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
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=form, headers=headers) as r:
                if r.status in (200, 201):
                    data = await r.json()
                    fid = data.get("id")
                    if fid:
                        content_url = f"/api/v1/files/{fid}/content"
                        logger.info("Stored in OWUI files: %s", content_url)
                        return content_url
                    logger.warning("OWUI /files response missing 'id': %s", data)
                else:
                    logger.warning(
                        "OWUI upload failed — HTTP %d: %s",
                        r.status,
                        (await r.text())[:200],
                    )
    except Exception as exc:
        logger.warning("OWUI REST upload error: %s", exc)
    return None


def _to_data_uri(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def _resolve_display_url(
    http_url: str,
    img_meta: Dict[str, str],
    owui_base: str,
    request: Any,
    filename: str,
) -> str:
    image_bytes = await _fetch_from_comfyui(http_url, img_meta)
    if image_bytes is None:
        return ""
    owui_url = await _upload_to_owui_rest(owui_base, image_bytes, filename, request)
    if owui_url:
        return owui_url
    logger.info("OWUI upload failed; falling back to base64 data URI")
    return _to_data_uri(image_bytes)


# ─── LLM offload helpers ───────────────────────────────────────────────────────


async def _unload_ollama(base_url: str) -> str:
    """
    Unload all models currently loaded in Ollama by setting keep_alive=0.
    Returns a brief status string for logging.
    """
    base = base_url.rstrip("/")
    unloaded: List[str] = []
    try:
        async with aiohttp.ClientSession() as s:
            # Get list of running models
            async with s.get(
                f"{base}/api/ps", timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status != 200:
                    return f"Ollama /api/ps → HTTP {r.status} (skipped)"
                data = await r.json()

            models = [
                m.get("name", "") for m in data.get("models", []) if m.get("name")
            ]
            if not models:
                return "Ollama: no models loaded (nothing to unload)"

            for model in models:
                try:
                    payload = {"model": model, "keep_alive": 0}
                    async with s.post(
                        f"{base}/api/generate",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as ur:
                        status = ur.status
                        await ur.read()  # drain
                        if status in (200, 204):
                            unloaded.append(model)
                        else:
                            logger.warning("Ollama unload %s → HTTP %d", model, status)
                except Exception as exc:
                    logger.warning("Ollama unload %s failed: %s", model, exc)

        if unloaded:
            return f"Ollama: unloaded {', '.join(unloaded)}"
        return "Ollama: unload attempted but no confirmations"

    except Exception as exc:
        return f"Ollama offload skipped ({exc})"


async def _unload_llama_cpp(base_url: str) -> str:
    """
    Unload all loaded models from llama.cpp router mode VRAM.

    Uses the llama.cpp router API (requires router/multi-model mode):
      GET  /v1/models      → list models, filter by status == "loaded"
      POST /models/unload  → unload each by id
    """
    base = base_url.rstrip("/")
    unloaded: List[str] = []
    failed: List[str] = []

    try:
        async with aiohttp.ClientSession() as s:
            # ── 1. List loaded models ─────────────────────────────────────
            async with s.get(
                f"{base}/v1/models",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return f"llama.cpp /v1/models → HTTP {r.status} (skipped)"
                data = await r.json()

            loaded_ids: List[str] = []
            for m in data.get("data", []):
                status = m.get("status", {})
                status_val = (
                    status.get("value", "") if isinstance(status, dict) else status
                )
                if status_val == "loaded":
                    loaded_ids.append(m["id"])

            if not loaded_ids:
                return "llama.cpp: no models loaded (nothing to unload)"

            # ── 2. Unload each model ──────────────────────────────────────
            for model_id in loaded_ids:
                try:
                    async with s.post(
                        f"{base}/models/unload",
                        json={"model": model_id},
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as ur:
                        if ur.status in (200, 204):
                            unloaded.append(model_id)
                        else:
                            body = await ur.text()
                            failed.append(f"{model_id} (HTTP {ur.status}: {body[:80]})")
                except Exception as exc:
                    failed.append(f"{model_id} ({exc})")

        parts: List[str] = []
        if unloaded:
            parts.append(f"unloaded: {', '.join(unloaded)}")
        if failed:
            parts.append(f"failed: {', '.join(failed)}")
        return "llama.cpp: " + "; ".join(parts)

    except Exception as exc:
        return f"llama.cpp offload skipped ({exc})"


# ─── Main Tool class ───────────────────────────────────────────────────────────


class Tools:

    class Valves(BaseModel):
        comfyui_url: str = Field(
            default="http://localhost:8188",
            description="Base URL of your ComfyUI instance.",
        )
        owui_internal_base: str = Field(
            default="http://localhost:8080",
            description=(
                "Server-side base URL OWUI uses to fetch/store files "
                "(e.g. http://localhost:8080). Must be reachable from the "
                "OWUI container/process, not from the browser."
            ),
        )
        ollama_url: str = Field(
            default="http://localhost:11434",
            description=(
                "Base URL of your Ollama instance. Used to unload models "
                "before running the ComfyUI diffusion workflow so the GPU "
                "has maximum free VRAM."
            ),
        )
        llama_cpp_url: str = Field(
            default="http://localhost:8082",
            description=(
                "Base URL of your llama.cpp router server. Uses GET /v1/models "
                "to list loaded models and POST /models/unload to evict each "
                "from VRAM before the diffusion workflow runs. Requires "
                "llama.cpp running in router/multi-model mode."
            ),
        )
        unload_ollama: bool = Field(
            default=True,
            description=(
                "Unload all Ollama models from VRAM before running the "
                "ComfyUI workflow. Recommended when Ollama and ComfyUI share "
                "the same GPU. Disable on systems with separate GPUs or "
                "enough VRAM for both."
            ),
        )
        unload_llama_cpp: bool = Field(
            default=True,
            description=(
                "Unload all llama.cpp router models from VRAM before running "
                "the ComfyUI workflow. Requires llama.cpp in router mode. "
                "Harmless if llama.cpp is not running."
            ),
        )
        max_wait_seconds: int = Field(
            default=600,
            description=(
                "Maximum seconds to wait for ComfyUI to finish the image "
                "edit workflow."
            ),
        )
        seed: int = Field(
            default=-1,
            description=(
                "Random seed for the KSampler. -1 picks a random seed each " "run."
            ),
        )

    class UserValves(BaseModel):
        unload_ollama: bool = Field(
            default=True,
            description=(
                "Unload Ollama from VRAM before the diffusion run. "
                "Override the admin default for your personal preference."
            ),
        )
        unload_llama_cpp: bool = Field(
            default=True,
            description=(
                "Flush llama.cpp VRAM before the diffusion run. "
                "Override the admin default."
            ),
        )
        seed: int = Field(
            default=-1,
            description="Personal default seed. -1 = random.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _should_unload_ollama(self, user_valves: Any) -> bool:
        if user_valves and hasattr(user_valves, "unload_ollama"):
            return bool(user_valves.unload_ollama)
        return self.valves.unload_ollama

    def _should_unload_llama_cpp(self, user_valves: Any) -> bool:
        if user_valves and hasattr(user_valves, "unload_llama_cpp"):
            return bool(user_valves.unload_llama_cpp)
        return self.valves.unload_llama_cpp

    def _effective_seed(self, user_valves: Any) -> int:
        if user_valves and hasattr(user_valves, "seed"):
            s = int(user_valves.seed)
        else:
            s = int(self.valves.seed)
        if s < 0:
            import random

            return random.randint(1, 2**32 - 1)
        return s

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
        label: str,
    ) -> None:
        """
        Attach the result image to the chat message using the 'files' event.

        WHY "files" and NOT "message":
          In Native function-calling mode, OWUI replays successive
          chat:completion snapshots that overwrite message body content —
          anything injected via "message" events disappears.  The "files"
          event stores the image as a file attachment which is handled by a
          separate code path and survives those overwrites.
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
                            "name": label,
                            "collection_name": "",
                        }
                    ]
                },
            }
        )

    # ── Tool entry point ───────────────────────────────────────────────────────

    async def qwen_edit(
        self,
        prompt: str,
        image_url_1: str,
        image_url_2: str = "",
        image_url_3: str = "",
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        __user__: Optional[Dict[str, Any]] = None,
        __messages__: Optional[List[Dict[str, Any]]] = None,
        __request__: Optional[Any] = None,
    ) -> str:
        """
        Edit or composite images using the Qwen Image Edit 2511 model.

        Automatically selects the 1-image, 2-image, or 3-image ComfyUI
        workflow depending on how many image URLs are provided.

        BEFORE calling this tool, the LLM offloads Ollama / llama.cpp (if
        enabled) so the diffusion model gets maximum free VRAM.  The ComfyUI
        workflow itself contains an UnloadAllModels node at the end, freeing
        diffusion model weights after generation.

        ─── How to provide images ───────────────────────────────────────────
        image_url_1 (REQUIRED):
          The primary/base image.  Extract the full URL exactly as it appears
          in the conversation — either:
            • "data:image/png;base64,<long base64 string>"
            • "/api/v1/files/<uuid>/content"
          Do NOT shorten, truncate, or paraphrase it.

        image_url_2 / image_url_3 (OPTIONAL):
          Second and third reference images in the same format.  Leave as ""
          (empty string) when not needed.  The tool will detect how many real
          images are supplied and pick the matching workflow.

        ─── Prompt guidelines ───────────────────────────────────────────────
        Describe what you want using "image1", "image2", "image3" to refer to
        the uploaded images, e.g.:
          • "the person from image1 is wearing the outfit from image2"
          • "place the object from image2 into the scene from image1"
          • "image1 background, image2 subject, image3 style"

        :param prompt:      Edit instruction referencing image1/image2/image3.
        :param image_url_1: Full URL of the primary image.
        :param image_url_2: Full URL of the second reference image (or "").
        :param image_url_3: Full URL of the third reference image (or "").
        """
        emitter = __event_emitter__
        user_valves = (__user__ or {}).get("valves")
        owui_base = self.valves.owui_internal_base or OWUI_INTERNAL_BASE
        http_url = self.valves.comfyui_url.rstrip("/")

        # ── 1. Resolve all image bytes from URLs + message fallback ───────────
        await self._emit_status(emitter, "🔍 Resolving source images…")

        # Collect candidate URLs: LLM-supplied args first, then message scan
        arg_urls = [
            u for u in [image_url_1, image_url_2, image_url_3] if u and u.strip()
        ]
        msg_urls: List[str] = []
        if __messages__:
            msg_urls = _extract_image_urls_from_messages(__messages__)

        # Resolve bytes for each position
        resolved_bytes: List[bytes] = []
        attempted_urls = list(arg_urls) + [u for u in msg_urls if u not in arg_urls]

        for url in attempted_urls:
            if len(resolved_bytes) >= 3:
                break
            data = await _bytes_from_url(url.strip(), owui_base)
            if data:
                resolved_bytes.append(data)

        n_images = len(resolved_bytes)

        if n_images == 0:
            await self._emit_status(emitter, "❌ No images found.", done=True)
            return (
                "❌ Could not resolve any source images. "
                "Please make sure at least one image is attached to the "
                "conversation and try again."
            )

        logger.info("Resolved %d image(s) for Qwen Edit workflow", n_images)

        # ── 2. Offload LLM VRAM before the heavy diffusion run ────────────────
        if self._should_unload_ollama(user_valves):
            await self._emit_status(emitter, "⬇️ Unloading Ollama from VRAM…")
            msg = await _unload_ollama(self.valves.ollama_url)
            logger.info(msg)

        if self._should_unload_llama_cpp(user_valves):
            await self._emit_status(emitter, "⬇️ Flushing llama.cpp VRAM…")
            msg = await _unload_llama_cpp(self.valves.llama_cpp_url)
            logger.info(msg)

        # ── 3. Upload image(s) to ComfyUI ─────────────────────────────────────
        await self._emit_status(emitter, "📤 Uploading image(s) to ComfyUI…")
        comfy_filenames: List[str] = []
        for i, img_bytes in enumerate(resolved_bytes):
            fname = f"owui_qwen_input{i + 1}_{uuid.uuid4().hex[:8]}.png"
            try:
                stored = await _upload_image_to_comfyui(http_url, img_bytes, fname)
                comfy_filenames.append(stored)
            except Exception as exc:
                await self._emit_status(
                    emitter, f"❌ Upload failed for image {i + 1}: {exc}", done=True
                )
                return f"❌ Failed to upload image {i + 1} to ComfyUI: {exc}"

        # ── 4. Build the workflow ─────────────────────────────────────────────
        if n_images == 1:
            workflow = copy.deepcopy(_workflow_1_image())
            workflow_label = "1-image"
        elif n_images == 2:
            workflow = copy.deepcopy(_workflow_2_images())
            workflow["436"]["inputs"]["image"] = comfy_filenames[1]
            workflow_label = "2-image"
        else:
            workflow = copy.deepcopy(_workflow_3_images())
            workflow["436"]["inputs"]["image"] = comfy_filenames[1]
            workflow["437"]["inputs"]["image"] = comfy_filenames[2]
            workflow_label = "3-image"

        # Inject image1 and prompt into all variants
        workflow["78"]["inputs"]["image"] = comfy_filenames[0]
        workflow["435"]["inputs"]["value"] = prompt
        workflow["433:3"]["inputs"]["seed"] = self._effective_seed(user_valves)

        # ── 5. Submit and wait ────────────────────────────────────────────────
        client_id = str(uuid.uuid4())
        await self._emit_status(
            emitter,
            f"🎨 Running Qwen Image Edit ({workflow_label} workflow)…",
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

        # ── 6. Extract and store output image ─────────────────────────────────
        output_images = _extract_output_images(job_result)
        if not output_images:
            await self._emit_status(
                emitter,
                "⚠️ ComfyUI finished but produced no output images.",
                done=True,
            )
            return (
                "⚠️ ComfyUI finished but produced no output images. "
                "Check that the Qwen Image Edit model files are correctly "
                "installed and the TextEncodeQwenImageEditPlus custom node "
                "is available."
            )

        await self._emit_status(emitter, "💾 Storing result image…")
        results: List[str] = []
        for idx, img_meta in enumerate(output_images):
            out_filename = f"qwen_edit_{workflow_label}_{uuid.uuid4().hex[:6]}.png"
            display_url = await _resolve_display_url(
                http_url, img_meta, owui_base, __request__, out_filename
            )
            if not display_url:
                logger.error("Could not obtain display URL for output image %d", idx)
                continue
            await self._emit_image(emitter, display_url, out_filename)
            results.append(display_url)

        if not results:
            await self._emit_status(
                emitter, "❌ Failed to retrieve result image.", done=True
            )
            return (
                "❌ The workflow completed in ComfyUI but the result image "
                "could not be retrieved or stored."
            )

        await self._emit_status(emitter, "✅ Image edit complete!", done=True)

        return (
            f"Image edit completed successfully using the {workflow_label} workflow "
            f"({n_images} input image(s)). The result has been attached to this "
            "message as a file — do NOT include any markdown image syntax in your "
            "reply. Briefly confirm to the user that the edit is done."
        )
