<div align="center">

# 🧰 Open WebUI Custom Tools

**6 powerful tools that supercharge your Open WebUI experience** — from cinematic media streaming to structured AI workflows, smart encyclopedias, and dynamic personality switching.

[![Open WebUI Compatible](https://img.shields.io/badge/Open%20WebUI-Compatible-4A90D9?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyem0tMiAxNWwtNS01IDEuNDEtMS40MUwxMCAxNC4xN2w3LjU5LTcuNTlMMTkgOGwtOSA5eiIvPjwvc3ZnPg==)](https://openwebui.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tools](https://img.shields.io/badge/tools-6-blueviolet?style=flat-square)](https://openwebui.com/u/ichrist)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen?style=flat-square)](https://github.com)
[![Made with Claude](https://img.shields.io/badge/made%20with-Claude%20%E2%9D%A4-FF6B35?style=flat-square)](https://claude.ai)

> 🛒 **One-click install → [openwebui.com/u/ichrist](https://openwebui.com/u/ichrist)**

</div>

---

## 🗺️ Quick Navigation

| # | Tool | Best for |
|---|------|----------|
| 1 | [🎬 Jellyfin Media Player](#-jellyfin-media-player) | Stream movies, TV & music from your own server |
| 2 | [🧩 Ask User](#-ask-user) | Gather structured input before your AI starts writing |
| 3 | [🎭 Persona Studio](#-persona-studio) | Instantly switch your AI's personality & tone |
| 4 | [📖 Wikipedia](#-wikipedia) | Instant encyclopedia lookups in 20+ languages |
| 5 | [🌌 Omniscient Orchestrator](#-omniscient-orchestrator) | Multi-stage AI workflow with strategy selection |
| 6 | [😂 Joke Tool](#-joke-tool) | 300+ programmer jokes on demand |

---

## 🎬 Jellyfin Media Player

> **Stream your entire Jellyfin library inside Open WebUI** — with a cinematic embedded player, subtitle support, quality presets, and album art.

<img width="1148" alt="Jellyfin Media Player screenshot" src="https://github.com/user-attachments/assets/eaf06d46-7659-4cb4-9d47-e6754d935b19" />

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

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

### ⚙️ Setup (3 steps)

1. Create a **restricted Jellyfin user** (playback-only, no admin or delete permissions)
2. Generate an API key: **Dashboard → API Keys → +**
3. Paste both into the tool valves: `JELLYFIN_HOST` and `JELLYFIN_API_KEY`

### 🗣️ Example prompts

```
play Inception
play Breaking Bad S03E10
play music Bohemian Rhapsody
random comedy movie
tell me about Interstellar
what was recently added
```

---

## 🧩 Ask User

> **Replicate Claude's "ask follow-up questions before acting" behaviour** — collect structured multi-step input through sequential popup dialogs before your AI writes a single word.

<img width="1301" alt="Ask User screenshot" src="https://github.com/user-attachments/assets/48ba79cb-38d4-4fe7-8845-0750d3409486" />

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

### ✨ What it does

Ever notice how Claude pauses, asks you a few targeted questions, then produces something far more on-point? This tool brings that exact behaviour to Open WebUI. The LLM can ask 1–5 structured questions upfront — each in its own popup with a progress indicator — before committing to a response. No more back-and-forth re-prompting.

| Feature | Detail |
|---------|--------|
| 📋 Up to 5 questions | Defined upfront — no infinite loops |
| 🪟 One popup per question | Clear progress indicator: `Question 2 of 4` |
| 📦 Structured output | All answers returned together before the LLM acts |
| 🔒 Bounded & predictable | The LLM cannot keep asking — it must proceed |
| 🔑 No dependencies | Standard library only |

### 🗣️ Best for

```
"Write me a cover letter"    → gathers: role, company, tone, key achievements
"Plan my project"            → gathers: deadline, team size, stack, goals
"Draft a cold email"         → gathers: recipient, offer, call to action
"Create a workout plan"      → gathers: goal, equipment, days per week
```

> ⚠️ **Requires** Open WebUI with interactive input modal support. Won't work in headless or API-only environments.

---

## 🎭 Persona Studio

> **Instantly reshape how your AI thinks and communicates** — dozens of crafted personas across multiple categories, plus a fully custom option.

<img width="1250" alt="Persona Studio screenshot" src="https://github.com/user-attachments/assets/38035bc1-a629-44a3-8130-dd81275f8af9" />

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

### ✨ What it does

Stop editing system prompts manually. Persona Studio gives you an interactive popup browser with categorised personas — each with a distinct tone, voice, quirks, and style. Switch mid-conversation in one message.

| Feature | Detail |
|---------|--------|
| 🎯 Interactive browser | Categorised popup UI — pick and apply in one click |
| 😎 Dozens of personas | Technical · Creative · Professional · Playful · and more |
| ✍️ Custom option | Define any personality from scratch |
| 🚀 Instant switch | No re-prompting, no manual system prompt editing |

### 🗣️ Example prompts

```
Switch to a different persona
I want you to respond like a senior engineer doing code review
Change your communication style to casual and funny
Set a custom persona: you are a brutally honest editor
```

---

## 📖 Wikipedia

> **Instant encyclopedia lookups** — smart search, section-aware summaries, disambiguation handling, and 20+ languages. Zero config required.

<img width="1109" alt="Wikipedia tool screenshot" src="https://github.com/user-attachments/assets/6e88aac8-15b1-4d18-b04d-383cfeaf936b" />

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

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

### 🗣️ Example prompts

```
Who is Ada Lovelace?
Explain how black holes work
Tell me everything about the Apollo program
Search Wikipedia for quantum entanglement
¿Quién es Simón Bolívar?
```

### 🌍 Supported languages

`en` `fr` `de` `es` `it` `pt` `nl` `sv` `uk` `fa` `ja` `zh` `ar` `ko` `ru` `pl` `tr` `he` `vi` `id`

---

## 🌌 Omniscient Orchestrator

> **Stop getting generic answers.** Make your LLM pause, ask the right questions, pick a strategy — then produce something genuinely tailored to your goal.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

### ✨ What it does

Most LLMs dive straight into an answer, missing context that would have changed everything. The Orchestrator forces a structured 4-phase workflow: understand → clarify → strategise → execute. The result is dramatically more useful output, especially for complex or open-ended tasks.

| Phase | What happens |
|-------|-------------|
| 🔹 Phase 1 — Analyse | Maps your request, identifies gaps and ambiguities |
| 🔹 Phase 2 — Clarify | Asks up to 3 targeted questions via input modals |
| 🔹 Phase 3 — Strategise | Presents 3 distinct execution approaches to choose from |
| 🔹 Phase 4 — Execute | Generates output with all context locked in |

**Built-in guardrails:** max 3 questions, always skippable, always moves forward — no infinite loops.

### 🗣️ Best for

```
Writing long-form content (articles, landing pages, scripts, reports)
Brainstorming with structured creative options
Planning projects or technical roadmaps
Any prompt where you'd normally need 3 rounds of re-prompting
```

> ⚠️ **Requires** Open WebUI with interactive input modal support. Won't work in headless or API-only environments.

---

## 😂 Joke Tool

> **Give your AI a sense of humour** — 300+ curated programmer jokes, live API fetching, and batch delivery on demand.

<img width="1630" alt="Joke Tool screenshot" src="https://github.com/user-attachments/assets/7ea6a8c9-0ca7-469d-a456-53c71ca26472" />

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

### ✨ What it does

Because sometimes you need a break. A carefully curated vault of programmer humor — Git puns, deep-cut coding jokes, and classic one-liners — plus live fetching from `jokeapi.dev` when you want something fresh.

| Feature | Detail |
|---------|--------|
| 🃏 300+ jokes | Curated vault: Git puns, coding humor, dev classics |
| 🌐 Live mode | Fetches fresh jokes from `jokeapi.dev` on request |
| 🔢 Batch support | Ask for 1 joke or a specific number |
| 🛡️ Offline-safe | Always falls back to internal library if API is down |

### 🗣️ Example prompts

```
Tell me a joke
Give me 3 fresh jokes from the internet
Hit me with a random Git pun
Tell me 5 programming jokes
```

---

## 🛠️ Installation

All tools install the same way — takes about 30 seconds.

1. Open **Workspace → Tools** in Open WebUI
2. Click **➕ Add Tool**
3. Paste the script, **or** use one-click import from the marketplace
4. Click **Save**
5. Enable it in any chat via the **🔧 Tools** toggle

> 💡 **Tip:** Enable only the tools you need in each chat — keeping the tool list focused helps the LLM pick the right one every time.

---

## 📜 License

All tools are released under the **MIT License** — free to use, fork, modify, and publish.

---

## 💡 Inspiration & Credits

This project wouldn't exist without **[Haervwe's open-webui-tools](https://github.com/Haervwe/open-webui-tools)**.

Haervwe's collection is what got me building my own tools in the first place — seeing what was possible sparked the whole thing. We've also collaborated directly, which shaped several ideas here. If you're looking for even more great Open WebUI tools, his repo is absolutely worth a visit.

> 🙏 Big thanks to [@Haervwe](https://github.com/Haervwe) for the inspiration and the collaboration.

---

<div align="center">

Made with ☕ by [ichrist](https://openwebui.com/u/ichrist) · with help from [Claude](https://claude.ai)

⭐ If these tools save you time, a star goes a long way!

</div>
