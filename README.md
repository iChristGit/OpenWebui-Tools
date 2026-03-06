<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=200&section=header&text=Open%20WebUI%20Tools&fontSize=50&fontColor=fff&animation=twinkling&fontAlignY=38&desc=6%20tools%20to%20supercharge%20your%20AI%20%E2%80%94%20install%20in%2030%20seconds&descAlignY=58&descSize=16" />

<p>
  <a href="https://openwebui.com/u/ichrist"><img src="https://img.shields.io/badge/%F0%9F%9B%92%20Marketplace-ichrist-7C3AED?style=for-the-badge&labelColor=1a1a2e" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge&labelColor=1a1a2e" /></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.8+-3b82f6?style=for-the-badge&logo=python&logoColor=white&labelColor=1a1a2e" /></a>
  <a href="https://claude.ai"><img src="https://img.shields.io/badge/Built%20with-Claude%20%E2%9D%A4-f97316?style=for-the-badge&labelColor=1a1a2e" /></a>
</p>

<p>
  <img src="https://img.shields.io/badge/🎬_Jellyfin-Stream-6366f1?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🧩_Ask_User-Input-8b5cf6?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🎭_Personas-Switch-a855f7?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/📖_Wikipedia-Lookup-c084fc?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/🌌_Orchestrator-Plan-d946ef?style=flat-square&labelColor=0f0f23" />
  <img src="https://img.shields.io/badge/😂_Jokes-Laugh-ec4899?style=flat-square&labelColor=0f0f23" />
</p>

</div>

---

## 🗺️ Quick Navigation

| # | Tool | Best for |
|---|------|----------|
| 1 | [🎬 Jellyfin Media Player](#-jellyfin-media-player) | Stream movies, TV & music from your own server |
| 2 | [🧩 Ask User](#-ask-user) | The right questions before the right answer |
| 3 | [🎭 Persona Studio](#-persona-studio) | Instantly switch your AI's personality & tone |
| 4 | [📖 Wikipedia](#-wikipedia) | Instant encyclopedia lookups in 20+ languages |
| 5 | [🌌 Omniscient Orchestrator](#-omniscient-orchestrator) | Multi-stage AI workflow with strategy selection |
| 6 | [😂 Joke Tool](#-joke-tool) | 300+ programmer jokes on demand |

---

## 🎬 Jellyfin Media Player

> **Stream your entire Jellyfin library inside Open WebUI** — with a cinematic embedded player, subtitle support, quality presets, and album art.

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
</table>

<details>
<summary><b>🎵 Music Player — click to expand</b></summary>
<br/>
<div align="center">
  <img src="https://github.com/user-attachments/assets/fe272f89-c5c6-482b-95f1-9e0e66f62641" width="80%" alt="Jellyfin music player with waveform" />
  <p><i>Full music player with waveform visualiser, album art & EQ animation</i></p>
</div>
</details>

<br/>

### ✨ What it does

Your Jellyfin library, right inside the chat. Ask for any movie, show, or track in plain English and get an embedded player back — no tab-switching, no searching, no fuss.

| Feature | Detail |
|---------|--------|
| 🎬 Movies & TV | Stream any item, use `S01E01` or `1x01` episode notation |
| 🎵 Music | Full player with waveform visualiser, album art & EQ animation |
| 🎲 Random picks | Ask for a random film, optionally filter by genre |
| 💬 Subtitles | Dropdown with every available language track |
| 📐 Quality | Original · 4K · 1080p · 720p · 480p · 360p |
| ⬇️ Download | Download button on every player |
| 🔎 Info mode | Get rich media details without opening a player |

<details>
<summary><b>⚙️ Setup (3 steps)</b></summary>

1. Create a **restricted Jellyfin user** (playback-only, no admin or delete permissions)
2. Generate an API key: **Dashboard → API Keys → +**
3. Paste both into the tool valves: `JELLYFIN_HOST` and `JELLYFIN_API_KEY`

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
```

</details>

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

## 🌌 Omniscient Orchestrator

> **Stop getting generic answers.** Make your LLM pause, ask the right questions, pick a strategy — then produce something genuinely tailored to your goal.

**[→ Install from marketplace](https://openwebui.com/posts/orchestrator_0f269681)**

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
