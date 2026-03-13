"""
title: Thinking + Sampling Presets
author: ichrist
version: 2.1.0
license: MIT
description: >
  Thinking mode toggle + sampling parameter presets for Qwen3 / llama.cpp.
  REQUIRES: llama-server --jinja --reasoning-budget 0
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal

# ── Thinking depth ────────────────────────────────────────────────────────────
DEPTH_MAP = {
    "Unlimited": -1,
    "MAX": 16000,
    "Deep": 8192,
    "Normal": 3072,
    "Quick": 512,
}

DEPTH_HINTS = {
    "Unlimited": "",
    "MAX": "You have an enormous reasoning budget. Use every token of it. Explore exhaustively.",
    "Deep": "Reason carefully and thoroughly through every step before answering.",
    "Normal": "Think through the problem before answering, but stay concise.",
    "Quick": "Think briefly, then give a direct and concise answer.",
}

# ── Thinking style presets ────────────────────────────────────────────────────
THINKING_PRESETS = {
    "None": "",
    "Think Less": "Do not overthink. Reach a conclusion quickly and avoid excessive reasoning.",
    "Think More": "Think deeply and explore multiple angles before settling on an answer.",
    "Extended Thinking": (
        "Before answering, conduct an extended internal deliberation. "
        "Explore the problem space broadly: consider edge cases, alternative interpretations, "
        "counterarguments, and second-order effects. Stress-test your initial conclusions. "
        "Only converge on an answer after exhausting the major lines of reasoning."
    ),
    "MAX Thinking": (
        "You are in maximum reasoning mode. Think as long and as deeply as humanly possible — "
        "do not cut corners, do not rush to conclusions. "
        "Map out every relevant concept, assumption, and implication. "
        "Consider the problem from first principles, from domain expertise, from edge cases, "
        "and from adversarial angles. Challenge every intermediate conclusion before accepting it. "
        "If a chain of reasoning feels complete, ask yourself: what have I missed? "
        "Only after exhaustive internal deliberation should you begin composing your answer."
    ),
    "Step by Step": "Break down your reasoning into clear numbered steps.",
    "Devil's Advocate": "Consider and steelman the opposing viewpoint before giving your answer.",
    "First Principles": (
        "Strip the problem down to its most fundamental truths. "
        "Refuse to rely on analogy or convention. "
        "Rebuild your reasoning from the ground up using only what can be directly justified."
    ),
    "10x Hypotheses": (
        "Before answering, generate at least ten distinct hypotheses or approaches. "
        "Briefly evaluate each. Then select and develop the most promising one."
    ),
    "Socratic": (
        "Interrogate the question itself before answering. "
        "What assumptions does it carry? Are those assumptions valid? "
        "What is really being asked beneath the surface?"
    ),
    "Rubber Duck": (
        "Explain your reasoning step by step out loud as if teaching it to someone who knows nothing. "
        "Narrate every logical move. Catch your own mistakes as you speak them."
    ),
    "Pre-Mortem": (
        "Assume your answer or plan will fail. "
        "Think through every plausible reason it could go wrong before you commit to it. "
        "Then adjust your answer to address those failure modes."
    ),
    "Bayesian": (
        "Reason probabilistically. "
        "Assign rough confidence levels to key claims. "
        "Update them as you reason. "
        "State your final answer with an honest calibrated uncertainty."
    ),
    "Contrarian": (
        "Your default stance is skepticism. "
        "Challenge the framing of the question. "
        "Push back on obvious answers. "
        "Only accept a conclusion if it survives hard scrutiny."
    ),
}

# ── Presentation presets ──────────────────────────────────────────────────────
PRESENTATION_PRESETS = {
    "None": "",
    "ELI5": "After thinking, explain your answer as simply as possible, like I'm five.",
    "Be Concise": "After thinking, give the shortest possible answer that is still complete.",
    "Bullet Points": "Present your final answer as a clean bulleted list.",
    "TL;DR First": "Open your answer with a one-sentence TL;DR, then elaborate.",
    "Teach Me": (
        "Present your answer as a mini-lesson: start with the core concept, "
        "build up with examples, and end with a memorable takeaway."
    ),
    "Expert Tone": (
        "Write your answer at graduate level. "
        "Use precise technical vocabulary. Assume the reader is a domain expert."
    ),
    "Casual Chat": "Write your answer like you're texting a smart friend. Relaxed, no jargon.",
    "Debate Format": (
        "Structure your answer as a formal debate: "
        "state the proposition, present the strongest case for it, "
        "then the strongest case against it, then your verdict."
    ),
    "Analogies Only": (
        "Explain everything exclusively through analogies and metaphors. "
        "Do not use technical terms — map every concept to something concrete and familiar."
    ),
    "Action Items": "Distill your answer into concrete, numbered action items the user can execute immediately.",
    "Socratic Reply": (
        "Instead of stating conclusions directly, guide the user to them "
        "through a sequence of probing questions."
    ),
}

# ── Sampling presets ──────────────────────────────────────────────────────────
# Each entry is a dict of params to inject, or None to leave everything untouched.
# Parameter names match llama.cpp's OpenAI-compatible API root-level fields.
#   temperature       – randomness (float)
#   top_p             – nucleus sampling (float)
#   top_k             – top-k sampling (int)
#   min_p             – min-p sampling (float)
#   presence_penalty  – penalise tokens already present in context (float)
#   repeat_penalty    – penalise repeated token sequences, llama.cpp native (float)
#   repetition_penalty – alias used by some frontends / vLLM (same value)
SAMPLING_PRESETS: dict = {
    # ── "Default": touch nothing — let Open-WebUI / model settings win ────────
    "Default": None,
    # ── Instruct (non-thinking) · general tasks ───────────────────────────────
    "Instruct General": {
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "repeat_penalty": 1.0,
        "repetition_penalty": 1.0,
    },
    # ── Instruct (non-thinking) · reasoning / analytical tasks ───────────────
    "Instruct Reasoning": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "repeat_penalty": 1.0,
        "repetition_penalty": 1.0,
    },
    # ── Thinking mode · general tasks ────────────────────────────────────────
    "Thinking General": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "repeat_penalty": 1.0,
        "repetition_penalty": 1.0,
    },
    # ── Thinking mode · precise / coding tasks ────────────────────────────────
    "Thinking Precise": {
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 0.0,
        "repeat_penalty": 1.0,
        "repetition_penalty": 1.0,
    },
}

# ── Descriptions for Valve dropdowns ─────────────────────────────────────────
DEPTH_DESC = (
    "Unlimited = no cap · MAX = 16k tokens · Deep = 8k · Normal = 3k · Quick = 512"
)
THINKING_DESC = (
    "None = vanilla · Think Less/More = effort · Extended/MAX = deep deliberation · "
    "Step by Step / First Principles / 10x Hypotheses / Socratic / Rubber Duck / "
    "Pre-Mortem / Bayesian / Contrarian = reasoning style"
)
PRESENTATION_DESC = (
    "None = vanilla · ELI5 · Be Concise · Bullet Points · TL;DR First · Teach Me · "
    "Expert Tone · Casual Chat · Debate Format · Analogies Only · Action Items · Socratic Reply"
)
SAMPLING_DESC = (
    "Default = don't touch existing settings · "
    "Instruct General = temp 0.7, top_p 0.8, top_k 20, presence 1.5 · "
    "Instruct Reasoning = temp 1.0, top_p 0.95, top_k 20, presence 1.5 · "
    "Thinking General = temp 1.0, top_p 0.95, top_k 20, presence 1.5 · "
    "Thinking Precise = temp 0.6, top_p 0.95, top_k 20, presence 0.0 (coding)"
)

# ── Literal type aliases ──────────────────────────────────────────────────────
ThinkingDepthLiteral = Literal["Unlimited", "MAX", "Deep", "Normal", "Quick"]
ThinkingPresetLiteral = Literal[
    "None",
    "Think Less",
    "Think More",
    "Extended Thinking",
    "MAX Thinking",
    "Step by Step",
    "Devil's Advocate",
    "First Principles",
    "10x Hypotheses",
    "Socratic",
    "Rubber Duck",
    "Pre-Mortem",
    "Bayesian",
    "Contrarian",
]
PresentationPresetLiteral = Literal[
    "None",
    "ELI5",
    "Be Concise",
    "Bullet Points",
    "TL;DR First",
    "Teach Me",
    "Expert Tone",
    "Casual Chat",
    "Debate Format",
    "Analogies Only",
    "Action Items",
    "Socratic Reply",
]
SamplingPresetLiteral = Literal[
    "Default",
    "Instruct General",
    "Instruct Reasoning",
    "Thinking General",
    "Thinking Precise",
]


class Filter:

    class Valves(BaseModel):
        priority: int = Field(default=0)
        inject_depth_hint: bool = Field(
            default=False,
            description="Inject a prompt nudge that matches the chosen depth level.",
        )
        enable_thinking: bool = Field(
            default=True,
            description=(
                "Enable thinking mode (enable_thinking=True + reasoning_budget). "
                "Set to False to use non-thinking instruct mode while keeping all "
                "other presets (sampling, presentation) fully active."
            ),
        )
        default_thinking_depth: ThinkingDepthLiteral = Field(
            default="Unlimited", description=DEPTH_DESC
        )
        default_thinking_preset: ThinkingPresetLiteral = Field(
            default="None", description=THINKING_DESC
        )
        default_presentation_preset: PresentationPresetLiteral = Field(
            default="None", description=PRESENTATION_DESC
        )
        default_sampling_preset: SamplingPresetLiteral = Field(
            default="Default", description=SAMPLING_DESC
        )

    class UserValves(BaseModel):
        enable_thinking: bool = Field(
            default=True,
            description=(
                "Enable thinking mode. Set to False to use non-thinking instruct mode "
                "while keeping sampling presets and presentation style active."
            ),
        )
        thinking_depth: ThinkingDepthLiteral = Field(
            default="Unlimited", description=DEPTH_DESC
        )
        thinking_preset: ThinkingPresetLiteral = Field(
            default="None", description=THINKING_DESC
        )
        presentation_preset: PresentationPresetLiteral = Field(
            default="None", description=PRESENTATION_DESC
        )
        sampling_preset: SamplingPresetLiteral = Field(
            default="Default", description=SAMPLING_DESC
        )

    def __init__(self):
        self.valves = self.Valves()
        self.toggle = True
        self.icon = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIHN0cm9rZT0ibm9uZSIgZD0iTTAgMGgyNHYyNEgweiIgZmlsbD0ibm9uZSIvPjxwYXRoIGQ9Ik0xNS41IDEzYTMuNSAzLjUgMCAwIDAgLTMuNSAzLjV2MWEzLjUgMy41IDAgMCAwIDcgMHYtMS44IiAvPjxwYXRoIGQ9Ik04LjUgMTNhMy41IDMuNSAwIDAgMSAzLjUgMy41djFhMy41IDMuNSAwIDAgMSAtNyAwdi0xLjgiIC8+PHBhdGggZD0iTTE3LjUgMTZhMy41IDMuNSAwIDAgMCAwIC03aC0uNSIgLz48cGF0aCBkPSJNMTkgOS4zdi0yLjhhMy41IDMuNSAwIDAgMCAtNyAwIiAvPjxwYXRoIGQ9Ik02LjUgMTZhMy41IDMuNSAwIDAgMSAwIC03aC41IiAvPjxwYXRoIGQ9Ik01IDkuM3YtMi44YTMuNSAzLjUgMCAwIDEgNyAwdjEwIiAvPjwvc3ZnPg=="

    # ─────────────────────────────────────────────────────────────────────────
    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:

        uv = None
        if __user__ and "valves" in __user__:
            try:
                uv = __user__["valves"]
            except Exception:
                pass

        # ── 1. Resolve thinking on/off (user valve beats admin valve) ─────────
        thinking_on = self.valves.enable_thinking
        if uv:
            try:
                thinking_on = uv.enable_thinking
            except Exception:
                pass

        # ── 2. Resolve depth ──────────────────────────────────────────────────
        depth = self.valves.default_thinking_depth
        if uv:
            try:
                ud = uv.thinking_depth
                if ud != "Unlimited" or depth == "Unlimited":
                    depth = ud
            except Exception:
                pass

        # ── 3. Resolve thinking style preset ─────────────────────────────────
        thinking_key = self.valves.default_thinking_preset
        if uv:
            try:
                ut = uv.thinking_preset
                if ut != "None":
                    thinking_key = ut
            except Exception:
                pass

        # ── 4. Resolve presentation preset ───────────────────────────────────
        presentation_key = self.valves.default_presentation_preset
        if uv:
            try:
                up = uv.presentation_preset
                if up != "None":
                    presentation_key = up
            except Exception:
                pass

        # ── 5. Resolve sampling preset ────────────────────────────────────────
        sampling_key = self.valves.default_sampling_preset
        if uv:
            try:
                us = uv.sampling_preset
                if us != "Default":
                    sampling_key = us
            except Exception:
                pass

        # ── 6. Inject llama.cpp thinking params ───────────────────────────────
        # enable_thinking=False + reasoning_budget=0 → full non-thinking mode.
        # enable_thinking=True  + reasoning_budget=-1 → unlimited thinking.
        body["chat_template_kwargs"] = {"enable_thinking": thinking_on}
        body["reasoning_budget"] = DEPTH_MAP.get(depth, -1) if thinking_on else 0

        # ── 7. Inject sampling parameters ────────────────────────────────────
        # Written directly onto body root so llama.cpp receives them verbatim.
        # Also mirrored into body["options"] for Ollama-routed connections.
        sampling_params = SAMPLING_PRESETS.get(sampling_key)
        if sampling_params is not None:
            for key, value in sampling_params.items():
                body[key] = value

            options = body.setdefault("options", {})
            _ollama_map = {
                "temperature": "temperature",
                "top_p": "top_p",
                "top_k": "top_k",
                "min_p": "min_p",
                "presence_penalty": "presence_penalty",
                "repeat_penalty": "repeat_penalty",
            }
            for src_key, opt_key in _ollama_map.items():
                if src_key in sampling_params:
                    options[opt_key] = sampling_params[src_key]

        # ── 8. Build prompt injection text ───────────────────────────────────
        parts = []
        if self.valves.inject_depth_hint and thinking_on:
            hint = DEPTH_HINTS.get(depth, "")
            if hint:
                parts.append(hint)
        if thinking_on:
            thinking_text = THINKING_PRESETS.get(thinking_key, "")
            if thinking_text:
                parts.append(thinking_text)
        presentation_text = PRESENTATION_PRESETS.get(presentation_key, "")
        if presentation_text:
            parts.append(presentation_text)

        if not parts:
            return body

        injection = "\n\n".join(parts)
        messages = body.get("messages", [])

        # ── 9. Inject into system message ─────────────────────────────────────
        sys_idx = next(
            (i for i, m in enumerate(messages) if m.get("role") == "system"), None
        )
        if sys_idx is not None:
            existing = messages[sys_idx].get("content", "")
            messages[sys_idx]["content"] = (
                f"{injection}\n\n{existing}" if existing else injection
            )
        else:
            messages.insert(0, {"role": "system", "content": injection})

        # ── 10. Hard fallback: stamp last user message ────────────────────────
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                content = messages[i].get("content", "")
                if isinstance(content, list):
                    content.append(
                        {"type": "text", "text": f"\n[System instruction: {injection}]"}
                    )
                    messages[i]["content"] = content
                else:
                    messages[i][
                        "content"
                    ] = f"{content}\n[System instruction: {injection}]"
                break

        body["messages"] = messages
        return body
