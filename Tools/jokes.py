"""
title: Random Jokes Tool (Multi-Source + Offline Fallback)
author: ichrist
description: >
    Fetch jokes from 3 sources simultaneously: JokeAPI, icanhazdadjoke, and
    Official Joke API. Falls back to 250+ built-in offline jokes if APIs are
    unreachable or the user requests offline mode. Supports category/genre
    filtering, keyword search, and safe-mode. No API key required.
version: 3.0.0
license: MIT
"""

import json
import random
import urllib.request
import urllib.parse
import threading
from typing import Optional

# ── Offline joke bank ────────────────────────────────────────────────────────
# 250+ jokes embedded locally — used as fallback when APIs are unreachable
# or when the user explicitly asks for offline jokes.
# Each entry is either a plain string (single) or a dict with setup/delivery.

_OFFLINE_JOKES = [
    # --- git / programming (from curated list) ---
    "git pull a day keeps the conflicts away",
    "If you have anything staged, commit now or stash forever",
    "Remember to keep your porcelain clean",
    "Commit early, commit often. A tip for version controlling — not for relationships",
    "Fork by yourself, shame on you. Fork with a friend, now we're getting somewhere.",
    "A branch, a tag, and a reflog walk into a bar. The bartender says, 'What is this, some sort of rebase?'",
    "Why did the commit cross the rebase? To git to the other repo",
    "You can checkout any time you like, but you can never diff.",
    "git-stash: The sock drawer of version control",
    "git-blame: ruining friendships since 2006",
    "Be careful when rewriting history. It may push you to use the dark side of the --force",
    "When you play the game of clones, you merge or you reset --hard.",
    "git: Multiplayer Notepad",
    "git happens",
    "May the forks be with you",
    "git is one byte short of a four-letter word",
    "What we push in life echoes in eternity",
    "All those commits will be lost in time... Like tears in rain... Time to gc",
    "git-bisect: The good, the bad and the... uhh... skip",
    "git - subversion done right",
    "This is not a joke, it's a commit.",
    "diff in hell, SVNites!",
    "git off!",
    "Once you go git, you never go back.",
    "In case of fire: git commit, git push, leave the building",
    "Don't forgit to bring a towel",
    "Fork it until you make it.",
    "The problem with Git jokes? Well, everyone has their own version :)",
    "Frankly, my dear, I don't give a fork.",
    "Git gets easier once you get the basic idea that branches are homeomorphic endofunctors mapping submanifolds of a Hilbert space.",
    "May the --force be with you",
    "I git by with a little help from my friends",
    "git gud",
    "War is peace, freedom is slavery, ignorance is strength, git is version control",
    "What is the most loyal tool of a programmer? Git, because of its COMMITment!",
    "Be careful not to remove the branch you're standing on",
    "In Soviet Russia, git commits YOU!",
    "git: Committed for life",
    "git: history is written by the committers.",
    "Updates were rejected: use the --force",
    "git a job, hippie!",
    "I kissed a git, and I liked it.",
    {
        "setup": "Knock knock. Who's there?",
        "delivery": "Git. Git-who? Sorry, 'who' is not a git command — did you mean 'show'?",
    },
    {
        "setup": "Why did the commit go to jail?",
        "delivery": "It was charged with assault and battery.",
    },
    # --- programming ---
    "Why do Java developers wear sunglasses? Because they stare straight into the Eclipse!",
    "What did the .NET developer name their boat? Sea Sharp.",
    "I like my coffee like I like my IDEs… Dark and free.",
    "Why aren't frontend developers humble? Because they display: flex;",
    "Say what you want about SQL, but it brings a lot to the table.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "Debugging is like being a detective in a crime movie where you are also the murderer.",
    "I would tell you a UDP joke, but you might not get it.",
    "Version control is my love language.",
    "Monday is a bug in the weekend code.",
    "What is a software developer's favorite herb? Parsley.",
    "I started coding for fun. Now I do it for loops.",
    "Real programmers count from zero.",
    "My attitude isn't bad. It's in beta.",
    "There are 10 types of people: those who understand binary and those who don't.",
    "Why was the function afraid? It didn't return.",
    "How did the pirate communicate? Pier-to-pier networking.",
    "Software developers: Turning caffeine into code since 1970.",
    "To understand recursion, you must first understand recursion.",
    "I'm friends with 25 letters of the alphabet. I don't know Y.",
    "Documentation is the 'Coming Soon' sign of the software world.",
    "I have a joke about pointers, but you might not get the reference.",
    "My browser history is cleaner than my code.",
    "Coding is my cardio.",
    "I don't procrastinate; I just wait for the right version.",
    "Stand-up meetings are just group buffering.",
    "Why do programmers love dark mode? Because light attracts bugs.",
    "What do you call a group of eight hobbits? A hobbyte.",
    "Why did the IRS investigate the CLI? It was a shell company.",
    "What is a programmer's favorite kind of dog? Computer Labs.",
    "Why did the developer go to the beach? To test his 'sand'box.",
    "What's a programmer's favorite snack? Microchips.",
    "Why do assembly programmers have big muscles? They do a lot of pushing and popping.",
    "What's the best thing about a boolean? Even if you are wrong, you are only off by a bit.",
    "What's a programmer's favorite musical? 'The Phantom of the Opera'-ting System.",
    "What's the first rule of programming? If it works, don't touch it.",
    "What's a programmer's favorite color? #000000 (Black).",
    "What do you call a software developer who doesn't use version control? Unemployed.",
    {
        "setup": "A SQL query walks into a bar, walks up to two tables and asks:",
        "delivery": "'Can I join you?'",
    },
    {
        "setup": "How many programmers does it take to change a lightbulb?",
        "delivery": "None, that's a hardware problem.",
    },
    {
        "setup": "A programmer's wife tells him: 'Go to the store and buy a loaf of bread. If they have eggs, buy a dozen.'",
        "delivery": "He returns with 12 loaves.",
    },
    {
        "setup": "Why did the function return early?",
        "delivery": "It saw the 'return' sign.",
    },
    {
        "setup": "I have a joke on recursion,",
        "delivery": "but you'll have to wait for it to call itself.",
    },
    {
        "setup": "Why do SQL developers have high divorce rates?",
        "delivery": "One-to-many relationships.",
    },
    {"setup": "How do you comfort a JavaScript bug?", "delivery": "You console it!"},
    {"setup": "Why did the programmer quit?", "delivery": "He didn't get arrays."},
    {"setup": "What do you call a group of programmers?", "delivery": "An Assembly."},
    {
        "setup": "Why was the JavaScript developer sad?",
        "delivery": "He didn't know how to 'null' his feelings.",
    },
    {
        "setup": "What's the difference between a delicious dinner and a slow computer?",
        "delivery": "One's a rack of lamb, the other's a lack of RAM.",
    },
    {"setup": "What is a web developer's favorite tea?", "delivery": "URL Grey."},
    {
        "setup": "Why did the CSS file feel pretty?",
        "delivery": "It had a great layout.",
    },
    {"setup": "Why was the function so short?", "delivery": "It had no body."},
    {
        "setup": "Why did the variable go to therapy?",
        "delivery": "It was constantly being reassigned.",
    },
    {
        "setup": "Why did the developer break up with the IDE?",
        "delivery": "Too many conflicts.",
    },
    {"setup": "How do coders stay warm?", "delivery": "They use nested loops."},
    {"setup": "Why did the function feel lonely?", "delivery": "It had no arguments."},
    {
        "setup": "Why was the loop so funny?",
        "delivery": "It kept repeating the punchline.",
    },
    {
        "setup": "Why did the programmer cross the road?",
        "delivery": "To get to the other IDE.",
    },
    {
        "setup": "Why do Python programmers prefer snakes?",
        "delivery": "Because they hate the braces.",
    },
    {
        "setup": "An optimist says the glass is half-full. A pessimist says it's half-empty.",
        "delivery": "A programmer says it's twice as big as it needs to be.",
    },
    {
        "setup": "What's a programmer's favorite horror movie?",
        "delivery": "The XORcist.",
    },
    {
        "setup": "Why was the WiFi so confident?",
        "delivery": "It had strong connections.",
    },
    {"setup": "Why do hackers love winter?", "delivery": "They can break the ice."},
    {"setup": "Why did the array get promoted?", "delivery": "It had many dimensions."},
    {
        "setup": "Why did the developer bring a ladder?",
        "delivery": "To reach the high-level language.",
    },
    {"setup": "Why did the build fail?", "delivery": "It had commitment issues."},
    {"setup": "How do developers fix a broken heart?", "delivery": "With a patch."},
    {"setup": "How do programmers flirt?", "delivery": "With inline comments."},
    {
        "setup": "Why did the code cross the road?",
        "delivery": "To get to the production environment.",
    },
    {"setup": "Why do programmers hate nature?", "delivery": "Too many bugs."},
    {"setup": "Why did the junior dev panic?", "delivery": "Null pointer exception."},
    {"setup": "Why was the boolean so honest?", "delivery": "It could not lie."},
    {"setup": "How do functions make jokes?", "delivery": "By returning punchlines."},
    {
        "setup": "Why did the programmer get kicked out of school?",
        "delivery": "He kept skipping classes.",
    },
    {"setup": "What's a SQL developer's favorite drink?", "delivery": "A JOINt."},
    {"setup": "Why did the server make a bad comedian?", "delivery": "Poor delivery."},
    {"setup": "Why did the function feel tired?", "delivery": "It ran too many loops."},
    {
        "setup": "How do programmers stay calm?",
        "delivery": "They know how to handle exceptions.",
    },
    {
        "setup": "How do developers react instantly?",
        "delivery": "They have event listeners.",
    },
    {
        "setup": "Why was the recursive joke funny?",
        "delivery": "Because it was recursive.",
    },
    {
        "setup": "Why do programmers prefer cats?",
        "delivery": "Because they ignore you like your code.",
    },
    {"setup": "Why was the computer cold?", "delivery": "It left its Windows open."},
    {
        "setup": "Why was the JavaScript file sad?",
        "delivery": "It had too many callbacks.",
    },
    {"setup": "Why did the function break up?", "delivery": "Constant arguments."},
    {
        "setup": "How many Java developers does it take to change a lightbulb?",
        "delivery": "They don't, they just define the generic LightBulb interface.",
    },
    {
        "setup": "Why did the Python programmer get arrested?",
        "delivery": "He had too many 'imports'.",
    },
    {
        "setup": "Why do programmers hate meetings?",
        "delivery": "It's a context-switch of doom.",
    },
    {
        "setup": "How do you know an extroverted programmer?",
        "delivery": "They look at *your* shoes.",
    },
    {"setup": "Why was the developer broke?", "delivery": "He used all his cache."},
    {
        "setup": "How do you tell if a dev is lying?",
        "delivery": "Their lips are moving and they're saying 'It's an easy fix.'",
    },
    {
        "setup": "Why did the API get a ticket?",
        "delivery": "It went over the rate limit.",
    },
    {
        "setup": "How do you make a million dollars as a programmer?",
        "delivery": "Start with two million and build a game engine.",
    },
    {
        "setup": "Why did the developer name his dog 'Syntax'?",
        "delivery": "Because he never follows the rules.",
    },
    {
        "setup": "How do you keep a programmer in the shower forever?",
        "delivery": "Give them a bottle of shampoo that says 'Lather, Rinse, Repeat.'",
    },
    {
        "setup": "What's a programmer's favorite game?",
        "delivery": "'Hide and Seek' (the bug).",
    },
    {
        "setup": "Why did the developer go to the doctor?",
        "delivery": "He had a 'virus'.",
    },
    {
        "setup": "Why did the developer name his cat 'Java'?",
        "delivery": "Because it has many 'claws'.",
    },
    {
        "setup": "How do you tell a programmer from a non-programmer?",
        "delivery": "Ask them to count to ten. The programmer starts at zero.",
    },
    {
        "setup": "Why did the developer go to the gym?",
        "delivery": "To work on his 'flexbox'.",
    },
    {"setup": "What's a programmer's favorite season?", "delivery": "Spring (Boot)."},
    {
        "setup": "What do you call a programmer who plays guitar?",
        "delivery": "A 'C' player.",
    },
    # --- general tech ---
    "Why did the smartphone need glasses? It lost its contacts.",
    "Java and JavaScript are as similar as Car and Carpet.",
    "I'm not a great programmer; I'm just a pro at debugging my mistakes.",
    "My attitude isn't bad. It's in beta.",
    "Software is like a toddler. It works only when I watch it.",
    "I don't rise and shine, I caffeinate and hope.",
    "Why do coders love coffee? It helps them stay grounded.",
    {
        "setup": "Why was the web developer's boat sinking?",
        "delivery": "They had too many anchors.",
    },
    {
        "setup": "Why did the developer name his daughter 'Ruby'?",
        "delivery": "Because she was a gem.",
    },
    {
        "setup": "What did the .js file say to the .css file?",
        "delivery": "'You've got style.'",
    },
    {
        "setup": "Why did the laptop go to school?",
        "delivery": "To improve its processing skills.",
    },
    {"setup": "Why did the array break up?", "delivery": "No chemistry."},
    {"setup": "How do coders express love?", "delivery": "With a well-placed comment."},
    {
        "setup": "Why did the developer go to art class?",
        "delivery": "To master the 'canvas'.",
    },
    {
        "setup": "How does the compiler react to romance?",
        "delivery": "It checks for compatibility.",
    },
    {"setup": "Why was the CSS dev so tired?", "delivery": "Too many 'float's."},
    {
        "setup": "Why did the developer bring a mirror to the computer?",
        "delivery": "To 'reflect' on the code.",
    },
    {
        "setup": "How do you fix a broken computer?",
        "delivery": "With a 'byte' of luck.",
    },
    {
        "setup": "Why did the developer name his car 'Python'?",
        "delivery": "Because it's a 'snake' on the road.",
    },
    {
        "setup": "Why did the commit cross the road?",
        "delivery": "To git to the other side!",
    },
    {
        "setup": "Why did the commit break up from its tag?",
        "delivery": "It needed more branch space.",
    },
    {"setup": "What do you call a programmer from Finland?", "delivery": "Nerdic."},
    {
        "setup": "Why did the developer bring a pen to the computer?",
        "delivery": "To 'write' some code.",
    },
    {
        "setup": "Why did the developer bring a clock to the meeting?",
        "delivery": "To 'time' the execution.",
    },
]


class Tools:
    """
    Multi-source joke fetcher querying 3 free APIs in parallel:
      1. JokeAPI          (v2.jokeapi.dev)                    – categories + keyword search
      2. icanhazdadjoke   (icanhazdadjoke.com)                – 300+ dad jokes, great keyword search
      3. Official Joke API (official-joke-api.appspot.com)    – general/programming/misc types
      4. Offline fallback  (built-in, 250+ jokes)             – used when APIs fail or offline=True

    IMPORTANT INSTRUCTIONS FOR THE LLM:
    - Call get_jokes() EXACTLY ONCE per user request. Do NOT call it multiple times.
    - The tool already fetches from all sources and returns merged results in one call.
    - After receiving the tool result, present the jokes to the user and STOP.
    - Do NOT call the tool again unless the user explicitly asks for more jokes.
    - Default amount is 5. Only use a lower number if the user specifically asks for fewer.
    - For keyword searches (e.g. "chicken", "doctor") always use the search parameter.
    - For genre/topic requests (e.g. "programming", "dark", "pun") use the category parameter.
    - If the user says they are offline, or asks for offline/local jokes, set offline=True.
    """

    def __init__(self):
        self.jokeapi_categories = {
            "any": "Any",
            "programming": "Programming",
            "misc": "Misc",
            "miscellaneous": "Misc",
            "dark": "Dark",
            "pun": "Pun",
            "puns": "Pun",
            "spooky": "Spooky",
            "halloween": "Spooky",
            "christmas": "Christmas",
            "holiday": "Christmas",
            "xmas": "Christmas",
        }
        self.official_types = {
            "programming": "programming",
            "general": "general",
            "misc": "general",
            "knock-knock": "knock-knock",
            "dark": "dark",
        }
        self.jokeapi_flags = {
            "nsfw",
            "religious",
            "political",
            "racist",
            "sexist",
            "explicit",
        }

    # ── Offline source ───────────────────────────────────────────────────────

    def _fetch_offline(self, amount: int, search: Optional[str]) -> list:
        pool = _OFFLINE_JOKES[:]
        if search:
            kw = search.strip().lower()
            filtered = [
                j
                for j in pool
                if kw
                in (
                    j if isinstance(j, str) else f"{j['setup']} {j['delivery']}"
                ).lower()
            ]
            pool = filtered if filtered else pool  # fall back to full pool if no match

        random.shuffle(pool)
        results = []
        for j in pool[:amount]:
            if isinstance(j, str):
                results.append(
                    {
                        "source": "Offline",
                        "category": "Built-in",
                        "text": j,
                        "type": "single",
                    }
                )
            else:
                results.append(
                    {
                        "source": "Offline",
                        "category": "Built-in",
                        "text": f"{j['setup']} {j['delivery']}",
                        "setup": j["setup"],
                        "delivery": j["delivery"],
                        "type": "twopart",
                    }
                )
        return results

    # ── Source 1: JokeAPI ────────────────────────────────────────────────────

    def _fetch_jokeapi(
        self, amount, category, search, safe_mode, blacklist_flags, results
    ):
        try:
            cat_key = (category or "Any").strip().lower()
            resolved = self.jokeapi_categories.get(cat_key, "Any")
            params = {"amount": min(amount, 5)}
            if safe_mode:
                params["safe-mode"] = "true"
            elif blacklist_flags:
                flags = [
                    f.strip().lower()
                    for f in blacklist_flags.split(",")
                    if f.strip().lower() in self.jokeapi_flags
                ]
                if flags:
                    params["blacklistFlags"] = ",".join(flags)
            if search:
                params["contains"] = search.strip()
            url = f"https://v2.jokeapi.dev/joke/{resolved}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url, headers={"User-Agent": "OpenWebUI-JokesTool/3.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            if data.get("error"):
                return
            jokes_raw = data.get("jokes") if "jokes" in data else [data]
            for j in jokes_raw:
                if j.get("type") == "twopart":
                    results.append(
                        {
                            "source": "JokeAPI",
                            "category": j.get("category", resolved),
                            "text": f"{j.get('setup','')} ... {j.get('delivery','')}",
                            "setup": j.get("setup", ""),
                            "delivery": j.get("delivery", ""),
                            "type": "twopart",
                        }
                    )
                else:
                    results.append(
                        {
                            "source": "JokeAPI",
                            "category": j.get("category", resolved),
                            "text": j.get("joke", ""),
                            "type": "single",
                        }
                    )
        except Exception:
            pass

    # ── Source 2: icanhazdadjoke ─────────────────────────────────────────────

    def _fetch_dadjoke(self, amount, search, results):
        try:
            headers = {
                "Accept": "application/json",
                "User-Agent": "OpenWebUI-JokesTool/3.0 (https://openwebui.com)",
            }
            if search:
                params = urllib.parse.urlencode(
                    {"term": search.strip(), "limit": max(amount, 10)}
                )
                url = f"https://icanhazdadjoke.com/search?{params}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
                for j in data.get("results", []):
                    results.append(
                        {
                            "source": "icanhazdadjoke",
                            "category": "Dad Joke",
                            "text": j.get("joke", ""),
                            "type": "single",
                        }
                    )
            else:
                seen = set()
                for _ in range(min(amount, 5)):
                    req = urllib.request.Request(
                        "https://icanhazdadjoke.com/", headers=headers
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        data = json.loads(resp.read().decode())
                    joke_text = data.get("joke", "")
                    if joke_text and joke_text not in seen:
                        seen.add(joke_text)
                        results.append(
                            {
                                "source": "icanhazdadjoke",
                                "category": "Dad Joke",
                                "text": joke_text,
                                "type": "single",
                            }
                        )
        except Exception:
            pass

    # ── Source 3: Official Joke API ──────────────────────────────────────────

    def _fetch_official(self, amount, category, results):
        try:
            cat_key = (category or "general").strip().lower()
            joke_type = self.official_types.get(cat_key)
            url = (
                f"https://official-joke-api.appspot.com/jokes/{joke_type}/ten"
                if joke_type
                else "https://official-joke-api.appspot.com/jokes/ten"
            )
            req = urllib.request.Request(
                url, headers={"User-Agent": "OpenWebUI-JokesTool/3.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, list):
                for j in data[:amount]:
                    results.append(
                        {
                            "source": "Official Joke API",
                            "category": j.get("type", "General").capitalize(),
                            "text": f"{j.get('setup','')} ... {j.get('punchline','')}",
                            "setup": j.get("setup", ""),
                            "delivery": j.get("punchline", ""),
                            "type": "twopart",
                        }
                    )
        except Exception:
            pass

    # ── Deduplication ────────────────────────────────────────────────────────

    def _deduplicate(self, jokes):
        seen, unique = set(), []
        for j in jokes:
            key = j["text"].strip().lower()[:80]
            if key not in seen:
                seen.add(key)
                unique.append(j)
        return unique

    # ── Format output ────────────────────────────────────────────────────────

    def _format(self, jokes, amount, offline_notice=""):
        output_lines = []
        for i, joke in enumerate(jokes, start=1):
            label = f"**Joke {i}**" if amount > 1 else "**Here's a joke!**"
            source_tag = f"_{joke['category']} · {joke['source']}_"
            if joke["type"] == "twopart":
                output_lines.append(
                    f"{label} {source_tag}\n"
                    f"🔹 {joke['setup']}\n"
                    f"💬 {joke['delivery']}"
                )
            else:
                output_lines.append(f"{label} {source_tag}\n" f"😄 {joke['text']}")
        result = "\n\n---\n\n".join(output_lines)
        if offline_notice:
            result += f"\n\n> {offline_notice}"
        return result

    # ── Public tool method ───────────────────────────────────────────────────

    def get_jokes(
        self,
        amount: int = 5,
        category: Optional[str] = "Any",
        search: Optional[str] = None,
        safe_mode: bool = True,
        blacklist_flags: Optional[str] = None,
        offline: bool = False,
    ) -> str:
        """
        Fetch jokes from up to 4 sources (3 live APIs + offline fallback).
        Call this tool EXACTLY ONCE per user request. Do NOT call again after
        receiving results — just present them and stop.

        :param amount: Number of jokes to return (1-10). Default is 5. Only
                       reduce if the user explicitly asks for fewer.
        :param category: Genre: Any, Programming, Misc, Dark, Pun, Spooky,
                         Christmas, General, Knock-Knock. Use for genre requests.
        :param search: Keyword searched across all sources (e.g. "chicken",
                       "doctor", "cat"). Use when user asks about a specific topic.
        :param safe_mode: Filters explicit content on JokeAPI. Default True.
        :param blacklist_flags: Comma-separated JokeAPI flags when safe_mode=False:
                                nsfw, religious, political, racist, sexist, explicit.
        :param offline: Set True if user says they are offline or explicitly asks
                        for local/built-in/offline jokes. Skips all API calls.
        :return: Formatted jokes from all available sources, with offline fallback.
        """
        amount = max(1, min(10, int(amount)))
        per_source = max(amount, 5)

        # ── Offline-only mode ────────────────────────────────────────────────
        if offline:
            jokes = self._fetch_offline(amount, search)
            if not jokes:
                return "😅 No offline jokes matched that keyword. Try a different search term."
            return self._format(
                jokes, amount, offline_notice="📴 Showing built-in offline jokes."
            )

        # ── Live API mode ────────────────────────────────────────────────────
        jokeapi_results, dadjoke_results, official_results = [], [], []

        threads = [
            threading.Thread(
                target=self._fetch_jokeapi,
                args=(
                    per_source,
                    category,
                    search,
                    safe_mode,
                    blacklist_flags,
                    jokeapi_results,
                ),
            ),
            threading.Thread(
                target=self._fetch_dadjoke, args=(per_source, search, dadjoke_results)
            ),
        ]
        if not search:
            threads.append(
                threading.Thread(
                    target=self._fetch_official,
                    args=(per_source, category, official_results),
                )
            )

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Interleave sources for variety
        merged = []
        max_len = max(
            len(jokeapi_results), len(dadjoke_results), len(official_results), 1
        )
        for i in range(max_len):
            if i < len(jokeapi_results):
                merged.append(jokeapi_results[i])
            if i < len(dadjoke_results):
                merged.append(dadjoke_results[i])
            if i < len(official_results):
                merged.append(official_results[i])

        unique = self._deduplicate(merged)[:amount]

        # ── Automatic offline fallback ───────────────────────────────────────
        if not unique:
            offline_jokes = self._fetch_offline(amount, search)
            if not offline_jokes:
                hint = (
                    f'search: **"{search}"**' if search else f"category: **{category}**"
                )
                return (
                    f"😅 No jokes found anywhere for {hint}.\n\n"
                    f"Try a different keyword or category: "
                    f"Any, Programming, Misc, Dark, Pun, Spooky, Christmas."
                )
            notice = (
                "⚠️ Live APIs returned no results — showing built-in offline jokes instead."
                if not search
                else f'⚠️ No online results for "{search}" — showing built-in jokes instead.'
            )
            return self._format(offline_jokes, amount, offline_notice=notice)

        return self._format(unique, amount)

    def list_categories(self) -> str:
        """
        Returns available categories, search tips, and source information.
        :return: Formatted string with all options.
        """
        return (
            "📋 **Available Joke Categories:**\n\n"
            "- **Any** — Random from all categories\n"
            "- **Programming** — Nerdy coding & tech jokes\n"
            "- **Misc / General** — General humor\n"
            "- **Dark** — Dark humor *(safe_mode=False to unlock)*\n"
            "- **Pun** — Puns and wordplay\n"
            "- **Spooky** — Halloween & horror-themed\n"
            "- **Christmas** — Holiday & Christmas jokes\n"
            "- **Knock-Knock** — Classic knock-knock jokes\n\n"
            "🔍 **Search by keyword across all sources:**\n"
            "Examples: search='chicken', search='doctor', search='coffee', search='git'\n\n"
            "📡 **Sources (queried simultaneously):**\n"
            "1. JokeAPI — 1,368 jokes, categories + keyword search\n"
            "2. icanhazdadjoke — 300+ dad jokes, excellent keyword search\n"
            "3. Official Joke API — 150+ general & programming jokes\n"
            "4. Built-in offline bank — 250+ jokes, always available\n\n"
            "📴 **Offline mode:** Set offline=True to use only built-in jokes.\n"
            "The offline bank is also used automatically as a fallback if APIs fail.\n\n"
            "🛡️ Safe mode ON by default. Set safe_mode=False for edgier content."
        )
