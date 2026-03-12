<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=200&section=header&text=Open%20WebUI%20Tools&fontSize=50&fontColor=fff&animation=twinkling&fontAlignY=38&desc=9%20tools%20to%20supercharge%20your%20AI%20%E2%80%94%20install%20in%2030%20seconds&descAlignY=58&descSize=16" />

<p>
  <a href="https://openwebui.com/u/ichrist"><img src="https://img.shields.io/badge/%F0%9F%9B%92%20Marketplace-ichrist-7C3AED?style=for-the-badge&labelColor=1a1a2e" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge&labelColor=1a1a2e" /></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.8+-3b82f6?style=for-the-badge&logo=python&logoColor=white&labelColor=1a1a2e" /></a>
  <a href="https://claude.ai"><img src="https://img.shields.io/badge/Built%20with-Claude%20%E2%9D%A4-f97316?style=for-the-badge&labelColor=1a1a2e" /></a>
</p>

<p>
  <img src="https://img.shields.io/badge/🎥_LTX_2.3-Video_Gen-6366f1?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🎬_Jellyfin-Stream-6366f1?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🧩_Ask_User-Input-8b5cf6?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🎭_Personas-Switch-a855f7?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/📖_Wikipedia-Lookup-c084fc?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🌌_Orchestrator-Plan-d946ef?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/😂_Jokes-Laugh-ec4899?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🧠_Thinking-Reason-06b6d4?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/💾_VRAM-Unload-ef4444?style=flat-square&labelColor=0f0f23" />
</p>

</div>

---

## 🗺️ Quick Navigation

| # | Tool | Best for |
|---|------|----------|
| 1 | [🎥 LTX-2.3 Video Generator](#-ltx-23-video-generator) | Generate AI videos from text or images via ComfyUI |
| 2 | [🎬 Jellyfin Media Player](#-jellyfin-media-player) | Stream movies, TV, music & live TV from your own server |
| 3 | [🧠 Thinking Filter](#-thinking-filter) | One-click thinking toggle + full reasoning control for llama.cpp |
| 4 | [🧩 Ask User](#-ask-user) | The right questions before the right answer |
| 5 | [🎭 Persona Studio](#-persona-studio) | Instantly switch your AI's personality & tone |
| 6 | [📖 Wikipedia](#-wikipedia) | Instant encyclopedia lookups in 20+ languages |
| 7 | [🌌 Omniscient Orchestrator](#-omniscient-orchestrator) | Multi-stage AI workflow with strategy selection |
| 8 | [😂 Joke Tool](#-joke-tool) | 300+ programmer jokes on demand |
| 9 | [💾 VRAM Unload](#-vram-unload) | Unload llamacpp models with one click |

---

🛒 Install from the Open WebUI Marketplace

The fastest way to get these tools running. No copy-paste required — install directly from the Open WebUI marketplace in seconds.

<div align="center"> <a href="https://openwebui.com/u/ichrist"> <img src="https://img.shields.io/badge/Open_WebUI_Marketplace-ichrist-7C3AED?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2Zy8+&labelColor=1a1a2e"/> </a> </div>

---

## 🎥 LTX-2.3 Video Generator

> **Generate cinematic AI videos from a text prompt or an uploaded image** — powered by LTX-Video 2.3 (22B FP8) running locally in ComfyUI, with an embedded player, mobile-compatible output, and creative filenames chosen by the LLM.

**[→ Install from marketplace](https://openwebui.com/posts/ltx_23_video_generator_text_to_video_image_to_vide_d31d1572)**

> 🙏 Adapted from **[Haervwe's WAN 2.2 ComfyUI tool](https://github.com/Haervwe/open-webui-tools)** — the original inspiration for this implementation.

<div align="center">
  <img src="https://github.com/user-attachments/assets/0882ac31-6863-4351-b26d-c8b9f5267b69" width="80%" alt="LTX-2.3 Video Generator screenshot" />
</div>

<br/>

### ✨ What it does

Two tools in one: **Text-to-Video** and **Image-to-Video**, both driven by the LTX-Video 2.3 22B model running locally in ComfyUI. Ask for a video in plain English, get a fully embedded player back in chat — with a download button, open button, and a creative title the LLM names itself.

| Feature | Detail |
|---------|--------|
| ✍️ Text-to-Video | Generate from any prompt at 1280×720, configurable up to 30 s |
| 🖼️ Image-to-Video | Animate any uploaded image at its native resolution |
| 📱 Mobile-compatible | ffmpeg post-encode to H.264 `yuv420p` + `faststart` — shareable on iOS & WhatsApp |
| 🎲 Random seeds | Both noise seeds randomised every generation — never duplicate outputs |
| 🎬 Creative filenames | LLM picks a unique 2–4 word title per video (e.g. `Dragon_Awakens_Dawn_i2v`) |
| 🔋 Auto VRAM unload | Unloads Ollama models from VRAM before generating to free headroom |
| ⏱️ Configurable duration | 5 s · 10 s · 15 s · 20 s · 25 s · 30 s — set per user |
| 🔑 Optional API key | Bearer token support for secured ComfyUI setups |

<details>
<summary><b>⚙️ Prerequisites</b></summary>

This tool connects to a running ComfyUI instance with LTX-Video 2.3 already set up. You'll need:

1. **ComfyUI** running with an LTX-2.3 workflow loaded — see [LightricksAI/LTX-Video](https://huggingface.co/Lightricks/LTX-Video) for models
2. **[ComfyUI-Unload-Model](https://github.com/SeanScripts/ComfyUI-Unload-Model)** custom node installed — required by the workflow to free VRAM between pipeline stages

Then configure the tool valves:

| Valve | Default | What it does |
|-------|---------|--------------|
| `comfyui_api_url` | `http://localhost:8188` | ComfyUI HTTP endpoint |
| `comfyui_api_key` | *(empty)* | Bearer token if ComfyUI is behind auth |
| `owui_internal_base` | `http://localhost:8080` | Internal OWUI URL for file serving |
| `video_length_frames` | `241` | Default frame count (241 = 10 s at 24 fps) |
| `frame_rate` | `24` | Output fps |
| `t2v_width` / `t2v_height` | `1280` / `720` | Text-to-Video output resolution |
| `max_wait_time` | `600` | Seconds before timeout (generation takes 3–10 min) |
| `unload_ollama_models` | `true` | Auto-free Ollama VRAM before each generation |
| `ollama_api_url` | `http://localhost:11434` | Your Ollama server address |

</details>

<details>
<summary><b>🗣️ Example prompts</b></summary>

```
make a video of a samurai walking through cherry blossoms at sunset
generate a 15 second clip of ocean waves crashing at night
animate this image [upload any photo]
create a video of a neon-lit city street in heavy rain
a slow-motion shot of a red fox jumping through snow
timelapse of storm clouds rolling over a mountain range
```

</details>

<details>
<summary><b>⚡ Per-user settings</b></summary>

Each user can override the admin defaults independently:

| Setting | Options |
|---------|---------|
| `video_duration` | `5s` `10s` `15s` `20s` `25s` `30s` |
| `frame_rate` | Any integer (default `24`) |
| `t2v_width` / `t2v_height` | Any resolution (default `1280×720`) |

</details>

---

---

## 🎬 Jellyfin Media Player

> **Stream your entire Jellyfin library inside Open WebUI** — with a cinematic embedded player, subtitle support, quality presets, album art, and live TV with EPG.

**[→ Install from marketplace](https://openwebui.com/posts/jellyfin_tool_movies_tv_shows_and_music_in_your_op_92cc018e)**

<table>
  <tr>
    <td width="50%" align="center">
      <b>🎬 Movies</b><br/><br/>
      <img src="https://github.com/user-attachments/assets/eaf06d46-7659-4cb4-9d47-e6754d935b19" width="100%" alt="Jellyfin movie player" />
    </td>
    <td width="50%" align="center">
      <b>📺 TV Shows</b><br/><br/>
      <img src="https://github.com/user-attachments/assets/1494ebe0-26ca-4dae-ad45-29b4b81735b8" width="100%" alt="Jellyfin TV player" />
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <b>📡 Live TV</b><br/><br/>
      <img src="https://github.com/user-attachments/assets/aa2b8509-cbf0-4e67-b698-c8338bfb08b6" width="100%" alt="Jellyfin live TV player" />
    </td>
    <td width="50%" align="center">
      <b>🎵 Music</b><br/><br/>
      <img src="https://github.com/user-attachments/assets/6950300f-f413-4a4f-a1f5-7990461efb77" width="100%" alt="Jellyfin music player" />
    </td>
  </tr>
</table>

### ✨ What it does

Your Jellyfin library, right inside the chat. Ask for any movie, show, track, or live channel in plain English and get an embedded player back — no tab-switching, no searching, no fuss.

| Feature | Detail |
|---------|--------|
| 🎬 Movies & TV | Stream any item, use `S01E01` or `1x01` episode notation |
| 🎵 Music | Full player with waveform visualiser, album art & EQ animation |
| 📡 Live TV | Tune to any channel with a pulsing LIVE badge and EPG now-playing info |
| 🎲 Random picks | Ask for a random film, episode, or song — optionally filter by genre |
| 💬 Subtitles | Dropdown with every available language track |
| 📐 Quality | Original · 4K · 1080p · 720p · 480p · 360p |
| ⬇️ Download | Download button on every player |
| 🔎 Info mode | Get rich media details without opening a player |

<details>
<summary><b>⚙️ Setup (3 steps)</b></summary>

1. Create a **restricted Jellyfin user** (playback-only, no admin or delete permissions)
2. Generate an API key: **Dashboard → API Keys → +**
3. Paste both into the tool valves: `JELLYFIN_HOST` and `JELLYFIN_API_KEY`

> For Live TV, you'll also need a tuner or IPTV source configured under **Dashboard → Live TV**.

</details>

<details>
<summary><b>🗣️ Example prompts</b></summary>

```
play Inception
play Breaking Bad S03E10
play music Bohemian Rhapsody
random comedy movie
tell me about Interstellar
what was recently added
watch live CNN
list live channels
```

</details>

---

---

## 🧠 Thinking Filter

> **The missing thinking toggle for llama.cpp + Qwen3.** One click to unleash deep reasoning. One click to turn it off. And when you want more — full control over depth, style, and how answers are presented.

**[→ Install from marketplace](https://openwebui.com/posts/thinking_toggle_one_click_reasoning_control_for_ll_bb3f66ad)**

<img width="1101" height="330" alt="8bed8be1-8d6a-42b1-bb0d-f2929fe1cb9e" src="https://github.com/user-attachments/assets/e77d688b-ba3a-47a9-b49f-f331c1158949" />


### ✨ What it does

llama.cpp supports Qwen3's extended `<think>` reasoning mode natively — but Open WebUI has no built-in toggle for it. This filter fixes that completely, replacing manual tweaking with a proper one-click think button and a full suite of reasoning controls.

| Feature | Detail |
|---------|--------|
| 🧠 One-click toggle | Brain button in the ✦ panel — ON thinks, OFF is instant vanilla |
| 🔀 enable_thinking valve | Toggle thinking on/off per-user without disabling the filter — sampling & presentation stay active either way |
| 🎛️ 4 sampling presets | Force Qwen3.5's official parameters at llama.cpp API level — Instruct General · Instruct Reasoning · Thinking General · Thinking Precise |
| 📊 5 depth levels | Unlimited · MAX (16k) · Deep (8k) · Normal (3k) · Quick (512 tokens) |
| 🔬 13 reasoning presets | Shape *how* it thinks |
| 🎨 11 presentation presets | ELI5, Expert Tone, TL;DR First — shape *how* it answers |
| 👤 Per-user control | Every user sets their own depth, style, and sampling independently |
| 🔒 Bulletproof injection | Dual-path injection (system + user message) works around Open WebUI's pipeline bug |

<details>
<summary><b>⚡ Setup (1 step)</b></summary>

**Step 1 — Start llama-server with:**

```bash
llama-server --jinja --reasoning-budget 0
```

The `--reasoning-budget 0` flag lets the filter set the budget dynamically per request. That's it — done forever.

Enable the function and set it as default for your qwen3.5 models if you want the default to be thinking enabled.
(If you rather have thinking disabled by default do not set the function as default!)

Now every chat has a 🧠 button that can be diabled in one click and enabled back in two clicks.

</details>

<details>
<summary><b>📊 Thinking Depth</b></summary>

| Depth | Token Budget | Best for |
|-------|-------------|----------|
| **Unlimited** | No cap | Default — model thinks as long as it needs |
| **MAX** | 16 000 tokens | Hardest problems, exhaustive analysis |
| **Deep** | 8 000 tokens | Complex reasoning, careful step-by-step |
| **Normal** | 3 000 tokens | Everyday use, balanced |
| **Quick** | 512 tokens | Fast answers with just a hint of thought |

</details>

<details>
<summary><b>🔬 Reasoning Presets — <i>how</i> the model thinks</b></summary>

| Preset | What it does |
|--------|-------------|
| **None** | Vanilla — pure thinking, no style instruction |
| **Think Less** | Skip over-analysis, reach conclusions fast |
| **Think More** | Explore multiple angles before settling |
| **Extended Thinking** | Deep deliberation: edge cases, counterargs, stress-tests every conclusion |
| **MAX Thinking** | 🔥 Exhaustive — never stops early, challenges everything, asks "what have I missed?" Pair with MAX depth |
| **Step by Step** | Numbered structured reasoning, nothing skipped |
| **Devil's Advocate** | Steelmans the opposing view before answering |
| **First Principles** | Strips to fundamentals, rebuilds from scratch |
| **10x Hypotheses** | Generates 10 distinct approaches, evaluates all, picks the best |
| **Socratic** | Interrogates the question's own assumptions before answering |
| **Rubber Duck** | Narrates every logical move out loud — catches its own mistakes |
| **Pre-Mortem** | Assumes the answer will fail, fixes it before giving it |
| **Bayesian** | Probabilistic reasoning with honest calibrated confidence |
| **Contrarian** | Default skepticism — challenges obvious answers, demands proof |

</details>

<details>
<summary><b>🎨 Presentation Presets — <i>how</i> the answer looks</b></summary>

| Preset | What it does |
|--------|-------------|
| **None** | Vanilla output |
| **ELI5** | Explain like I'm five — strip all complexity |
| **Be Concise** | Shortest complete answer, zero padding |
| **Bullet Points** | Clean bulleted list |
| **TL;DR First** | One-sentence summary up top, then full detail |
| **Teach Me** | Concept → examples → memorable takeaway |
| **Expert Tone** | Graduate-level, precise vocabulary |
| **Casual Chat** | Relaxed, no jargon, like texting a smart friend |
| **Debate Format** | Strongest FOR → strongest AGAINST → verdict |
| **Analogies Only** | Everything through metaphors, zero technical terms |
| **Action Items** | Numbered steps to execute immediately |
| **Socratic Reply** | Guides you to the answer through probing questions |

</details>

<details>
<summary><b>🎛️ Mix & Match Examples</b></summary>

| Depth | Reasoning | Presentation | Result |
|-------|-----------|-------------|--------|
| MAX | MAX Thinking | Expert Tone | 🔥 Deepest possible analysis, grad-level output |
| Normal | Bayesian | TL;DR First | Calibrated probabilistic answer, summary first |
| Quick | None | Be Concise | Lightning-fast minimal answer |
| Deep | First Principles | Teach Me | Rebuilds from scratch, explains like a lesson |
| Deep | Devil's Advocate | Debate Format | Full steelman treatment, structured verdict |
| Unlimited | Contrarian | ELI5 | Challenges every assumption, explains simply |

</details>

---

---

## 🧩 Ask User

> **Replicate Claude's "ask follow-up questions before acting" behaviour** — collect structured multi-step input through sequential popup dialogs before your AI writes a single word.

**[→ Install from marketplace](https://openwebui.com/posts/ask_user_14182520)**

<div align="center">
  <img src="https://github.com/user-attachments/assets/48ba79cb-38d4-4fe7-8845-0750d3409486" width="80%" alt="Ask User screenshot" />
</div>

<br/>

### ✨ What it does

Ever notice how Claude pauses, asks you a few targeted questions, then produces something far more on-point? This tool brings that exact behaviour to Open WebUI. The LLM can ask 1–5 structured questions upfront — each in its own popup with a progress indicator — before committing to a response.

| Feature | Detail |
|---------|--------|
| 📋 Up to 5 questions | Defined upfront — no infinite loops |
| 🪟 One popup per question | Clear progress indicator: `Question 2 of 4` |
| 📦 Structured output | All answers returned together before the LLM acts |
| 🔒 Bounded & predictable | The LLM cannot keep asking — it must proceed |
| 🔑 No dependencies | Standard library only |

<details>
<summary><b>🗣️ Best for</b></summary>

```
"Write me a cover letter"    → gathers: role, company, tone, key achievements
"Plan my project"            → gathers: deadline, team size, stack, goals
"Draft a cold email"         → gathers: recipient, offer, call to action
"Create a workout plan"      → gathers: goal, equipment, days per week
```

> ⚠️ **Requires** Open WebUI with interactive input modal support. Won't work in headless or API-only environments.

</details>

---

---

## 🎭 Persona Studio

> **Instantly reshape how your AI thinks and communicates** — dozens of crafted personas across multiple categories, plus a fully custom option.

**[→ Install from marketplace](https://openwebui.com/posts/persona_selector_over_150_personas_for_your_daily_c4406010)**

<div align="center">
  <img src="https://github.com/user-attachments/assets/38035bc1-a629-44a3-8130-dd81275f8af9" width="80%" alt="Persona Studio screenshot" />
</div>

<br/>

### ✨ What it does

Stop editing system prompts manually. Persona Studio gives you an interactive popup browser with categorised personas — each with a distinct tone, voice, quirks, and style. Switch mid-conversation in one message.

| Feature | Detail |
|---------|--------|
| 🎯 Interactive browser | Categorised popup UI — pick and apply in one click |
| 😎 Dozens of personas | Technical · Creative · Professional · Playful · and more |
| ✍️ Custom option | Define any personality from scratch |
| 🚀 Instant switch | No re-prompting, no manual system prompt editing |

<details>
<summary><b>🗣️ Example prompts</b></summary>

```
Switch to a different persona
I want you to respond like a senior engineer doing code review
Change your communication style to casual and funny
Set a custom persona: you are a brutally honest editor
```

</details>

---

---

## 📖 Wikipedia

> **Instant encyclopedia lookups** — smart search, section-aware summaries, disambiguation handling, and 20+ languages. Zero config required.

**[→ Install from marketplace](https://openwebui.com/posts/wikipedia_tool_00b03142)**

<div align="center">
  <img src="https://github.com/user-attachments/assets/6e88aac8-15b1-4d18-b04d-383cfeaf936b" width="80%" alt="Wikipedia tool screenshot" />
</div>

<br/>

### ✨ What it does

Your LLM gets live access to Wikipedia without any API key or setup. It automatically picks the right detail level, handles ambiguous titles gracefully, and always cites the source URL.

| Feature | Detail |
|---------|--------|
| 🔍 Smart search | Natural language queries work fine |
| 📏 3 detail levels | `brief` (intro only) · `standard` (intro + sections) · `full` (entire article) |
| 🗂️ Section-aware | Structured summaries per section — not a wall of text |
| ⚠️ Disambiguation | Shows options when a title matches multiple articles |
| 🌍 20+ languages | Just write in your language — it auto-detects |
| 🔗 Always cited | Every response includes the Wikipedia source URL |
| 🔑 Zero config | Uses the free public MediaWiki API |

<details>
<summary><b>🗣️ Example prompts & supported languages</b></summary>

```
Who is Ada Lovelace?
Explain how black holes work
Tell me everything about the Apollo program
Search Wikipedia for quantum entanglement
¿Quién es Simón Bolívar?
```

**Supported languages:** `en` `fr` `de` `es` `it` `pt` `nl` `sv` `uk` `fa` `ja` `zh` `ar` `ko` `ru` `pl` `tr` `he` `vi` `id`

</details>

---

---

## 🌌 Omniscient Orchestrator

> **Stop getting generic answers.** Make your LLM pause, ask the right questions, pick a strategy — then produce something genuinely tailored to your goal.

**[→ Install from marketplace](https://openwebui.com/posts/orchestrator_0f269681)**

<img width="393" height="746" alt="e263b231-d724-4266-bc95-3b7c277d4393" src="https://github.com/user-attachments/assets/7f453a38-8376-48e0-a44d-c33f36e93936" />

### ✨ What it does

Most LLMs dive straight into an answer, missing context that would have changed everything. The Orchestrator forces a structured 4-phase workflow: understand → clarify → strategise → execute.

| Phase | What happens |
|-------|-------------|
| 🔹 Phase 1 — Analyse | Maps your request, identifies gaps and ambiguities |
| 🔹 Phase 2 — Clarify | Asks up to 3 targeted questions via input modals |
| 🔹 Phase 3 — Strategise | Presents 3 distinct execution approaches to choose from |
| 🔹 Phase 4 — Execute | Generates output with all context locked in |

> **Built-in guardrails:** max 3 questions, always skippable, always moves forward — no infinite loops.

<details>
<summary><b>🗣️ Best for</b></summary>

```
Writing long-form content (articles, landing pages, scripts, reports)
Brainstorming with structured creative options
Planning projects or technical roadmaps
Any prompt where you'd normally need 3 rounds of re-prompting
```

> ⚠️ **Requires** Open WebUI with interactive input modal support. Won't work in headless or API-only environments.

</details>

---

---

## 😂 Joke Tool

> **Give your AI a sense of humour** — 300+ curated programmer jokes, live API fetching, and batch delivery on demand.

**[→ Install from marketplace](https://openwebui.com/posts/jokes_tool_14d95010)**

<div align="center">
  <img src="https://github.com/user-attachments/assets/7ea6a8c9-0ca7-469d-a456-53c71ca26472" width="80%" alt="Joke Tool screenshot" />
</div>

<br/>

### ✨ What it does

A carefully curated vault of programmer humor — Git puns, deep-cut coding jokes, and classic one-liners — plus live fetching from `jokeapi.dev` when you want something fresh.

| Feature | Detail |
|---------|--------|
| 🃏 300+ jokes | Curated vault: Git puns, coding humor, dev classics |
| 🌐 Live mode | Fetches fresh jokes from `jokeapi.dev` on request |
| 🔢 Batch support | Ask for 1 joke or a specific number |
| 🛡️ Offline-safe | Always falls back to internal library if API is down |

<details>
<summary><b>🗣️ Example prompts</b></summary>

```
Tell me a joke
Give me 3 fresh jokes from the internet
Hit me with a random Git pun
Tell me 5 programming jokes
```

</details>

---

## 💾 VRAM Unload

> **Free your GPU memory without leaving the chat** — one action button that detects loaded models and unloads them from VRAM instantly via the llama.cpp router API.

**[→ Install from marketplace](https://openwebui.com/posts/llamacpp_unload_unload_llamacpp_models_from_vram_d_b4252014)**

<img width="968" height="703" alt="Screenshot 2026-03-08 204032" src="https://github.com/user-attachments/assets/0c896fde-142c-472c-8811-463bbd3596d4" />


### ✨ What it does

Running llama.cpp in router mode means models stay resident in VRAM until you explicitly unload them. This action button insantly clean the model from VRAM.

| Feature | Detail |
|---------|--------|
| 🔍 Auto-detects loaded models | Queries `/v1/models` and filters to currently loaded ones |
| 🔁 Multi-model support | Unloads every loaded model in one click if multiple are resident |
| 📡 Live status updates | Status messages as each model unloads, success/error per model |
| 🔑 Zero dependencies | Pure `aiohttp` — nothing extra to install |

<details>
<summary><b>⚙️ Setup (1 step)</b></summary>

Set `LLAMACPP_BASE_URL` in the action valves to your llama.cpp router server:

```
http://127.0.0.1:8080
```

That's it. The action button appears in the chat toolbar — click it any time to free VRAM.

> **Requires llama.cpp running in router mode (llama-server).

</details>

<details>
<summary><b>🛠️ Troubleshooting</b></summary>

| Symptom | Fix |
|---------|-----|
| ❌ "Cannot reach llama.cpp" | Check `LLAMACPP_BASE_URL` is correct and the server is running |
| ℹ️ "No models currently loaded" | No models are resident in VRAM — nothing to unload |
| ❌ HTTP 404 on unload | Make sure llama.cpp is started in router mode, not single-model mode |
| ❌ HTTP 4xx/5xx | Check llama.cpp logs for the specific error |

</details>

---


## 🛠️ Installation

All tools install the same way — takes about 30 seconds.

```
1. Open Workspace → Tools in Open WebUI
2. Click ➕ Add Tool
3. Paste the script, or use one-click import from the marketplace
4. Click Save
5. Enable it in any chat via the 🔧 Tools toggle
```

> 💡 **Tip:** Enable only the tools you need in each chat — keeping the tool list focused helps the LLM pick the right one every time.

---

## 📜 License

All tools are released under the **MIT License** — free to use, fork, modify, and publish.

---

## 💡 Inspiration & Credits

This project wouldn't exist without **[Haervwe's open-webui-tools](https://github.com/Haervwe/open-webui-tools)**.

Haervwe's collection is what got me building my own tools in the first place — seeing what was possible sparked the whole thing. We've also collaborated directly, which shaped several ideas here. If you're looking for even more great Open WebUI tools, their repo is absolutely worth a visit.

> 🙏 Big thanks to [@Haervwe](https://github.com/Haervwe) for the inspiration and the collaboration.

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=120&section=footer" />

Made with ☕ by [ichrist](https://openwebui.com/u/ichrist) · powered by [Claude](https://claude.ai)

⭐ **If these tools save you time, a star goes a long way!**

</div>
