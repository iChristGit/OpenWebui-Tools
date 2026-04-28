"""
title: Genius Song Lyrics
author: iChrist (adapted from MrMilitaryMech tool)
author_url: https://github.com/MrMilitaryMech
version: 0.4.3
"""

import re
import requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher


def _similarity(a: str, b: str) -> float:
    """Return a 0–1 similarity score between two strings (case-insensitive)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _normalize(text: str) -> str:
    """Strip punctuation/extra spaces for looser comparisons."""
    return re.sub(r"[^\w\s]", "", text).strip().lower()


class Tools:
    def __init__(self):
        self.token = "QmwKhvaYRoBGQlYfcDqpakI76jG37UrH9Da21_GWwaSEfC1x6yf6SIjdw5wKs4yj"

        # Minimum similarity thresholds (tweak if needed)
        self.TITLE_THRESHOLD = 0.6
        self.ARTIST_THRESHOLD = 0.5

    def _query_genius(self, query: str) -> list:
        """Run a single search query against the Genius API and return hits."""
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            "https://api.genius.com/search",
            headers=headers,
            params={"q": query},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()["response"]["hits"]
        return []

    def _best_hit(self, hits: list, title: str, artist: str):
        """
        Score every hit by combined title+artist similarity and return the
        best one that clears both thresholds. Falls back to the top hit if
        nothing clears the bar (so we never return empty-handed on a good search).
        """
        best_result = None
        best_score = -1

        for hit in hits:
            result = hit["result"]
            hit_title = result.get("title", "")
            hit_artist = result.get("primary_artist", {}).get("name", "")

            t_score = _similarity(_normalize(title), _normalize(hit_title))
            a_score = _similarity(_normalize(artist), _normalize(hit_artist))
            combined = (t_score + a_score) / 2

            if combined > best_score:
                best_score = combined
                best_result = result

            # Exact enough on both? Return immediately.
            if t_score >= self.TITLE_THRESHOLD and a_score >= self.ARTIST_THRESHOLD:
                return result

        # Nothing cleared both thresholds — return the best overall match
        # only if it cleared at least the title bar (artist aliases are common)
        if (
            best_result
            and _similarity(_normalize(title), _normalize(best_result.get("title", "")))
            >= self.TITLE_THRESHOLD
        ):
            return best_result

        return None

    def search_song(self, title: str, artist: str):
        """
        Try several query variants and return the best-matching Genius result.
        Strategies (in order):
          1. "title artist"          – standard
          2. "title"                 – artist name might differ (aliases, features)
          3. "artist title"          – reversed order sometimes ranks better
        """
        queries = [
            f"{title} {artist}",
            title,
            f"{artist} {title}",
        ]

        for query in queries:
            hits = self._query_genius(query)
            if not hits:
                continue
            result = self._best_hit(hits, title, artist)
            if result:
                return result

        return None

    def get_lyrics_url(self, song_id: int):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            f"https://api.genius.com/songs/{song_id}",
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()["response"]["song"]["url"]
        return None

    def scrape_lyrics(self, lyrics_url: str) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(lyrics_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return f"Failed to retrieve lyrics. Status code: {response.status_code}"

        soup = BeautifulSoup(response.text, "html.parser")

        # Modern Genius markup
        lyrics_divs = soup.find_all(
            "div", class_=lambda c: c and "Lyrics__Container" in c
        )
        # Fallback for older Genius pages
        if not lyrics_divs:
            lyrics_divs = soup.find_all("div", class_="lyrics")

        if not lyrics_divs:
            return "Lyrics not found."

        lyrics = ""
        for div in lyrics_divs:
            for br in div.find_all("br"):
                br.replace_with("\n")
            lyrics += div.get_text() + "\n"

        return lyrics.strip()

    def get_song_lyrics(self, title: str, artist: str) -> str:
        """
        Get the lyrics of a given song by title and artist.
        :param title: The title of the song.
        :param artist: The artist of the song.
        :return: The lyrics of the song or an error message.
        """
        if not title or not artist:
            return "The song title or artist has not been defined, so lyrics cannot be determined."

        try:
            song = self.search_song(title, artist)
            if not song:
                return f"Song '{title}' by '{artist}' not found on Genius."

            # Tell the caller which result was actually matched (helpful for debugging)
            matched_title = song.get("title", title)
            matched_artist = song.get("primary_artist", {}).get("name", artist)

            lyrics_url = self.get_lyrics_url(song["id"])
            if not lyrics_url:
                return f"Lyrics URL not found for '{title}' by '{artist}'."

            lyrics = self.scrape_lyrics(lyrics_url)
            header = f"Lyrics for '{matched_title}' by '{matched_artist}':"
            if (
                matched_title.lower() != title.lower()
                or matched_artist.lower() != artist.lower()
            ):
                header += f"\n(Searched for: '{title}' by '{artist}')"
            return f"{header}\n{lyrics}"

        except Exception as e:
            return f"Error fetching lyrics: {str(e)}"
