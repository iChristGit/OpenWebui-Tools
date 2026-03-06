# 🧰 Open WebUI Custom Tools

A collection of 6 tools for [Open WebUI](https://openwebui.com) — from media streaming to structured AI workflows. All tools are free, open source, and available on the marketplace with one-click import.

> 🛒 **[Browse & install all tools → openwebui.com/u/ichrist](https://openwebui.com/u/ichrist)**

---

## 📦 Tools

| # | Tool | What it does |
|---|------|-------------|
| 1 | [🎬 Jellyfin Media Player](#-jellyfin-media-player) | Stream movies, TV & music from your Jellyfin server |
| 2 | [📖 Wikipedia](#-wikipedia) | Instant encyclopedia lookups in 20+ languages |
| 3 | [🌌 Omniscient Orchestrator](#-omniscient-orchestrator) | Multi-stage AI workflow with clarification & strategy selection |
| 4 | [😂 Joke Tool](#-joke-tool) | 300+ programmer jokes + live API fetching |
| 5 | [🎭 Persona Studio](#-persona-studio) | Dynamically switch your AI's personality on the fly |
| 6 | [🧩 Ask User](#-ask-user) | Collect structured multi-step user input via popups |

---

## 🎬 Jellyfin Media Player

> Stream your entire Jellyfin library inside Open WebUI with a cinematic embedded player.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

#### ✨ Features
- 🎬 Stream any movie, TV episode, or music track
- 📺 Episode lookup with `S01E01` / `1x01` notation
- 🎵 Music player with waveform, album art & EQ animation
- 🎲 Random picks with optional genre filter
- 💬 Subtitle dropdown — all available language tracks
- 📐 Quality presets: Original, 4K, 1080p, 720p, 480p, 360p
- ⬇️ Download button on every player
- 🔎 Search library or get rich media info without opening a player

#### ⚙️ Setup
1. Create a restricted Jellyfin user (playback only, no admin/delete)
2. Generate an API key: **Dashboard → API Keys → +**
3. Set `JELLYFIN_HOST` and `JELLYFIN_API_KEY` in the tool valves

#### 🗣️ Example prompts
```
play Inception
play Breaking Bad S03E10
play music Bohemian Rhapsody
random comedy movie
tell me about Interstellar
what was recently added
```

---

## 📖 Wikipedia

> Give your LLM instant access to the world's largest encyclopedia — no API key, no setup.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

#### ✨ Features
- 🔍 Smart search — natural language queries work fine
- 📏 3 detail levels — `brief` · `standard` · `full` — the LLM picks automatically
- 🗂️ Section-aware — structured summaries, not walls of text
- ⚠️ Disambiguation handling — shows options when a title is ambiguous
- 🌍 20+ languages — just write in your language or ask for one
- 🔗 Always cites the source URL
- 🔑 Zero config — uses the free public MediaWiki API

#### 🗣️ Example prompts
```
Who is Ada Lovelace?
Explain how black holes work
Tell me everything about the Apollo program
Search Wikipedia for quantum entanglement
Quién es Simón Bolívar?
```

#### 🌍 Supported languages
`en` `fr` `de` `es` `it` `pt` `nl` `sv` `uk` `fa` `ja` `zh` `ar` `ko` `ru` `pl` `tr` `he` `vi` `id`

---

## 🌌 Omniscient Orchestrator

> Stop getting generic answers. Make your LLM pause, ask the right questions, and pick a strategy — before writing a single word.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

#### ✨ Features
- 🔹 **Phase 1** — Analyzes your request and maps what's ambiguous
- 🔹 **Phase 2** — Asks up to 3 targeted clarification questions via input modals
- 🔹 **Phase 3** — Presents 3 distinct execution strategies for you to choose
- 🔹 **Phase 4** — Generates output with all context locked in
- 🛡️ Built-in guardrails — max 3 questions, skippable, always moves forward
- 🔑 No external APIs — standard library only

#### 🗣️ Best for
```
Writing long-form content (articles, landing pages, scripts)
Brainstorming with structured options
Planning projects or roadmaps
Any prompt where you'd normally re-prompt 3 times
```

> ⚠️ Requires Open WebUI with interactive input modal support. Won't work in headless/API-only environments.

---

## 😂 Joke Tool

> Give your AI a massive library of programmer humor for when things get too serious.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

#### ✨ Features
- 🃏 **300+ curated jokes** — Git puns, deep-cut coding humor, and more
- 🌐 **Live mode** — fetches fresh jokes from `jokeapi.dev` on request
- 🔢 **Batch support** — ask for 1 joke or a specific number
- 📊 Status updates showing vault vs. internet mode
- 🛡️ Offline-safe — always falls back to internal library

#### 🗣️ Example prompts
```
Tell me a joke
Give me 3 fresh jokes from the internet
Hit me with a random git pun
```

---

## 🎭 Persona Studio

> Dynamically switch how your AI thinks and talks — dozens of personas across multiple categories.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

#### ✨ Features
- 🎯 Interactive popup UI with categorized persona browser
- 😎 Dozens of crafted personas — each with unique tone, voice, quirks, and style
- ✍️ Custom persona option — define absolutely anything you want
- 🚀 Instant switch — no re-prompting or manual system prompt editing

#### 🗣️ Example prompts
```
Switch to a different persona
I want you to act differently
Change your communication style
Set a custom persona
```

---

## 🧩 Ask User

> Collect structured multi-step user input through sequential popup dialogs in a single, controlled tool call.

**[→ Install from marketplace](https://openwebui.com/u/ichrist)**

#### ✨ Features
- 📋 Accepts 1–5 questions defined upfront — no infinite loops
- 🪟 One popup per question with a clear progress indicator (e.g. `Question 2 of 4`)
- 📦 Returns all responses together as a structured string
- 🔒 Bounded, predictable, atomic — the LLM cannot ask unlimited questions
- 🔑 No external dependencies

#### 🗣️ Best for
```
Gathering context before generating a document
Multi-field form-style input flows
Any task where the LLM needs several pieces of info before acting
```

> ⚠️ Requires Open WebUI with interactive input modal support.

---

## 🛠️ Installation (any tool)

1. Go to **Workspace → Tools** in Open WebUI
2. Click **➕ Add Tool**
3. Either paste the script contents, or use the one-click import from the marketplace
4. Hit **Save**
5. Enable it in any chat via the **🔧 Tools** button

---

## 📜 License

All tools are released under the **MIT License** — free to use, fork, and publish.

---

> Made with ☕ by [ichrist](https://openwebui.com/u/ichrist)
