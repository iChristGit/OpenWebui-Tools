"""
title: Wikipedia Lookup Tool
author: ichrist
description: >
    Search and retrieve Wikipedia articles with smart disambiguation,
    section-aware extraction, and three detail levels (brief / standard / full).
    Supports 20+ languages. No API key required.
version: 1.1.0
license: MIT
"""

import json
import re
import urllib.request
import urllib.parse
from typing import Optional


class Tools:
    """
    Wikipedia tool using the free MediaWiki Action API and REST API.
    No authentication or API key required.

    INSTRUCTIONS FOR THE LLM — READ CAREFULLY:

    PRIMARY METHOD: lookup(query, detail, language)
      Use this for almost every Wikipedia request. It searches for the best
      matching article, fetches its content, and returns structured output.

      detail levels:
        - "brief"    → intro paragraph only. Use for simple factual questions
                       ("What is photosynthesis?", "Who is Marie Curie?").
        - "standard" → intro + all section summaries. Use for most questions.
                       This is the DEFAULT — use it when unsure.
        - "full"     → complete article text (truncated at ~8000 words).
                       Use only when the user explicitly wants deep detail
                       ("Tell me everything about X", "Give me a full overview").

    SECONDARY METHOD: search(query, language)
      Use only when:
        - The user wants to browse/explore a topic ("What Wikipedia articles
          exist about quantum mechanics?")
        - lookup() returns a disambiguation and you need to show the user options
        - The user asks "search Wikipedia for..."

    LANGUAGE: Pass the ISO 639-1 code (e.g. "fr", "de", "es", "ja").
    Default is "en". Use the user's language if they write in another language.

    BEHAVIOR RULES:
    - Call lookup() or search() ONCE. Do NOT call again unless user asks a
      follow-up or wants more detail.
    - After receiving results, synthesize and present them naturally. Do NOT
      just paste the raw tool output verbatim.
    - If the article is a disambiguation page, call search() to show options,
      then ask the user which they meant.
    - Always mention the Wikipedia URL so the user can read further.
    """

    LANG_NAMES = {
        "en": "English",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "ru": "Russian",
        "ja": "Japanese",
        "zh": "Chinese",
        "ar": "Arabic",
        "ko": "Korean",
        "pl": "Polish",
        "sv": "Swedish",
        "fa": "Persian",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "vi": "Vietnamese",
        "he": "Hebrew",
        "id": "Indonesian",
    }

    def __init__(self):
        self._ua = "OpenWebUI-WikipediaTool/1.0 (https://openwebui.com)"

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": self._ua})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def _api(self, lang: str, params: dict) -> dict:
        base = f"https://{lang}.wikipedia.org/w/api.php"
        qs = urllib.parse.urlencode({**params, "format": "json", "utf8": 1})
        return self._get(f"{base}?{qs}")

    def _rest_summary(self, lang: str, title: str) -> dict:
        encoded = urllib.parse.quote(title.replace(" ", "_"))
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        return self._get(url)

    def _clean(self, text: str) -> str:
        """Strip wiki markup artifacts that slip through plaintext extraction."""
        text = re.sub(r"\n{3,}", "\n\n", text)  # collapse blank lines
        text = re.sub(r" {2,}", " ", text)  # collapse spaces
        text = re.sub(r"\[\d+\]", "", text)  # remove citation markers [1]
        text = re.sub(r"\[note \d+\]", "", text)  # remove note markers
        text = re.sub(r"={2,}[^=]+=*={2,}", "", text)  # leftover == headers ==
        return text.strip()

    def _is_disambiguation(self, title: str, extract: str) -> bool:
        lowt = title.lower()
        lowe = (extract or "").lower()
        return (
            "(disambiguation)" in lowt
            or "may refer to:" in lowe
            or "may refer to\n" in lowe
            or (
                lowe.strip().startswith("this article is about")
                and ("for other uses" in lowe or "see also" in lowe)
            )
        )

    def _truncate(self, text: str, max_chars: int) -> tuple:
        if len(text) <= max_chars:
            return text, False
        cut = text[:max_chars]
        last_para = cut.rfind("\n\n")
        if last_para > max_chars * 0.7:
            cut = cut[:last_para]
        return cut, True

    def _search_titles(self, query: str, lang: str, limit: int = 6) -> list:
        data = self._api(
            lang,
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "srprop": "snippet|titlesnippet",
            },
        )
        return data.get("query", {}).get("search", [])

    def _fetch_extract(self, title: str, lang: str, intro_only: bool = False) -> str:
        """Fetch plain-text extract for an article (full or intro only)."""
        params = {
            "action": "query",
            "prop": "extracts",
            "titles": title,
            "explaintext": 1,
            "redirects": 1,
        }
        if intro_only:
            params["exintro"] = 1
        data = self._api(lang, params)
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        return self._clean(page.get("extract", ""))

    def _fetch_sections(self, title: str, lang: str) -> list:
        """Return the table-of-contents section list for an article."""
        data = self._api(
            lang,
            {
                "action": "parse",
                "page": title,
                "prop": "sections",
                "redirects": 1,
            },
        )
        return data.get("parse", {}).get("sections", [])

    def _fetch_section_text(self, title: str, lang: str, section_index: int) -> str:
        """
        Fetch plain-text content of a single section by its numeric index.

        Uses action=parse with prop=wikitext + section, then strips markup.
        This is the correct approach — the previous rvsection trick on
        action=query/prop=extracts does NOT work and returns the intro every time.
        """
        data = self._api(
            lang,
            {
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "section": section_index,
                "redirects": 1,
                "disableeditsection": 1,
            },
        )
        wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
        return self._clean(self._strip_wikitext(wikitext))

    def _strip_wikitext(self, text: str) -> str:
        """
        Convert raw wikitext to readable plain text.
        Handles the most common markup patterns.
        """
        # Remove templates: {{...}}  (non-greedy, handles nesting via repeat)
        prev = None
        while prev != text:
            prev = text
            text = re.sub(r"\{\{[^{}]*\}\}", "", text)

        # Remove [[File:...]] / [[Image:...]] with captions
        text = re.sub(
            r"\[\[(?:File|Image|Media):[^\]]*\]\]", "", text, flags=re.IGNORECASE
        )

        # Convert [[link|label]] → label, [[link]] → link
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)

        # Remove external links [http://... label] → label, bare [http://...] → ''
        text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
        text = re.sub(r"\[https?://\S+\]", "", text)

        # Remove bold/italic markup
        text = re.sub(r"'{2,3}", "", text)

        # Remove section headers (==/===/etc.)
        text = re.sub(r"={2,}[^=\n]+=*={2,}", "", text)

        # Remove HTML tags
        text = re.sub(r"<ref[^>]*/?>.*?</ref>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)

        # Collapse whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)

        return text.strip()

    def _fetch_links(self, title: str, lang: str, limit: int = 8) -> list:
        data = self._api(
            lang,
            {
                "action": "query",
                "prop": "links",
                "titles": title,
                "pllimit": limit,
                "plnamespace": 0,
            },
        )
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        return [lnk["title"] for lnk in page.get("links", [])]

    def _page_url(self, title: str, lang: str) -> str:
        encoded = urllib.parse.quote(title.replace(" ", "_"))
        return f"https://{lang}.wikipedia.org/wiki/{encoded}"

    def _strip_html(self, text: str) -> str:
        return re.sub(r"<[^>]+>", "", text)

    # ── Public methods ────────────────────────────────────────────────────────

    def lookup(
        self,
        query: str,
        detail: str = "standard",
        language: str = "en",
    ) -> str:
        """
        Search Wikipedia and return article content. This is the main method —
        use it for almost all Wikipedia queries.

        :param query: What to look up. Can be a topic, person, concept, question,
                      or specific article title. Natural language is fine.
        :param detail: How much content to return.
                       "brief"    — intro paragraph only (~1–3 sentences to a paragraph).
                                    Best for: quick facts, definitions, "who is X".
                       "standard" — intro + section-by-section summaries (DEFAULT).
                                    Best for: most questions, explanations, overviews.
                       "full"     — complete article up to ~8000 chars.
                                    Best for: "tell me everything", deep dives.
        :param language: Wikipedia language edition. ISO 639-1 code (default "en").
                         Examples: "fr" (French), "de" (German), "es" (Spanish),
                         "ja" (Japanese), "zh" (Chinese), "ar" (Arabic).
        :return: Structured article content with title, URL, content, and related links.
        """
        lang = language.strip().lower() or "en"

        # Normalise detail — accept common aliases
        detail = (detail or "standard").strip().lower()
        alias_map = {"intro": "brief", "short": "brief", "long": "full", "all": "full"}
        detail = alias_map.get(detail, detail)
        if detail not in ("brief", "standard", "full"):
            detail = "standard"

        # ── Step 1: Find best matching article ──────────────────────────────
        results = self._search_titles(query, lang, limit=6)
        if not results:
            lang_label = (
                f" in {self.LANG_NAMES.get(lang, lang)} Wikipedia."
                if lang != "en"
                else "."
            )
            return (
                f'❌ No Wikipedia articles found for **"{query}"**{lang_label}\n\n'
                "Try rephrasing your query or use a different language."
            )

        title = results[0]["title"]

        # ── Step 2: Fetch REST summary (fast, has description + thumbnail) ──
        try:
            rest = self._rest_summary(lang, title)
            if rest.get("type") == "disambiguation":
                return self._handle_disambiguation(title, lang, results)
            canonical_title = rest.get("title", title)
            description = rest.get("description", "")
            rest_extract = rest.get("extract", "")
            page_url = rest.get("content_urls", {}).get("desktop", {}).get(
                "page"
            ) or self._page_url(canonical_title, lang)
            last_modified = (
                rest.get("timestamp", "")[:10] if rest.get("timestamp") else ""
            )
        except Exception:
            canonical_title = title
            description = ""
            rest_extract = ""
            page_url = self._page_url(title, lang)
            last_modified = ""

        # ── Step 3: Build output ─────────────────────────────────────────────
        output_parts = []

        # Header block
        header = f"## {canonical_title}"
        if description:
            header += f"\n_{description}_"
        if last_modified:
            header += f"\n📅 Last updated: {last_modified}"
        header += f"\n🔗 {page_url}"
        output_parts.append(header)

        # ── brief ────────────────────────────────────────────────────────────
        if detail == "brief":
            intro = rest_extract or self._fetch_extract(
                canonical_title, lang, intro_only=True
            )
            output_parts.append(intro if intro else "_(No summary available.)_")

        # ── standard ─────────────────────────────────────────────────────────
        elif detail == "standard":
            # Intro
            intro = self._fetch_extract(canonical_title, lang, intro_only=True)
            if intro:
                intro_trunc, _ = self._truncate(intro, 2000)
                output_parts.append("### Introduction\n" + intro_trunc)

            # Section summaries
            try:
                sections = self._fetch_sections(canonical_title, lang)

                skip_titles = {
                    "see also",
                    "references",
                    "external links",
                    "further reading",
                    "notes",
                    "bibliography",
                    "citations",
                    "footnotes",
                    "sources",
                }
                # Only top-level sections (toclevel == 1), skip boilerplate
                key_sections = [
                    s
                    for s in sections
                    if s.get("toclevel", 1) == 1
                    and s.get("line", "").lower() not in skip_titles
                ][:6]

                if key_sections:
                    toc = "\n".join(f"  - {s['line']}" for s in key_sections)
                    output_parts.append("### Contents\n" + toc)

                    section_summaries = []
                    for s in key_sections[:4]:  # cap API calls at 4
                        try:
                            # 'index' is the correct numeric section index for parse API
                            idx = int(s.get("index", 0))
                            if idx == 0:
                                continue
                            sec_text = self._fetch_section_text(
                                canonical_title, lang, idx
                            )
                            if sec_text:
                                # Take only the first paragraph, capped at 500 chars
                                first_para = sec_text.split("\n\n")[0].strip()
                                first_para, _ = self._truncate(first_para, 500)
                                if first_para:
                                    section_summaries.append(
                                        f"**{s['line']}**\n{first_para}"
                                    )
                        except Exception:
                            continue

                    if section_summaries:
                        output_parts.append("\n\n---\n\n".join(section_summaries))

            except Exception:
                # Graceful fallback: plain extract
                full = self._fetch_extract(canonical_title, lang)
                trunc, was_cut = self._truncate(full, 4000)
                output_parts.append(trunc)
                if was_cut:
                    output_parts.append(f"_…article continues at {page_url}_")

        # ── full ─────────────────────────────────────────────────────────────
        else:
            full_text = self._fetch_extract(canonical_title, lang)
            if self._is_disambiguation(canonical_title, full_text):
                return self._handle_disambiguation(canonical_title, lang, results)
            trunc, was_cut = self._truncate(full_text, 9000)
            output_parts.append(trunc)
            if was_cut:
                output_parts.append(
                    f"\n_…article truncated for context. Full article: {page_url}_"
                )

        # ── Step 4: Related articles ─────────────────────────────────────────
        try:
            links = self._fetch_links(canonical_title, lang, limit=6)
            if links:
                related = ", ".join(f"**{l}**" for l in links[:6])
                output_parts.append(f"\n📚 **Related topics:** {related}")
        except Exception:
            pass

        # ── Step 5: Disambiguation safety-check for brief/standard ───────────
        if detail != "full":
            if self._is_disambiguation(canonical_title, rest_extract):
                return self._handle_disambiguation(canonical_title, lang, results)

        return "\n\n".join(output_parts)

    def _handle_disambiguation(
        self, title: str, lang: str, search_results: list
    ) -> str:
        lines = [
            f'⚠️ **"{title}" is a disambiguation page** — multiple articles match this title.\n',
            "Here are the closest results. Ask me which one you'd like to explore:\n",
        ]
        for i, r in enumerate(search_results[:6], 1):
            snippet = self._strip_html(r.get("snippet", "")).strip()
            snippet = re.sub(r"\s+", " ", snippet)
            snippet = (snippet[:120] + "…") if len(snippet) > 120 else snippet
            url = self._page_url(r["title"], lang)
            lines.append(f"**{i}. {r['title']}**\n   _{snippet}_\n   {url}")
        return "\n\n".join(lines)

    def search(
        self,
        query: str,
        language: str = "en",
    ) -> str:
        """
        Search Wikipedia and return a list of matching article titles and snippets.
        Use this when the user wants to browse/explore a topic, or when lookup()
        returns a disambiguation. For direct questions, prefer lookup() instead.

        :param query: Search terms or topic to find.
        :param language: Wikipedia language code (default "en").
        :return: A numbered list of up to 8 matching articles with descriptions and URLs.
        """
        lang = language.strip().lower() or "en"
        results = self._search_titles(query, lang, limit=8)

        if not results:
            lang_label = (
                f" in {self.LANG_NAMES.get(lang, lang.upper())} Wikipedia."
                if lang != "en"
                else "."
            )
            return f'❌ No Wikipedia results for **"{query}"**{lang_label}'

        lang_label = (
            f" ({self.LANG_NAMES.get(lang, lang.upper())} Wikipedia)"
            if lang != "en"
            else ""
        )
        lines = [f'### Wikipedia search results for "{query}"{lang_label}\n']

        for i, r in enumerate(results, 1):
            snippet = self._strip_html(r.get("snippet", "")).strip()
            snippet = re.sub(r"\s+", " ", snippet)
            snippet = (snippet[:150] + "…") if len(snippet) > 150 else snippet
            url = self._page_url(r["title"], lang)
            lines.append(f"**{i}. {r['title']}**\n_{snippet}_\n{url}")

        lines.append(
            "\n_Use `lookup()` with any of these titles for the full article._"
        )
        return "\n\n".join(lines)
