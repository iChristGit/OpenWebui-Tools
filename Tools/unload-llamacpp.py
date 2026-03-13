"""
title: 💾 VRAM Unload
author: ichrist
version: 0.4.0
description: Action button to unload all loaded models from VRAM via llama.cpp router mode API. One-click, no confirmations.
changelog:
  - 0.4.0 - Reworked to match Ollama unloader style: one-click, no confirmation, live status updates, auto-close output
  - 0.3.0 - Original version with confirmation dialog
"""

import asyncio
import time
from pydantic import BaseModel, Field
from typing import Callable, Any, Optional
import aiohttp


class Action:
    class Valves(BaseModel):
        LLAMACPP_BASE_URL: str = Field(
            default="http://127.0.0.1:8082",
            description="Base URL of your llama.cpp router server",
        )
        AUTO_CLOSE_OUTPUT: bool = Field(
            default=True,
            description="Automatically collapse output when finished",
        )
        AUTO_CLOSE_DELAY: int = Field(
            default=3,
            description="Seconds to wait before auto-closing output (default: 3)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.icon = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxyZWN0IHg9IjUiIHk9IjUiIHdpZHRoPSIxNCIgaGVpZ2h0PSIxNCIgcng9IjIiLz48cGF0aCBkPSJNOSA5aDZ2Nkg5eiIvPjxwYXRoIGQ9Ik05IDJ2M00xNSAydjNNOSAxOXYzTTE1IDE5djNNMiA5aDNNMiAxNWgzTTE5IDloM00xOSAxNWgzIi8+PHBhdGggZD0iTTE0IDEyaDRtLTItMmwyIDItMiAyIiAvPjwvc3ZnPg=="

    def _status(
        self, description: str, done: bool = False, status: str = "in_progress"
    ) -> dict:
        """Build a status event payload."""
        return {
            "type": "status",
            "data": {
                "status": status,
                "description": description,
                "done": done,
            },
        }

    async def _close_output(self, emitter: Callable) -> None:
        """Wait, then send signals to collapse the status output."""
        await asyncio.sleep(self.valves.AUTO_CLOSE_DELAY)
        await emitter(self._status("", done=True, status="complete"))
        await emitter({})
        await emitter({"type": "close_output", "data": {"force_close": True}})

    async def action(
        self,
        body: dict,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
        __event_call__: Callable[[dict], Any] = None,
    ) -> Optional[dict]:

        if not __event_emitter__:
            return body

        emit = __event_emitter__
        base_url = self.valves.LLAMACPP_BASE_URL.rstrip("/")

        await emit(self._status("Connecting to llama.cpp..."))

        # ── Step 1: fetch loaded models ────────────────────────────────────────
        loaded_models = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base_url}/v1/models",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for m in data.get("data", []):
                            status = m.get("status", {})
                            status_val = (
                                status.get("value", "")
                                if isinstance(status, dict)
                                else status
                            )
                            if status_val == "loaded":
                                loaded_models.append(m["id"])
                    else:
                        await emit(
                            self._status(
                                f"Unexpected response from llama.cpp: HTTP {resp.status}",
                                done=True,
                                status="error",
                            )
                        )
                        return body

        except Exception as e:
            await emit(
                self._status(
                    f"Cannot reach llama.cpp at {base_url}: {e}",
                    done=True,
                    status="error",
                )
            )
            return body

        if not loaded_models:
            await emit(
                self._status(
                    "No models currently loaded in VRAM.", done=True, status="complete"
                )
            )
            if self.valves.AUTO_CLOSE_OUTPUT:
                asyncio.create_task(self._close_output(emit))
            return body

        await emit(
            self._status(
                f"Found {len(loaded_models)} loaded model(s). Starting unload..."
            )
        )

        # ── Step 2: unload each model ──────────────────────────────────────────
        total_unloaded = 0
        total_failed = 0
        errors = []

        for model_id in loaded_models:
            await emit(self._status(f"Unloading model: {model_id}"))
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{base_url}/models/unload",
                        json={"model": model_id},
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status in (200, 204):
                            total_unloaded += 1
                            await emit(
                                self._status(f"Successfully unloaded model: {model_id}")
                            )
                        else:
                            total_failed += 1
                            resp_text = await resp.text()
                            msg = f"HTTP {resp.status} unloading '{model_id}': {resp_text}"
                            errors.append(msg)
                            await emit(
                                self._status(
                                    f"Failed to unload model: {model_id} — {resp_text}"
                                )
                            )
            except Exception as e:
                total_failed += 1
                msg = f"Error unloading '{model_id}': {e}"
                errors.append(msg)
                await emit(self._status(f"Failed to unload model: {model_id} — {e}"))

        # ── Step 3: final summary ──────────────────────────────────────────────
        if total_unloaded > 0 and total_failed == 0:
            summary = f"Successfully unloaded {total_unloaded} model(s) from VRAM."
            final_status = "complete"
        elif total_unloaded > 0:
            summary = (
                f"Partially successful: unloaded {total_unloaded}, failed {total_failed}.\n"
                + "\n".join(errors)
            )
            final_status = "warning"
        else:
            summary = f"Failed to unload {total_failed} model(s).\n" + "\n".join(errors)
            final_status = "error"

        await emit(self._status(summary, done=True, status=final_status))

        if self.valves.AUTO_CLOSE_OUTPUT:
            asyncio.create_task(self._close_output(emit))

        return body
