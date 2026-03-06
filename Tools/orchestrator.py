"""
title: 🌌 The Omniscient Orchestrator
author: ichrist
version: 2.0
description: A high-polish, multi-stage workflow engine for autonomous clarification, path selection, and persona alignment.
"""

from typing import List, Dict, Optional
import time


class Tools:
    def __init__(self):
        self.max_questions = 3
        self.paths_limit = 3

    async def orchestrate(
        self,
        rationale: str,
        clarification_questions: List[str],
        execution_paths: List[Dict[str, str]],
        __event_call__=None,
        __event_emitter__=None,
    ) -> str:
        """
        The ultimate workflow tool. Call this when a request is complex.
        It handles deep clarification and strategic path selection in a polished UI.

        :param rationale: A brief explanation of why this workflow is starting.
        :param clarification_questions: 1-3 critical questions to define the 'What'.
        :param execution_paths: 3 distinct paths (Title & Description) to define the 'How'.
        """

        if not __event_call__ or not __event_emitter__:
            return "⚠️ Interface Error: Interactive Modules Offline."

        # --- PHASE 1: INITIALIZATION ---
        await __event_emitter__(
            {
                "type": "status",
                "data": {
                    "description": "🧠 Analyzing Query Architecture...",
                    "done": False,
                },
            }
        )
        time.sleep(0.5)

        # --- PHASE 2: THE CLARIFICATION MODAL ---
        # Guardrail: Limit questions to prevent fatigue
        active_qs = clarification_questions[: self.max_questions]
        answers = []

        for i, q in enumerate(active_qs):
            resp = await __event_call__(
                {
                    "type": "input",
                    "data": {
                        "title": f"🛠️ DATA ACQUISITION: STEP {i+1}/{len(active_qs)}",
                        "message": (
                            f"**Current Task:** {rationale}\n\n"
                            f"--- \n"
                            f"**MISSING PARAMETER:** \n"
                            f"> {q}\n"
                            f"--- \n"
                            "💡 *Please provide specific details to ensure maximum accuracy.*"
                        ),
                        "placeholder": "Type your details here...",
                    },
                }
            )
            # Guardrail: Handle empty responses
            answer_text = (
                resp
                if resp and str(resp).strip()
                else "Not specified (Defaulting to expert choice)."
            )
            answers.append(f"Param {i+1}: {q} | Value: {answer_text}")

        # --- PHASE 3: THE NEXUS PATH SELECTION ---
        await __event_emitter__(
            {
                "type": "status",
                "data": {
                    "description": "🌌 Stabilization Complete. Opening Nexus...",
                    "done": False,
                },
            }
        )

        path_options = ""
        for i, p in enumerate(execution_paths[: self.paths_limit]):
            path_options += f"**{i+1}️⃣ {p['title']}**\n*{p['description']}*\n\n"

        selected_path = await __event_call__(
            {
                "type": "input",
                "data": {
                    "title": "🧭 STRATEGIC DIRECTION",
                    "message": (
                        "I have formulated three distinct execution timelines. \n"
                        "**Which path shall we manifest?**\n\n"
                        f"{path_options}"
                        "--- \n"
                        "✍️ *Enter the number (1, 2, or 3) of your preferred strategy.*"
                    ),
                    "placeholder": "1, 2, or 3...",
                },
            }
        )

        # --- PHASE 4: FINAL VALIDATION ---
        await __event_emitter__(
            {
                "type": "status",
                "data": {
                    "description": "✅ All Parameters Locked. Commencing Generation.",
                    "done": True,
                },
            }
        )

        # Return a neatly formatted data block for the LLM to process
        result_summary = (
            f"### ORCHESTRATION COMPLETE\n"
            f"**Rationale:** {rationale}\n"
            f"**Clarifications:** {answers}\n"
            f"**Selected Timeline:** {selected_path}\n"
            f"---\n"
            f"Proceed with the final output now."
        )
        return result_summary
