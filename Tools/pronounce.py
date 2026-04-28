"""
title: Language Pronunciation Guide — v5 Quick Edition
author: iChrist
description: >
  Ultimate travel language companion. Three tools:
  🔤 quick_pronounce_word (NEW — compact single-word banner, syllable pills with
  English phonetics, auto-play normal+slow, mnemonic, IPA — no tabs, instant),
  📚 pronounce (full flip-card learning experience, dual-tab),
  🧭 translate_and_play ("how do I say X in Y" travel tool, Navigator tab first).
version: 5.0.0
license: MIT
requirements: gtts
"""

# ─────────────────────────────────────────────────────────────────────────────
#  HOW IT WORKS
#  1. LLM calls pronounce() or translate_and_play() with pre-generated word_data.
#  2. gTTS generates full-phrase MP3 in-memory → base64 data-URI (1 call).
#  3. Word chip audio uses browser Web Speech API by default (zero bandwidth).
#     Set Valve word_audio_mode="gtts" to get high-quality per-word audio.
#  4. Slow mode defaults to Web Speech rate control (zero bandwidth).
#     Set Valve generate_slow_audio=True for a gTTS slow phrase.
#  5. A fully self-contained HTML player is emitted via the "embeds" event.
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import base64
import io
import json
import uuid
from typing import Callable, Optional

from gtts import gTTS, lang as gtts_lang
from pydantic import BaseModel, Field

# ── Language / locale maps ──────────────────────────────────────────────────

LANGUAGE_MAP: dict[str, str] = {
    "french": "fr",
    "español": "es",
    "spanish": "es",
    "portuguese": "pt",
    "italian": "it",
    "romanian": "ro",
    "german": "de",
    "dutch": "nl",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "russian": "ru",
    "polish": "pl",
    "czech": "cs",
    "japanese": "ja",
    "chinese": "zh-CN",
    "mandarin": "zh-CN",
    "cantonese": "zh-TW",
    "korean": "ko",
    "thai": "th",
    "vietnamese": "vi",
    "hindi": "hi",
    "bengali": "bn",
    "indonesian": "id",
    "arabic": "ar",
    "turkish": "tr",
    "hebrew": "iw",
    "swahili": "sw",
    "greek": "el",
    "hungarian": "hu",
    "finnish": "fi",
    "ukrainian": "uk",
    "catalan": "ca",
    "welsh": "cy",
    "english": "en",
}

LANGUAGE_FLAGS: dict[str, str] = {
    "fr": "🇫🇷",
    "es": "🇪🇸",
    "de": "🇩🇪",
    "it": "🇮🇹",
    "pt": "🇵🇹",
    "ja": "🇯🇵",
    "zh-CN": "🇨🇳",
    "zh-TW": "🇹🇼",
    "ko": "🇰🇷",
    "ru": "🇷🇺",
    "pl": "🇵🇱",
    "cs": "🇨🇿",
    "ar": "🇸🇦",
    "hi": "🇮🇳",
    "bn": "🇧🇩",
    "tr": "🇹🇷",
    "iw": "🇮🇱",
    "el": "🇬🇷",
    "hu": "🇭🇺",
    "fi": "🇫🇮",
    "uk": "🇺🇦",
    "nl": "🇳🇱",
    "sv": "🇸🇪",
    "no": "🇳🇴",
    "da": "🇩🇰",
    "th": "🇹🇭",
    "vi": "🇻🇳",
    "id": "🇮🇩",
    "sw": "🇰🇪",
    "ca": "🏴",
    "cy": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "en": "🇬🇧",
    "ro": "🇷🇴",
}

LANGUAGE_GRADIENTS: dict[str, tuple[str, str]] = {
    "fr": ("#003189", "#ED2939"),
    "es": ("#AA151B", "#F1BF00"),
    "de": ("#1a1a1a", "#CC0000"),
    "it": ("#008C45", "#CE2B37"),
    "pt": ("#006600", "#FF0000"),
    "ja": ("#BC002D", "#2C2C6C"),
    "zh-CN": ("#DE2910", "#FFDE00"),
    "zh-TW": ("#1B449C", "#FE0000"),
    "ko": ("#003478", "#CD2E3A"),
    "ru": ("#0032A0", "#DC143C"),
    "ar": ("#007A3D", "#CE1126"),
    "hi": ("#FF671F", "#046A38"),
    "tr": ("#E30A17", "#1C1C1C"),
    "el": ("#0D5EAF", "#4a90d9"),
    "uk": ("#005BBB", "#FFD500"),
    "sv": ("#006AA7", "#FECC02"),
    "no": ("#EF2B2D", "#002868"),
    "da": ("#C60C30", "#003580"),
    "fi": ("#003580", "#4a7fd4"),
    "nl": ("#AE1C28", "#21468B"),
    "en": ("#012169", "#C8102E"),
    "ro": ("#002B7F", "#FCD116"),
    "pl": ("#DC143C", "#6a1a2a"),
    "hu": ("#CE2939", "#477050"),
    "cs": ("#D7141A", "#11457E"),
    "iw": ("#003399", "#4466cc"),
    "sw": ("#006600", "#1a4a00"),
}
DEFAULT_GRADIENT = ("#667eea", "#764ba2")

CULTURAL_EMOJIS: dict[str, list[str]] = {
    "fr": ["🗼", "⚜️", "🥐", "🍷", "🎨", "🌹", "🧀", "🎭"],
    "es": ["💃", "🌹", "🎸", "🌮", "🌊", "🐂", "⛅", "🌴"],
    "de": ["🍺", "🏰", "⚙️", "🎻", "🌲", "❄️", "🥨", "🦅"],
    "it": ["🍕", "🎭", "⛵", "🌹", "🍝", "🏛️", "🌺", "🎺"],
    "pt": ["🎸", "🌊", "⛵", "🦜", "🌺", "☀️", "🐟", "🎭"],
    "ja": ["🌸", "⛩️", "🗾", "🎏", "🍜", "🎌", "🌙", "🏯"],
    "zh-CN": ["🏮", "🐉", "🧧", "🎆", "🌙", "🐼", "🍜", "⭐"],
    "zh-TW": ["🏮", "🐉", "🧧", "🌸", "🌙", "⭐", "🌺", "🎋"],
    "ko": ["🌸", "🎭", "🎮", "🌺", "🎵", "🌙", "⭐", "🏯"],
    "ru": ["🪆", "❄️", "⭐", "🏔️", "🎻", "🐻", "🌺", "🌙"],
    "ar": ["🌙", "⭐", "🕌", "🏺", "🌴", "🐪", "🌅", "🎨"],
    "hi": ["🪷", "🐘", "🌺", "🎆", "🏯", "🌙", "⭐", "🎵"],
    "tr": ["🌙", "⭐", "🕌", "🌹", "🌊", "🏛️", "🎭", "🍵"],
    "el": ["🏛️", "🌊", "⛵", "🌅", "🫒", "🍋", "🏺", "🌙"],
    "uk": ["🌻", "❄️", "⭐", "🕊️", "🏔️", "🌺", "💛", "💙"],
    "nl": ["🌷", "🧀", "⚓", "🌾", "🎨", "🚲", "🌸", "🌬️"],
    "sv": ["👑", "🌲", "❄️", "🦌", "🌸", "⚓", "🌊", "🎿"],
    "no": ["⛵", "🏔️", "❄️", "🦌", "🌊", "👑", "🌅", "🐺"],
    "da": ["🍄", "⚓", "🌊", "👑", "🧜", "❄️", "🌸", "🐦"],
    "fi": ["❄️", "🦌", "🌲", "🎿", "🌅", "🪶", "🌸", "🐧"],
    "pl": ["🦅", "🌹", "❄️", "⛪", "🌲", "⭐", "🍄", "💛"],
    "en": ["🎩", "🍵", "🏰", "🌹", "⚓", "🎭", "🌂", "🦁"],
    "default": ["🌍", "🎵", "📚", "✨", "🌟", "💫", "🗺️", "📖"],
}

CJK_LANGS = {"ja", "zh-CN", "zh-TW", "zh", "ko", "th"}
TONAL_LANGS = {"zh-CN", "zh-TW", "zh", "vi", "th"}

PHONETIC_TIPS: dict[str, str] = {
    "fr": "Nasal vowels (an/en/in/on/un) resonate in the nose. Final consonants are almost always silent. The uvular 'r' comes from the back of the throat. Liaison links words: <em>les amis</em> → /lez‿ami/.",
    "de": "'ch' after front vowels = [ç] (like whispering 'hue'), after back vowels = [x] (Scottish 'loch'). 'w' is always [v], 'v' is usually [f]. Every syllable is crisp.",
    "es": "'j' is a throaty [x]. Trill 'rr' by relaxing your tongue tip. 'c' before e/i = [s] in Latin America, [θ] in Spain. Vowels are pure and short.",
    "pt": "Nasal vowels: 'ão' ≈ /ãw/, 'ã' ≈ /ã/. 'lh' = [ʎ], 'nh' = [ɲ]. European Portuguese swallows unstressed vowels; Brazilian opens them.",
    "it": "'c' before i/e = [tʃ] (church). 'g' before i/e = [dʒ] (judge). Double consonants are held longer. Stress is usually penultimate.",
    "ja": "Pitch-accent language: tone rise/fall changes meaning. Each mora gets equal time. Long vowels (ō, ū) held twice as long. 'r' is a light flap between English r and l.",
    "zh-CN": "4 tones + neutral: ¯ (high level) / ˊ (rising) ∨ (dip-rise) ˋ (falling). Pinyin 'x'=[ɕ], 'zh'=[ʈʂ], 'q'=[tɕ]. Tones are not optional — they change meaning completely.",
    "ko": "Three consonant types: aspirated (kh,ph,th), plain (k,p,t), tense (kk,pp,tt). Final consonants link into next syllable when followed by a vowel.",
    "ar": "Emphatic consonants (ص,ض,ط,ظ) darken adjacent vowels. Pharyngeal ʕ (ع) and ħ (ح) come deep from the throat. Short vowels often omitted in written text.",
    "ru": "Soft consonants marked by ь. Unstressed 'o' reduces to [ə] or [a] — молоко is pronounced 'malakó'. Stress is unpredictable and must be memorized.",
    "hi": "Aspirated stops (kh,gh,ch,jh,th,dh,ph,bh) are distinct phonemes. Retroflex consonants (ट ठ ड ढ) made with tongue curled back.",
    "tr": "Vowel harmony: suffixes must match root vowel (front/back, round/unround). 'ğ' lengthens preceding vowel. Stress falls on last syllable by default.",
    "el": "'γ' before front vowels = [ʝ] (soft y-sound). Stress always marked with accent (´) and is meaningful. Double consonants pronounced distinctly.",
    "default": "Listen to each word multiple times. Focus on mouth shape, tongue position, and breath. Use 🐢 Slow mode for learner-friendly pacing.",
}

# ── Audio helpers ───────────────────────────────────────────────────────────


def _audio_b64(text: str, lang: str, slow: bool = False) -> str:
    tts = gTTS(text=text, lang=lang, slow=slow)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


async def _audio_b64_async(text: str, lang: str, slow: bool = False) -> str:
    return await asyncio.to_thread(_audio_b64, text, lang, slow)


# ── Language resolution ─────────────────────────────────────────────────────


def _resolve_language(raw: str) -> tuple[str, str]:
    cleaned = raw.strip().lower()
    try:
        supported = gtts_lang.tts_langs()
        for code in supported:
            if code.lower() == cleaned:
                return code, supported[code]
    except Exception:
        pass
    if cleaned in LANGUAGE_MAP:
        code = LANGUAGE_MAP[cleaned]
        try:
            supported = gtts_lang.tts_langs()
            return code, supported.get(code, code)
        except Exception:
            return code, code
    raise ValueError(
        f"Unknown language '{raw}'. Try 'French', 'Japanese', 'ar', 'zh-CN', etc."
    )


# ── HTML component builders ─────────────────────────────────────────────────


def _make_particles(emojis: list[str]) -> str:
    positions = [
        (8, 12, 0.0, 5.5),
        (85, 8, 0.9, 6.2),
        (3, 55, 1.7, 5.0),
        (92, 50, 0.4, 6.8),
        (12, 82, 1.2, 5.3),
        (78, 78, 2.1, 6.0),
        (50, 5, 0.6, 7.0),
        (45, 90, 1.5, 5.8),
    ]
    return "\n".join(
        f'<div class="particle" style="left:{x}%;top:{y}%;animation-delay:{d:.1f}s;animation-duration:{dur:.1f}s">{emojis[i%len(emojis)]}</div>'
        for i, (x, y, d, dur) in enumerate(positions)
    )


def _make_word_cards(words_data: list[dict]) -> str:
    cards = []
    for i, w in enumerate(words_data):
        word = w.get("word", "")
        ipa = w.get("ipa", "")
        trans = w.get("translation", "")
        roman = w.get("romanization", "")
        pos = w.get("part_of_speech", "")
        sylls = w.get("syllables", [])
        diff = int(w.get("difficulty", 0))
        mnemonic = w.get("mnemonic", "")
        example = w.get("example", "")
        ex_trans = w.get("example_translation", "")
        formality = w.get("formality", "")
        gender = w.get("gender", "")
        tone = w.get("tone", "")

        diff_html = "".join(
            f'<span class="dd {"df" if j<diff else "de"}"></span>' for j in range(5)
        )
        syl_str = " · ".join(sylls) if sylls else roman
        back_parts = []
        if ipa:
            back_parts.append(f'<div class="ipa">{ipa}</div>')
        if syl_str:
            back_parts.append(f'<div class="syllables">{syl_str}</div>')
        if trans:
            back_parts.append(f'<div class="word-trans">{trans}</div>')
        badges = ""
        if pos:
            badges += f'<span class="badge pos">{pos}</span>'
        if formality:
            badges += f'<span class="badge fm">{formality}</span>'
        if gender:
            badges += f'<span class="badge gd">{gender}</span>'
        if tone:
            badges += f'<span class="badge tn">tone: {tone}</span>'
        if badges:
            back_parts.append(f'<div class="badges">{badges}</div>')
        if mnemonic:
            back_parts.append(f'<div class="mnemonic">💡 {mnemonic}</div>')
        if example:
            ex_html = f'<div class="example">"{example}"</div>'
            if ex_trans:
                ex_html += f'<div class="example-trans">{ex_trans}</div>'
            back_parts.append(ex_html)

        has_back = bool(back_parts)
        back_body = "\n".join(back_parts)
        cards.append(f"""<div class="fc {'hb' if has_back else ''}" data-idx="{i}">
  <div class="fc-inner">
    <div class="fc-front">
      <div class="fc-top"><div class="diff-dots">{diff_html}</div>{'<span class="flip-hint">tap ↩</span>' if has_back else ''}</div>
      <div class="word-main" data-idx="{i}">{word}</div>
      {'<div class="word-roman">'+roman+'</div>' if roman and not sylls else ''}
      <button class="wab" data-idx="{i}" title="Play">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </button>
    </div>
    {'<div class="fc-back">'+back_body+'<button class="wab-back" data-idx="'+str(i)+'"><svg viewBox="0 0 24 24" fill="currentColor" width="11" height="11"><path d="M8 5v14l11-7z"/></svg> hear again</button></div>' if has_back else ''}
  </div>
</div>""")
    return "\n".join(cards)


def _make_related_phrases(related: list[dict]) -> str:
    if not related:
        return ""
    items = "".join(
        f'<div class="rp-item"><div class="rp-left"><span class="rp-phrase">{r.get("phrase","")}</span>'
        f'<span class="rp-trans">{r.get("translation","")}</span></div>'
        f'<button class="rp-play" data-phrase="{r.get("phrase","").replace(chr(34),chr(39))}" title="Play">'
        f'<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M8 5v14l11-7z"/></svg></button></div>'
        for r in related[:6]
    )
    return f'<div class="section-block"><div class="section-title">🔗 Related Phrases</div><div class="rp-grid">{items}</div></div>'


def _make_word_breakdown(words_data: list[dict], user_language: str) -> str:
    """Word-by-word breakdown table for Navigator panel."""
    if not words_data:
        return ""
    rows = []
    for i, w in enumerate(words_data):
        word = w.get("word", "")
        trans = w.get("translation", "—")
        roman = w.get("romanization", "")
        ipa = w.get("ipa", "")
        phonetic = roman or (f"/{ipa}/" if ipa else "")
        rows.append(
            f'<div class="wb-row" data-idx="{i}">'
            f'<div class="wb-left"><span class="wb-word">{word}</span>'
            f'{"<span class=wb-ph>"+phonetic+"</span>" if phonetic else ""}</div>'
            f'<span class="wb-arrow">→</span>'
            f'<span class="wb-trans">{trans}</span>'
            f'<button class="wb-play" data-word="{word.replace(chr(34),chr(39))}" data-idx="{i}" title="Say it">'
            f'<svg viewBox="0 0 24 24" fill="currentColor" width="11" height="11"><path d="M8 5v14l11-7z"/></svg></button>'
            f"</div>"
        )
    lang_label = (
        f"in {user_language}"
        if user_language and user_language.lower() not in ("en", "english")
        else ""
    )
    return (
        f'<div class="wb-section">'
        f'<div class="wb-title">📖 What each word means {lang_label}</div>'
        f'<div class="wb-list">{"".join(rows)}</div>'
        f"</div>"
    )


# ── Main HTML builder ───────────────────────────────────────────────────────


def _build_player_html(
    phrase: str,
    lang_code: str,
    lang_name: str,
    lang_flag: str,
    words: list[dict],
    phrase_normal_b64: str,
    phrase_slow_b64: str,  # "" if using Web Speech for slow
    tip: str,
    fun_fact: str,
    related_phrases: list[dict],
    cultural_emojis: list[str],
    navigator_mode: bool = False,
    use_speech_api: bool = True,
    user_language: str = "English",
    source_text: str = "",
) -> str:

    pid = uuid.uuid4().hex[:8]
    c0, c1 = LANGUAGE_GRADIENTS.get(lang_code, DEFAULT_GRADIENT)
    multi = len(words) > 1
    words_json = json.dumps(words)
    particles_html = _make_particles(cultural_emojis)
    word_cards_html = _make_word_cards(words)
    related_html = _make_related_phrases(related_phrases)
    word_breakdown_html = _make_word_breakdown(words, user_language)
    deco_emojis = " ".join(cultural_emojis[:3])

    # Phrase with word spans for highlighting (non-CJK only)
    if lang_code not in CJK_LANGS and len(words) > 1:
        raw_words = phrase.split()
        phrase_spans = " ".join(
            f'<span class="pw" data-idx="{i}">{w}</span>'
            for i, w in enumerate(raw_words)
        )
    else:
        phrase_spans = phrase

    # Waveform bars
    bars = "".join(
        f'<div class="bar" style="animation-delay:{i*0.05:.2f}s;animation-duration:{0.55+(i%7)*0.07:.2f}s"></div>'
        for i in range(28)
    )

    fact_html = (
        f'<div class="section-block fact-block"><div class="section-title">✨ Did you know?</div>'
        f'<p class="fact-text">{fun_fact}</p></div>'
        if fun_fact
        else ""
    )

    has_slow_b64 = bool(phrase_slow_b64)
    use_speech_api_js = "true" if use_speech_api else "false"
    has_slow_js = "true" if has_slow_b64 else "false"
    start_tab = "nav" if navigator_mode else "learn"
    source_html = (
        f'<div class="nav-source">🗣 "{source_text}"</div>' if source_text else ""
    )

    # Romanization for navigate panel (from first word with romanization, or phrase-level)
    nav_roman = ""
    for w in words:
        if w.get("romanization"):
            nav_roman = " ".join(
                ww.get("romanization", "") for ww in words if ww.get("romanization")
            )
            break

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --c0:{c0};--c1:{c1};
  --glass:rgba(255,255,255,0.08);
  --glass-border:rgba(255,255,255,0.14);
  --glass-dark:rgba(0,0,0,0.22);
  --text:rgba(255,255,255,1);
  --text-sub:rgba(255,255,255,0.72);
  --text-dim:rgba(255,255,255,0.42);
  --accent:#fff;
  --radius:18px;--radius-sm:12px;--radius-xs:8px;
}}
html,body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:transparent;overflow-x:hidden}}
.app{{position:relative;max-width:540px;margin:0 auto 20px;padding:4px}}
.bg-layer{{position:fixed;inset:0;z-index:-1;pointer-events:none;background:linear-gradient(135deg,var(--c0) 0%,var(--c1) 100%);background-size:300% 300%;animation:bgDrift 12s ease infinite}}
@keyframes bgDrift{{0%{{background-position:0% 50%}}50%{{background-position:100% 50%}}100%{{background-position:0% 50%}}}}
.particles{{position:absolute;inset:0;pointer-events:none;overflow:hidden;border-radius:var(--radius);z-index:0}}
.particle{{position:absolute;font-size:22px;opacity:0.18;animation:particleFloat linear infinite;filter:blur(0.5px)}}
@keyframes particleFloat{{0%{{transform:translateY(0) rotate(0deg) scale(1);opacity:0.18}}50%{{transform:translateY(-28px) rotate(180deg) scale(1.08);opacity:0.26}}100%{{transform:translateY(0) rotate(360deg) scale(1);opacity:0.18}}}}
.card{{position:relative;z-index:1;background:rgba(0,0,0,0.32);backdrop-filter:blur(28px);-webkit-backdrop-filter:blur(28px);border-radius:var(--radius);border:1px solid var(--glass-border);box-shadow:0 32px 80px rgba(0,0,0,0.5),0 0 0 1px rgba(255,255,255,0.06);overflow:hidden;color:var(--text);animation:cardIn 0.5s cubic-bezier(0.34,1.56,0.64,1)}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(16px) scale(0.97)}}to{{opacity:1;transform:none}}}}

/* ── Hero ── */
.hero{{background:linear-gradient(160deg,rgba(255,255,255,0.1) 0%,rgba(255,255,255,0.03) 100%);padding:22px 24px 18px;text-align:center;border-bottom:1px solid var(--glass-border);position:relative;overflow:hidden}}
.lang-badge{{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.2);border-radius:999px;padding:5px 14px 5px 10px;font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:rgba(255,255,255,0.9);margin-bottom:12px}}
.lang-flag{{font-size:18px;line-height:1}}.lang-deco{{font-size:13px;opacity:0.7;letter-spacing:2px}}
.phrase-text{{font-size:26px;font-weight:900;letter-spacing:-0.5px;line-height:1.25;text-shadow:0 4px 20px rgba(0,0,0,0.4);margin-bottom:6px}}
.phrase-text .pw{{transition:background 0.2s,color 0.2s,border-radius 0.2s,padding 0.2s}}
.phrase-text .pw.hi{{background:rgba(255,255,255,0.92);color:{c0};border-radius:6px;padding:0 4px;box-shadow:0 2px 12px rgba(0,0,0,0.2)}}
.phrase-romanized{{font-size:13px;color:var(--text-sub);font-style:italic;letter-spacing:0.3px}}

/* ── Tabs ── */
.tab-bar{{display:flex;padding:0 16px;gap:6px;border-bottom:1px solid var(--glass-border);background:rgba(0,0,0,0.18)}}
.tab-btn{{flex:1;padding:11px 8px;background:none;border:none;color:var(--text-dim);font-size:12px;font-weight:800;letter-spacing:0.5px;cursor:pointer;border-bottom:2px solid transparent;transition:color 0.2s,border-color 0.2s;white-space:nowrap}}
.tab-btn.active{{color:#fff;border-bottom-color:rgba(255,255,255,0.7)}}
.tab-pane{{display:none}}.tab-pane.active{{display:block}}

/* ── Waveform ── */
.inner{{padding:0 20px}}
.waveform{{display:flex;align-items:center;justify-content:center;gap:3px;height:28px;padding:14px 0 10px;opacity:0.35;transition:opacity 0.4s}}
.waveform.playing{{opacity:1}}
.bar{{width:3px;border-radius:3px;background:rgba(255,255,255,0.9);height:3px;animation:barBounce ease-in-out infinite alternate;animation-play-state:paused}}
.waveform.playing .bar{{animation-play-state:running}}
@keyframes barBounce{{from{{height:3px;opacity:0.4}}to{{height:24px;opacity:1}}}}

/* ── Controls ── */
.controls{{display:flex;align-items:center;justify-content:center;gap:10px;padding:4px 20px 18px;flex-wrap:wrap}}
.btn-play-all{{display:inline-flex;align-items:center;gap:9px;background:rgba(255,255,255,0.95);color:{c0};border:none;border-radius:999px;padding:11px 24px;font-size:13px;font-weight:900;cursor:pointer;box-shadow:0 6px 24px rgba(0,0,0,0.3);transition:transform 0.13s,box-shadow 0.13s;letter-spacing:0.2px}}
.btn-play-all:hover{{transform:scale(1.05);box-shadow:0 10px 32px rgba(0,0,0,0.4)}}.btn-play-all:active{{transform:scale(0.97)}}
.speed-toggle{{display:flex;background:rgba(255,255,255,0.1);border-radius:999px;padding:3px;gap:2px;border:1px solid rgba(255,255,255,0.14)}}
.speed-btn{{border:none;background:transparent;color:rgba(255,255,255,0.6);border-radius:999px;padding:6px 14px;font-size:11px;font-weight:800;cursor:pointer;transition:background 0.18s,color 0.18s;letter-spacing:0.3px}}
.speed-btn.active{{background:rgba(255,255,255,0.22);color:#fff}}

/* ── Copy button ── */
.btn-copy{{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.18);color:rgba(255,255,255,0.8);border-radius:999px;padding:7px 14px;font-size:11px;font-weight:800;cursor:pointer;transition:background 0.15s,color 0.15s}}
.btn-copy:hover{{background:rgba(255,255,255,0.18);color:#fff}}
.btn-copy.copied{{background:rgba(100,255,180,0.2);border-color:rgba(100,255,180,0.4);color:#a0ffd0}}

/* ── Section blocks ── */
.section-title{{font-size:10px;font-weight:900;letter-spacing:2.5px;text-transform:uppercase;color:var(--text-dim);margin-bottom:12px;display:flex;align-items:center;gap:6px}}
.section-block{{margin:0 20px 18px;background:var(--glass-dark);border-radius:var(--radius-sm);border:1px solid var(--glass-border);padding:16px}}

/* ── Word flip cards ── */
.words-label{{font-size:10px;font-weight:900;letter-spacing:2.5px;text-transform:uppercase;color:var(--text-dim);margin:0 20px 12px}}
.words-grid{{display:flex;flex-wrap:wrap;gap:10px;padding:0 20px 20px}}
.fc{{width:calc(50% - 5px);min-width:130px;perspective:900px;cursor:default}}.fc.hb{{cursor:pointer}}
.fc-inner{{position:relative;width:100%;transition:transform 0.55s cubic-bezier(0.645,0.045,0.355,1);transform-style:preserve-3d;min-height:120px}}
.fc.flipped .fc-inner{{transform:rotateY(180deg)}}
.fc-front,.fc-back{{position:absolute;inset:0;border-radius:var(--radius-sm);backface-visibility:hidden;-webkit-backface-visibility:hidden;border:1px solid var(--glass-border);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:14px 12px;gap:8px}}
.fc-front{{background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);transition:background 0.2s,border-color 0.2s,box-shadow 0.2s}}
.fc.hb .fc-front:hover{{background:rgba(255,255,255,0.16);border-color:rgba(255,255,255,0.25);box-shadow:0 4px 20px rgba(0,0,0,0.2)}}
.fc.playing-chip .fc-front{{background:rgba(255,255,255,0.92);border-color:transparent;box-shadow:0 0 0 3px rgba(255,255,255,0.3),0 6px 24px rgba(0,0,0,0.3);animation:chipGlow 0.9s ease-in-out infinite alternate}}
@keyframes chipGlow{{from{{box-shadow:0 0 0 2px rgba(255,255,255,0.2),0 4px 16px rgba(0,0,0,0.25)}}to{{box-shadow:0 0 0 6px rgba(255,255,255,0.3),0 8px 28px rgba(0,0,0,0.35)}}}}
.fc.playing-chip .word-main{{color:{c0}}}.fc.playing-chip .wab{{color:{c0}!important;background:rgba(0,0,0,0.1)!important}}
.fc-back{{background:rgba(0,0,0,0.55);backdrop-filter:blur(20px);transform:rotateY(180deg);overflow-y:auto;gap:6px;align-items:flex-start;padding:14px}}
.fc-top{{display:flex;align-items:center;justify-content:space-between;width:100%}}
.diff-dots{{display:flex;gap:3px}}.dd{{width:7px;height:7px;border-radius:50%}}.df{{background:rgba(255,255,255,0.85)}}.de{{background:rgba(255,255,255,0.2)}}
.flip-hint{{font-size:9px;color:var(--text-dim);font-weight:700;letter-spacing:0.5px}}
.word-main{{font-size:20px;font-weight:900;letter-spacing:-0.3px;text-align:center;line-height:1.2;word-break:break-word}}
.word-roman{{font-size:11px;color:var(--text-sub);text-align:center}}
.wab{{background:rgba(255,255,255,0.15);border:none;border-radius:999px;width:34px;height:34px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#fff;transition:background 0.15s,transform 0.1s;flex-shrink:0}}
.wab:hover{{background:rgba(255,255,255,0.25);transform:scale(1.1)}}.wab:active{{transform:scale(0.93)}}.wab svg{{width:14px;height:14px}}
.ipa{{font-size:14px;color:rgba(255,255,255,0.55);letter-spacing:0.5px;font-family:monospace}}
.syllables{{font-size:12px;color:var(--text-sub);letter-spacing:1px;font-style:italic}}
.word-trans{{font-size:15px;font-weight:800;color:#fff;line-height:1.3}}
.badges{{display:flex;flex-wrap:wrap;gap:4px}}
.badge{{font-size:9px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;border-radius:6px;padding:3px 7px}}
.badge.pos{{background:rgba(100,200,255,0.2);color:#a8daff}}.badge.fm{{background:rgba(255,200,100,0.2);color:#ffe0a0}}
.badge.gd{{background:rgba(200,100,255,0.2);color:#e0b0ff}}.badge.tn{{background:rgba(100,255,180,0.2);color:#a0ffd0}}
.mnemonic{{font-size:11px;color:rgba(255,220,130,0.9);line-height:1.5;font-style:italic}}
.example{{font-size:11px;color:rgba(255,255,255,0.6);font-style:italic;line-height:1.4;margin-top:2px}}
.example-trans{{font-size:10px;color:rgba(255,255,255,0.4);line-height:1.4}}
.wab-back{{display:inline-flex;align-items:center;gap:5px;background:rgba(255,255,255,0.1);border:none;border-radius:999px;padding:5px 12px;color:rgba(255,255,255,0.65);font-size:10px;font-weight:700;cursor:pointer;margin-top:4px}}
.wab-back:hover{{background:rgba(255,255,255,0.18);color:#fff}}

/* ── Full phrase player ── */
.phrase-player{{display:flex;align-items:center;gap:12px}}
.phrase-play-btn{{width:44px;height:44px;border-radius:50%;border:none;background:rgba(255,255,255,0.92);color:{c0};cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;box-shadow:0 4px 16px rgba(0,0,0,0.25);transition:transform 0.13s,box-shadow 0.13s}}
.phrase-play-btn:hover{{transform:scale(1.08);box-shadow:0 6px 24px rgba(0,0,0,0.35)}}.phrase-play-btn:active{{transform:scale(0.93)}}
.progress-wrap{{flex:1;cursor:pointer}}.progress-track{{height:5px;border-radius:99px;background:rgba(255,255,255,0.18);overflow:hidden}}
.progress-fill{{height:100%;width:0%;border-radius:99px;background:linear-gradient(90deg,rgba(255,255,255,0.7),rgba(255,255,255,1));transition:width 0.1s linear;box-shadow:0 0 10px rgba(255,255,255,0.4)}}
.time-row{{display:flex;justify-content:space-between;font-size:9px;font-weight:700;color:var(--text-dim);margin-top:6px;font-variant-numeric:tabular-nums}}

/* ── Tip / fact / related ── */
.tip-text{{font-size:12px;line-height:1.7;color:var(--text-sub)}}.fact-text{{font-size:12px;line-height:1.7;color:rgba(255,230,150,0.9)}}
.rp-grid{{display:flex;flex-direction:column;gap:8px}}
.rp-item{{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:7px 10px;background:rgba(255,255,255,0.06);border-radius:var(--radius-xs);border:1px solid rgba(255,255,255,0.08)}}
.rp-left{{display:flex;flex-direction:column;gap:2px;flex:1}}.rp-phrase{{font-size:13px;font-weight:700;color:#fff}}.rp-trans{{font-size:11px;color:var(--text-sub);font-style:italic}}
.rp-play{{background:rgba(255,255,255,0.12);border:none;border-radius:50%;width:28px;height:28px;cursor:pointer;color:#fff;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background 0.15s}}
.rp-play:hover{{background:rgba(255,255,255,0.22)}}

/* ── 🧭 Navigator tab ── */
.nav-wrapper{{padding:0 0 20px}}
.nav-source{{margin:16px 20px 0;padding:10px 14px;background:rgba(255,255,255,0.07);border-radius:var(--radius-xs);border:1px solid rgba(255,255,255,0.1);font-size:12px;color:var(--text-sub);font-style:italic;text-align:center}}
.nav-phrase-wrap{{text-align:center;padding:24px 20px 18px}}
.nav-phrase{{font-size:38px;font-weight:900;line-height:1.2;letter-spacing:-1px;text-shadow:0 4px 24px rgba(0,0,0,0.5);word-break:break-word}}
.nav-phrase .pw{{transition:background 0.2s,color 0.2s,border-radius 0.2s,padding 0.2s;border-radius:6px}}
.nav-phrase .pw.hi{{background:rgba(255,255,255,0.9);color:{c0};padding:0 6px;box-shadow:0 2px 16px rgba(0,0,0,0.2)}}
.nav-roman{{font-size:16px;color:var(--text-sub);font-style:italic;margin-top:8px;letter-spacing:0.5px}}
.nav-controls{{display:flex;flex-direction:column;align-items:center;gap:14px;padding:0 20px 20px}}
.nav-play-btn{{display:flex;align-items:center;justify-content:center;gap:14px;width:100%;max-width:320px;padding:18px 28px;background:rgba(255,255,255,0.95);color:{c0};border:none;border-radius:var(--radius-sm);font-size:17px;font-weight:900;cursor:pointer;box-shadow:0 8px 32px rgba(0,0,0,0.35);transition:transform 0.15s,box-shadow 0.15s;letter-spacing:0.3px}}
.nav-play-btn:hover{{transform:scale(1.03);box-shadow:0 12px 40px rgba(0,0,0,0.45)}}.nav-play-btn:active{{transform:scale(0.97)}}
.nav-play-btn.playing{{background:rgba(255,255,255,0.85);animation:navPulse 1.2s ease-in-out infinite}}
@keyframes navPulse{{0%,100%{{box-shadow:0 8px 32px rgba(0,0,0,0.35)}}50%{{box-shadow:0 8px 40px rgba(255,255,255,0.2),0 0 0 6px rgba(255,255,255,0.1)}}}}
.nav-btn-icon{{font-size:22px;line-height:1}}.nav-btn-label{{font-size:16px}}
.nav-options{{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:10px 18px;width:100%}}
.rep-group{{display:flex;align-items:center;gap:6px}}.opt-label{{font-size:11px;color:var(--text-dim);font-weight:700;letter-spacing:0.5px}}
.rep-btn{{background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.14);color:rgba(255,255,255,0.65);border-radius:999px;padding:5px 12px;font-size:11px;font-weight:800;cursor:pointer;transition:background 0.15s,color 0.15s}}
.rep-btn.active{{background:rgba(255,255,255,0.22);color:#fff;border-color:rgba(255,255,255,0.3)}}
.loop-wrap{{display:flex;align-items:center;gap:7px;cursor:pointer;padding:5px 12px;background:rgba(255,255,255,0.08);border-radius:999px;border:1px solid rgba(255,255,255,0.14);transition:background 0.15s}}
.loop-wrap:hover,.loop-wrap.active{{background:rgba(255,255,255,0.18);border-color:rgba(255,255,255,0.28)}}
.loop-wrap input{{display:none}}.loop-label{{font-size:11px;font-weight:800;color:rgba(255,255,255,0.7);cursor:pointer;letter-spacing:0.3px}}
.loop-wrap.active .loop-label{{color:#fff}}

/* ── Word breakdown ── */
.wb-section{{margin:0 20px 16px;background:var(--glass-dark);border-radius:var(--radius-sm);border:1px solid var(--glass-border);padding:14px 16px}}
.wb-title{{font-size:10px;font-weight:900;letter-spacing:2px;text-transform:uppercase;color:var(--text-dim);margin-bottom:12px}}
.wb-list{{display:flex;flex-direction:column;gap:6px}}
.wb-row{{display:flex;align-items:center;gap:8px;padding:8px 10px;background:rgba(255,255,255,0.05);border-radius:var(--radius-xs);border:1px solid rgba(255,255,255,0.07)}}
.wb-row.hi-row{{background:rgba(255,255,255,0.12);border-color:rgba(255,255,255,0.2)}}
.wb-left{{display:flex;flex-direction:column;min-width:80px;flex-shrink:0}}
.wb-word{{font-size:16px;font-weight:800;color:#fff}}.wb-ph{{font-size:10px;color:var(--text-dim);font-style:italic;margin-top:1px}}
.wb-arrow{{color:var(--text-dim);font-size:13px;flex-shrink:0}}
.wb-trans{{flex:1;font-size:13px;color:var(--text-sub);font-weight:600}}
.wb-play{{background:rgba(255,255,255,0.1);border:none;border-radius:50%;width:26px;height:26px;cursor:pointer;color:#fff;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background 0.15s}}
.wb-play:hover{{background:rgba(255,255,255,0.22)}}

/* ── Footer ── */
.card-footer{{padding:10px 20px 14px;text-align:center;font-size:10px;color:var(--text-dim);letter-spacing:0.5px;border-top:1px solid rgba(255,255,255,0.06)}}
.confetti-canvas{{position:fixed;inset:0;pointer-events:none;z-index:9999;display:none;width:100%;height:100%}}
audio{{display:none!important}}
::-webkit-scrollbar{{width:3px}}::-webkit-scrollbar-thumb{{background:rgba(255,255,255,0.2);border-radius:3px}}
</style>
</head>
<body>
<div class="app">
  <div class="bg-layer"></div>
  <div class="particles">{particles_html}</div>
  <div class="card">

    <!-- ── Hero ── -->
    <div class="hero">
      <div class="lang-badge">
        <span class="lang-flag">{lang_flag}</span>
        <span>{lang_name}</span>
        <span class="lang-deco">{deco_emojis}</span>
      </div>
      <div class="phrase-text" id="phraseHero_{pid}">{phrase_spans}</div>
    </div>

    <!-- ── Tab bar ── -->
    <div class="tab-bar">
      <button class="tab-btn {'active' if start_tab=='learn' else ''}" data-tab="learn" id="tabLearn_{pid}">📚 Learn</button>
      <button class="tab-btn {'active' if start_tab=='nav' else ''}" data-tab="nav" id="tabNav_{pid}">🧭 Navigate</button>
    </div>

    <!-- ══ LEARN TAB ══ -->
    <div class="tab-pane {'active' if start_tab=='learn' else ''}" id="paneLearn_{pid}">

      <!-- Waveform -->
      <div class="waveform inner" id="wv_{pid}">{bars}</div>

      <!-- Controls -->
      <div class="controls">
        <button class="btn-play-all" id="btnAll_{pid}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0"><path d="M8 5v14l11-7z"/></svg>
          Play All Words
        </button>
        <div class="speed-toggle">
          <button class="speed-btn active" id="btnNorm_{pid}" data-speed="normal">Normal</button>
          <button class="speed-btn" id="btnSlow_{pid}" data-speed="slow">🐢 Slow</button>
        </div>
        <button class="btn-copy" id="btnCopy_{pid}" title="Copy phrase">
          <svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
          Copy
        </button>
      </div>

      <!-- Word cards -->
      <div class="words-label">{'🔤 Word by Word — tap a card for details' if multi else '🔤 Tap card for details'}</div>
      <div class="words-grid" id="wgrid_{pid}">{word_cards_html}</div>

      <!-- Full phrase player -->
      <div class="section-block">
        <div class="section-title">🎵 Full Phrase</div>
        <div class="phrase-player">
          <button class="phrase-play-btn" id="phrBtn_{pid}">
            <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>
          </button>
          <div class="progress-wrap" id="phrWrap_{pid}">
            <div class="progress-track"><div class="progress-fill" id="phrFill_{pid}"></div></div>
            <div class="time-row"><span id="phrCur_{pid}">0:00</span><span id="phrDur_{pid}">0:00</span></div>
          </div>
        </div>
      </div>

      <!-- Phonetic tip -->
      <div class="section-block">
        <div class="section-title">💡 Pronunciation Tips</div>
        <p class="tip-text">{tip}</p>
      </div>

      {fact_html}
      {related_html}
    </div><!-- /paneLearn -->

    <!-- ══ NAVIGATE TAB ══ -->
    <div class="tab-pane {'active' if start_tab=='nav' else ''}" id="paneNav_{pid}">
      <div class="nav-wrapper">
        {source_html}

        <!-- Giant phrase display -->
        <div class="nav-phrase-wrap">
          <div class="nav-phrase" id="navPhrase_{pid}">{phrase_spans}</div>
          {'<div class="nav-roman">'+nav_roman+'</div>' if nav_roman else ''}
        </div>

        <!-- Play controls -->
        <div class="nav-controls">
          <button class="nav-play-btn" id="navPlayBtn_{pid}">
            <span class="nav-btn-icon" id="navIcon_{pid}">▶</span>
            <span class="nav-btn-label" id="navLabel_{pid}">Play for Locals</span>
          </button>

          <div class="nav-options">
            <div class="rep-group">
              <span class="opt-label">Repeat</span>
              <button class="rep-btn active" data-n="1">1×</button>
              <button class="rep-btn" data-n="3">3×</button>
              <button class="rep-btn" data-n="5">5×</button>
            </div>
            <label class="loop-wrap" id="loopWrap_{pid}">
              <input type="checkbox" id="loopToggle_{pid}">
              <span class="loop-label">🔁 Loop</span>
            </label>
          </div>
        </div>

        <!-- Word breakdown -->
        {word_breakdown_html}
      </div>
    </div><!-- /paneNav -->

    <div class="card-footer">{lang_flag} {lang_name} Pronunciation Guide</div>
  </div><!-- /card -->
</div><!-- /app -->

<!-- Audio elements (phrase only — words use Web Speech API by default) -->
<audio id="phrNorm_{pid}" preload="auto" src="data:audio/mpeg;base64,{phrase_normal_b64}"></audio>
<audio id="phrSlow_{pid}" preload="auto" {'src="data:audio/mpeg;base64,'+phrase_slow_b64+'"' if has_slow_b64 else 'src=""'}></audio>
<div id="wordAudios_{pid}" style="display:none"></div>
<canvas class="confetti-canvas" id="confetti_{pid}"></canvas>

<script>
(function(){{
  var pid='{pid}', phrase='{phrase.replace(chr(39), chr(92)+chr(39))}';
  var wdata={words_json};
  var langCode='{lang_code}';
  var useSpeechAPI={use_speech_api_js};
  var hasSlowB64={has_slow_js};
  var speed='normal', playing=false, stopFlag=false, curIdx=-1;
  var navLooping=false, navRepeat=1, navPlaying=false;

  // DOM refs — Learn tab
  var wv=el('wv_'), btnAll=el('btnAll_'), btnNorm=el('btnNorm_'), btnSlow=el('btnSlow_');
  var phrBtn=el('phrBtn_'), phrFill=el('phrFill_'), phrCur=el('phrCur_'), phrDur=el('phrDur_');
  var phrWrap=el('phrWrap_'), phrNorm=el('phrNorm_'), phrSlow=el('phrSlow_');
  var wgrid=el('wgrid_'), btnCopy=el('btnCopy_');
  var cards=wgrid.querySelectorAll('.fc');
  var phraseHero=el('phraseHero_'), pws=phraseHero.querySelectorAll('.pw');

  // DOM refs — Navigate tab
  var navPlayBtn=el('navPlayBtn_'), navIcon=el('navIcon_'), navLabel=el('navLabel_');
  var navPhrase=el('navPhrase_'), navPws=navPhrase.querySelectorAll('.pw');
  var loopWrap=el('loopWrap_'), loopToggle=el('loopToggle_');
  var tabLearn=el('tabLearn_'), tabNav=el('tabNav_');
  var paneLearn=el('paneLearn_'), paneNav=el('paneNav_');

  function el(prefix){{return document.getElementById(prefix+pid)}}

  // ── Web Speech API (used ONLY for related-phrase buttons, not word chips) ──
  var synth=window.speechSynthesis||null;
  var hasSpeech=!!synth;

  function speakText(text,slow){{
    return new Promise(function(res){{
      if(!hasSpeech){{res();return;}}
      synth.cancel();
      setTimeout(function(){{
        var utt=new SpeechSynthesisUtterance(text);
        utt.lang=langCode; utt.rate=slow?0.65:1.0;
        utt.onend=function(){{res();}};
        utt.onerror=function(){{res();}};
        synth.speak(utt);
        setTimeout(function(){{res();}},3000);
      }},80);
    }});
  }}
  function stopSpeech(){{if(hasSpeech)synth.cancel();}}

  // ── Word audio elements — gTTS data-URIs, ALWAYS used for word chips ──
  // HARDCODED: word chips bypass the Speech API entirely.
  // Reason: any setTimeout() in the audio-trigger chain breaks the browser's
  // user-gesture propagation, causing Audio.play() to be blocked by autoplay
  // policy in cross-origin iframes (OpenWebUI embed context).
  // The full phrase audio works because phrNorm.play() is called directly in
  // the click handler with no intervening timeouts.  We replicate that exact
  // pattern here for every word chip.
  var wnorm=[], wslow=[];
  (function(){{
    var container=el('wordAudios_');
    wdata.forEach(function(w,i){{
      var an=new Audio('data:audio/mpeg;base64,'+(w.b64_normal||''));
      var as_=new Audio('data:audio/mpeg;base64,'+(w.b64_slow||''));
      an.preload='auto'; as_.preload='auto';
      container.appendChild(an); container.appendChild(as_);
      wnorm.push(an); wslow.push(as_);
    }});
  }})();

  // playWord — SYNCHRONOUS gTTS path only. Must be called directly in a
  // user-gesture handler (no setTimeout wrapper before this call).
  function playWord(i,slow,onDone){{
    var done=onDone||function(){{}};
    if(i<0||i>=wdata.length){{done();return;}}
    var a=slow?wslow[i]:wnorm[i];
    if(!a){{done();return;}}
    // Stop any other word audio first
    wnorm.forEach(function(x,j){{if(j!==i&&x){{x.pause();x.currentTime=0;}}}});
    wslow.forEach(function(x,j){{if(j!==i&&x){{x.pause();x.currentTime=0;}}}});
    a.currentTime=0;
    a.onended=function(){{a.onended=null;a.onerror=null;done();}};
    a.onerror=function(){{a.onerror=null;a.onended=null;done();}};
    a.play().catch(function(err){{
      // If gTTS play is also blocked (rare), fall back to Speech API
      console.warn('gTTS word play blocked, trying Speech API:',err);
      a.onended=null; a.onerror=null;
      if(hasSpeech){{
        synth.cancel();
        var utt=new SpeechSynthesisUtterance(wdata[i].word||'');
        utt.lang=langCode; utt.rate=slow?0.65:1.0;
        utt.onend=function(){{done();}};
        utt.onerror=function(){{done();}};
        synth.speak(utt);
      }}else{{done();}}
    }});
  }}

  // Promise wrapper for sequential playback (Play All Words)
  function playWordPromise(i,slow){{
    return new Promise(function(res){{playWord(i,slow,res);}});
  }}

  function stopWordAudio(){{
    stopSpeech();
    wnorm.forEach(function(a){{if(a){{a.pause();a.currentTime=0;}}}});
    wslow.forEach(function(a){{if(a){{a.pause();a.currentTime=0;}}}});
  }}

  function fmt(s){{if(!s||isNaN(s)||!isFinite(s))return'0:00';return Math.floor(s/60)+':'+(('0'+Math.floor(s%60)).slice(-2))}}
  function wave(on){{wv.classList.toggle('playing',on)}}
  function getPhrase(){{return speed==='slow'&&hasSlowB64?phrSlow:phrNorm}}

  // ── Word highlighting ──
  function hiWord(i){{
    pws.forEach(function(s){{s.classList.remove('hi')}});
    navPws.forEach(function(s){{s.classList.remove('hi')}});
    if(i>=0){{
      if(pws[i])pws[i].classList.add('hi');
      if(navPws[i])navPws[i].classList.add('hi');
    }}
    // also highlight wb-row
    document.querySelectorAll('#paneNav_'+pid+' .wb-row').forEach(function(r){{r.classList.remove('hi-row')}});
    var wbRows=document.querySelectorAll('#paneNav_'+pid+' .wb-row');
    if(wbRows[i])wbRows[i].classList.add('hi-row');
  }}

  function clearCards(){{cards.forEach(function(c){{c.classList.remove('playing-chip')}});curIdx=-1;hiWord(-1)}}
  function setCardPlaying(i){{clearCards();if(i>=0&&i<cards.length){{cards[i].classList.add('playing-chip');curIdx=i;hiWord(i)}}}}

  function stopAll(){{
    stopFlag=true; playing=false;
    stopWordAudio();
    phrNorm.pause(); phrNorm.currentTime=0;
    if(hasSlowB64){{phrSlow.pause(); phrSlow.currentTime=0;}}
    phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';
    phrFill.style.width='0%'; phrCur.textContent='0:00';
    wave(false); clearCards();
    btnAll.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Play All Words';
  }}

  function playWordAt(i){{
    return new Promise(function(res){{
      if(stopFlag||i>=wdata.length){{res();return;}}
      setCardPlaying(i); wave(true);
      playWordPromise(i,speed==='slow').then(function(){{
        if(!stopFlag){{clearCards();wave(false);}}
        res();
      }});
    }});
  }}

  function playPhraseAudio(slow){{
    return new Promise(function(res){{
      var useSpeechSlow=slow&&!hasSlowB64;
      if(useSpeechSlow){{
        speakText(phrase,true).then(res);
        return;
      }}
      var a=slow&&hasSlowB64?phrSlow:phrNorm;
      a.currentTime=0;
      wave(true);
      phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 6h12v12H6z"/></svg>';
      a.onended=function(){{
        a.onended=null;
        phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';
        phrFill.style.width='0%'; phrCur.textContent='0:00';
        wave(false); res();
      }};
      a.play().catch(res);
    }});
  }}

  // ── Play All (Learn tab) ──
  btnAll.addEventListener('click',function(){{
    if(playing){{stopAll();return}}
    stopFlag=false; playing=true;
    btnAll.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h12v12H6z"/></svg> Stop';
    getPhrase().pause();
    var seq=Promise.resolve();
    var gap=function(){{return new Promise(function(r){{setTimeout(r,280)}});}};
    wdata.forEach(function(_,i){{
      seq=seq.then(function(){{if(stopFlag)return;return playWordAt(i).then(gap);}});
    }});
    seq=seq.then(function(){{
      if(stopFlag)return;
      clearCards();
      return playPhraseAudio(speed==='slow');
    }});
    seq.then(function(){{
      if(!stopFlag){{
        playing=false; stopFlag=false;
        wave(false); clearCards();
        btnAll.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Play All Words';
        celebrate();
      }}
    }});
  }});

  // ── Flip card interactions ──
  cards.forEach(function(card,i){{
    var wab=card.querySelector('.wab');
    if(wab){{
      wab.addEventListener('click',function(e){{
        e.stopPropagation();
        var wasPlaying=(curIdx===i&&wnorm[i]&&!wnorm[i].paused);
        stopAll(); stopFlag=false;
        if(!wasPlaying){{
          setCardPlaying(i); wave(true);
          // Call playWord directly here — no Promise wrapper, no setTimeout,
          // so the user gesture is still active when a.play() is invoked.
          playWord(i,speed==='slow',function(){{clearCards();wave(false);}});
        }}
      }});
    }}
    var wabb=card.querySelector('.wab-back');
    if(wabb){{
      wabb.addEventListener('click',function(e){{
        e.stopPropagation();
        stopAll(); stopFlag=false;
        setCardPlaying(i); wave(true);
        playWord(i,speed==='slow',function(){{clearCards();wave(false);}});
      }});
    }}
    if(card.classList.contains('hb')){{
      card.addEventListener('click',function(e){{
        if(e.target.closest('.wab')||e.target.closest('.wab-back'))return;
        card.classList.toggle('flipped');
      }});
    }}
  }});

  // ── Full phrase player (Learn tab) ──
  phrBtn.addEventListener('click',function(){{
    if(playing)stopAll();
    var useSpeechSlow=speed==='slow'&&!hasSlowB64;
    if(useSpeechSlow){{
      wave(true);
      phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 6h12v12H6z"/></svg>';
      speakText(phrase,true).then(function(){{
        phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';
        wave(false);
      }});
      return;
    }}
    var a=getPhrase();
    if(a.paused||a.ended){{
      if(a.ended)a.currentTime=0;
      wave(true);
      phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 6h12v12H6z"/></svg>';
      a.play().catch(function(){{phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';wave(false)}});
    }}else{{
      a.pause();
      phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';
      wave(false);
    }}
  }});
  [phrNorm,phrSlow].forEach(function(a){{
    a.addEventListener('timeupdate',function(){{
      if(a===getPhrase()&&!a.paused){{
        var p=a.duration?(a.currentTime/a.duration*100):0;
        phrFill.style.width=p+'%'; phrCur.textContent=fmt(a.currentTime); phrDur.textContent=fmt(a.duration);
      }}
    }});
    a.addEventListener('ended',function(){{
      if(a===getPhrase()){{phrFill.style.width='0%';phrCur.textContent='0:00';
        phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';
        wave(false);
      }}
    }});
  }});
  phrWrap.addEventListener('click',function(e){{
    var a=getPhrase();if(!a.duration)return;
    var r=phrWrap.getBoundingClientRect();
    var p=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
    a.currentTime=p*a.duration; phrFill.style.width=(p*100)+'%';
  }});

  // ── Speed toggle ──
  [btnNorm,btnSlow].forEach(function(btn){{
    btn.addEventListener('click',function(){{
      var wasP=!(getPhrase().paused), wasT=getPhrase().currentTime;
      stopAll(); stopFlag=false;
      speed=btn.dataset.speed;
      btnNorm.classList.toggle('active',speed==='normal');
      btnSlow.classList.toggle('active',speed==='slow');
      if(wasP){{var a=getPhrase();a.currentTime=wasT;wave(true);
        phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 6h12v12H6z"/></svg>';
        a.play().catch(function(){{phrBtn.innerHTML='<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z"/></svg>';wave(false)}});
      }}
    }});
  }});

  // ── Copy button ──
  btnCopy.addEventListener('click',function(){{
    navigator.clipboard&&navigator.clipboard.writeText(phrase).then(function(){{
      btnCopy.classList.add('copied');
      btnCopy.querySelector('svg').style.display='none';
      btnCopy.childNodes[btnCopy.childNodes.length-1].textContent=' Copied!';
      setTimeout(function(){{
        btnCopy.classList.remove('copied');
        btnCopy.querySelector('svg').style.display='';
        btnCopy.childNodes[btnCopy.childNodes.length-1].textContent=' Copy';
      }},2000);
    }});
  }});

  // ── Related phrase play buttons ──
  document.querySelectorAll('#paneLearn_'+pid+' .rp-play').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      var p=btn.dataset.phrase;
      if(hasSpeech)speakText(p,false);
    }});
  }});

  // ── Tab switching ──
  [[tabLearn,paneLearn],[tabNav,paneNav]].forEach(function(pair){{
    pair[0].addEventListener('click',function(){{
      tabLearn.classList.remove('active'); tabNav.classList.remove('active');
      paneLearn.classList.remove('active'); paneNav.classList.remove('active');
      pair[0].classList.add('active'); pair[1].classList.add('active');
    }});
  }});

  // ── Navigator tab ──
  var navRepeatCount=1;
  document.querySelectorAll('#paneNav_'+pid+' .rep-btn').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      document.querySelectorAll('#paneNav_'+pid+' .rep-btn').forEach(function(b){{b.classList.remove('active')}});
      btn.classList.add('active');
      navRepeatCount=parseInt(btn.dataset.n)||1;
    }});
  }});

  loopWrap.addEventListener('click',function(){{
    navLooping=!navLooping;
    loopToggle.checked=navLooping;
    loopWrap.classList.toggle('active',navLooping);
  }});

  function setNavPlaying(on){{
    navPlaying=on;
    navPlayBtn.classList.toggle('playing',on);
    navIcon.textContent=on?'■':'▶';
    navLabel.textContent=on?'Stop':'Play for Locals';
  }}

  var navStopFlag=false;
  function navPlayLoop(){{
    if(navStopFlag){{setNavPlaying(false);return}}
    speakText(phrase,false).then(function(){{
      if(navStopFlag){{setNavPlaying(false);return}}
      if(navLooping){{
        setTimeout(navPlayLoop,600);
      }}else{{
        setNavPlaying(false);
      }}
    }});
  }}

  navPlayBtn.addEventListener('click',function(){{
    if(navPlaying){{
      navStopFlag=true;
      stopSpeech();
      // also stop gTTS phrase
      phrNorm.pause(); phrNorm.currentTime=0;
      setNavPlaying(false);
      return;
    }}
    navStopFlag=false;
    setNavPlaying(true);
    var remaining=navRepeatCount;
    function playNext(){{
      if(navStopFlag||remaining<=0){{setNavPlaying(false);return}}
      remaining--;
      // Use gTTS audio for main play (better quality)
      phrNorm.currentTime=0;
      phrNorm.onended=function(){{
        phrNorm.onended=null;
        if(navStopFlag){{setNavPlaying(false);return}}
        if(remaining>0||navLooping){{
          if(navLooping&&remaining<=0)remaining=1;
          setTimeout(playNext,500);
        }}else{{setNavPlaying(false)}}
      }};
      phrNorm.onerror=function(){{
        phrNorm.onerror=null;
        // fallback to speech
        speakText(phrase,false).then(function(){{
          if(navStopFlag){{setNavPlaying(false);return}}
          if(remaining>0||navLooping){{if(navLooping&&remaining<=0)remaining=1;setTimeout(playNext,500)}}
          else{{setNavPlaying(false)}}
        }});
      }};
      phrNorm.play().catch(function(){{
        // speech fallback
        speakText(phrase,false).then(function(){{
          if(navStopFlag){{setNavPlaying(false);return}}
          if(remaining>0||navLooping){{if(navLooping&&remaining<=0)remaining=1;setTimeout(playNext,500)}}
          else setNavPlaying(false);
        }});
      }});
    }}
    playNext();
  }});

  // Word breakdown play buttons (Navigate tab)
  document.querySelectorAll('#paneNav_'+pid+' .wb-play').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      var i=parseInt(btn.dataset.idx);
      hiWord(i);
      stopSpeech();
      // Direct gTTS call — user gesture is still live here
      playWord(i,false,function(){{hiWord(-1);}});
    }});
  }});

  // ── Confetti ──
  function celebrate(){{
    var canvas=document.getElementById('confetti_'+pid);
    canvas.style.display='block'; canvas.width=window.innerWidth; canvas.height=window.innerHeight;
    var ctx=canvas.getContext('2d');
    var colors=['#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7','#DDA0DD','#98FB98','#FFD700'];
    var pts=[];
    for(var i=0;i<120;i++){{
      pts.push({{x:Math.random()*canvas.width,y:-10-Math.random()*100,color:colors[~~(Math.random()*colors.length)],
        size:Math.random()*7+3,vx:(Math.random()-0.5)*4,vy:Math.random()*3+2,
        angle:Math.random()*360,spin:(Math.random()-0.5)*8,shape:Math.random()>0.5?'rect':'circle'}});
    }}
    var start=Date.now();
    function animate(){{
      ctx.clearRect(0,0,canvas.width,canvas.height);
      pts.forEach(function(p){{
        p.x+=p.vx;p.y+=p.vy;p.angle+=p.spin;p.vy+=0.05;
        ctx.save();ctx.translate(p.x,p.y);ctx.rotate(p.angle*Math.PI/180);
        ctx.fillStyle=p.color;
        if(p.shape==='rect')ctx.fillRect(-p.size/2,-p.size/2,p.size,p.size*0.6);
        else{{ctx.beginPath();ctx.arc(0,0,p.size/2,0,Math.PI*2);ctx.fill()}}
        ctx.restore();
      }});
      pts=pts.filter(function(p){{return p.y<canvas.height}});
      if(pts.length>0&&Date.now()-start<4000)requestAnimationFrame(animate);
      else canvas.style.display='none';
    }}
    requestAnimationFrame(animate);
  }}

  // ── Auto-height for OWUI iframe ──
  function reportH(){{window.parent.postMessage({{type:'iframe:resize',height:document.body.scrollHeight}},'*')}}
  window.addEventListener('load',reportH);
  new MutationObserver(reportH).observe(document.body,{{subtree:true,childList:true,attributes:true}});

  // ── Auto-play in navigator mode ──
  {'if(true){setTimeout(function(){navPlayBtn.click()},400);}' if navigator_mode else '// no autoplay'}

}})();
</script>
</body>
</html>"""
    return html


# ── Quick-pronounce HTML builder ────────────────────────────────────────────


def _build_quick_html(
    word: str,
    lang_code: str,
    lang_name: str,
    lang_flag: str,
    ipa: str,
    syllables: list[str],
    phonetic_syllables: list[str],
    romanization: str,
    tone: str,
    mnemonic: str,
    part_of_speech: str,
    translation: str,
    normal_b64: str,
    slow_b64: str,
) -> str:
    pid = uuid.uuid4().hex[:8]
    c0, c1 = LANGUAGE_GRADIENTS.get(lang_code, DEFAULT_GRADIENT)
    cultural_emojis = CULTURAL_EMOJIS.get(lang_code, CULTURAL_EMOJIS["default"])
    deco = " ".join(cultural_emojis[:3])
    tip = PHONETIC_TIPS.get(lang_code, PHONETIC_TIPS["default"])
    is_cjk = lang_code in CJK_LANGS

    # Syllable pills — zip target syllable with English phonetic
    pill_pairs = []
    if syllables and phonetic_syllables:
        for s, p in zip(syllables, phonetic_syllables):
            pill_pairs.append((s, p))
    elif syllables:
        for s in syllables:
            pill_pairs.append((s, ""))
    elif romanization:
        pill_pairs.append((word, romanization))

    pills_html = ""
    for idx, (s, p) in enumerate(pill_pairs):
        hue = int(200 + idx * 47) % 360
        pills_html += (
            f'<div class="syl-pill" style="--h:{hue}">'
            f'<span class="syl-native">{s}</span>'
            + (f'<span class="syl-phon">{p}</span>' if p else "")
            + "</div>"
        )

    dots_html = ""
    for i in range(max(len(syllables) if syllables else 1, 1)):
        dots_html += (
            f'<span class="beat-dot" style="animation-delay:{i*0.18:.2f}s"></span>'
        )

    ipa_html = f'<div class="ipa-row">{ipa}</div>' if ipa else ""
    tone_html = f'<span class="badge-tone">{tone}</span>' if tone else ""
    pos_html = (
        f'<span class="badge-pos">{part_of_speech}</span>' if part_of_speech else ""
    )
    trans_html = f'<div class="trans-line">"{translation}"</div>' if translation else ""
    mnem_html = f'<div class="mnem-line">💡 {mnemonic}</div>' if mnemonic else ""
    roman_html = (
        f'<div class="roman-line">{romanization}</div>'
        if romanization and not is_cjk
        else ""
    )
    slow_src = f"data:audio/mpeg;base64,{slow_b64}" if slow_b64 else ""

    bars = "".join(
        f'<div class="qbar" style="animation-delay:{i*0.06:.2f}s;animation-duration:{0.5+(i%5)*0.09:.2f}s"></div>'
        for i in range(18)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--c0:{c0};--c1:{c1};--r:14px}}
html,body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:transparent}}
.qcard{{
  max-width:480px;margin:6px auto;padding:0;
  background:linear-gradient(135deg,rgba(0,0,0,0.45),rgba(0,0,0,0.28));
  border:1px solid rgba(255,255,255,0.13);
  border-radius:var(--r);
  backdrop-filter:blur(24px);
  color:#fff;
  overflow:hidden;
  animation:qIn 0.4s cubic-bezier(0.34,1.56,0.64,1);
  box-shadow:0 16px 48px rgba(0,0,0,0.5);
}}
@keyframes qIn{{from{{opacity:0;transform:translateY(10px) scale(0.97)}}to{{opacity:1;transform:none}}}}

/* ── Header strip ── */
.qhead{{
  background:linear-gradient(120deg,var(--c0),var(--c1));
  padding:12px 16px 10px;
  display:flex;align-items:center;justify-content:space-between;
  gap:10px;
}}
.qflag-name{{display:flex;align-items:center;gap:7px;font-size:11px;font-weight:900;letter-spacing:1.2px;text-transform:uppercase;opacity:0.92}}
.qflag{{font-size:18px;line-height:1}}
.qdeco{{font-size:13px;letter-spacing:2px;opacity:0.65}}

/* ── Word hero ── */
.qhero{{text-align:center;padding:20px 20px 10px}}
.qword{{font-size:46px;font-weight:900;letter-spacing:-1px;line-height:1.1;text-shadow:0 4px 20px rgba(0,0,0,0.45)}}
.roman-line{{font-size:14px;color:rgba(255,255,255,0.55);margin-top:4px;font-style:italic}}
.ipa-row{{font-size:15px;color:rgba(255,255,255,0.5);font-family:monospace;letter-spacing:0.5px;margin-top:3px}}
.badges{{display:flex;justify-content:center;gap:6px;margin-top:8px;flex-wrap:wrap}}
.badge-pos,.badge-tone{{font-size:9px;font-weight:800;letter-spacing:0.8px;text-transform:uppercase;border-radius:6px;padding:3px 8px}}
.badge-pos{{background:rgba(100,200,255,0.2);color:#a8daff}}
.badge-tone{{background:rgba(100,255,180,0.2);color:#a0ffd0}}
.trans-line{{font-size:13px;color:rgba(255,255,255,0.6);margin-top:6px;font-style:italic}}

/* ── Syllable pills ── */
.syl-strip{{
  display:flex;flex-wrap:wrap;justify-content:center;gap:8px;
  padding:14px 16px 6px;
}}
.syl-pill{{
  display:flex;flex-direction:column;align-items:center;gap:3px;
  background:rgba(255,255,255,0.07);
  border:1px solid rgba(255,255,255,0.12);
  border-radius:10px;padding:8px 14px;
  border-top:3px solid hsl(var(--h),70%,62%);
  min-width:52px;
}}
.syl-native{{font-size:17px;font-weight:800;color:#fff}}
.syl-phon{{font-size:11px;color:rgba(255,255,255,0.5);letter-spacing:0.3px;font-style:italic}}

/* ── Beat dots ── */
.beat-row{{display:flex;justify-content:center;gap:5px;padding:6px 0 2px}}
.beat-dot{{
  width:7px;height:7px;border-radius:50%;
  background:rgba(255,255,255,0.35);
  animation:beatPop 0.55s ease-in-out infinite alternate;
  animation-play-state:paused;
}}
.qwave-playing .beat-dot{{animation-play-state:running}}
@keyframes beatPop{{from{{transform:scale(0.6);opacity:0.3}}to{{transform:scale(1.3);opacity:1}}}}

/* ── Waveform ── */
.qwaveform{{
  display:flex;align-items:center;justify-content:center;gap:2px;
  height:22px;padding:8px 0 4px;opacity:0.3;transition:opacity 0.3s;
}}
.qwaveform.playing{{opacity:1}}
.qbar{{width:3px;border-radius:3px;background:rgba(255,255,255,0.9);height:3px;
  animation:qBounce ease-in-out infinite alternate;animation-play-state:paused}}
.qwaveform.playing .qbar{{animation-play-state:running}}
@keyframes qBounce{{from{{height:3px;opacity:0.4}}to{{height:18px;opacity:1}}}}

/* ── Controls ── */
.qcontrols{{display:flex;align-items:center;justify-content:center;gap:10px;padding:10px 16px 16px;flex-wrap:wrap}}
.qbtn{{
  display:inline-flex;align-items:center;gap:8px;
  border:none;border-radius:999px;font-size:13px;font-weight:900;cursor:pointer;
  padding:11px 22px;transition:transform 0.13s,box-shadow 0.13s;letter-spacing:0.2px;
}}
.qbtn-normal{{background:rgba(255,255,255,0.95);color:var(--c0);box-shadow:0 4px 18px rgba(0,0,0,0.3)}}
.qbtn-slow{{background:rgba(255,255,255,0.12);color:#fff;border:1px solid rgba(255,255,255,0.2)}}
.qbtn:hover{{transform:scale(1.05)}}.qbtn:active{{transform:scale(0.95)}}
.qbtn.active{{background:rgba(255,255,255,0.95);color:var(--c0);box-shadow:0 4px 18px rgba(0,0,0,0.3)}}
.qbtn-normal.playing{{animation:qPulse 1s ease-in-out infinite}}
@keyframes qPulse{{0%,100%{{box-shadow:0 4px 18px rgba(0,0,0,0.3)}}50%{{box-shadow:0 4px 28px rgba(255,255,255,0.2),0 0 0 4px rgba(255,255,255,0.08)}}}}

/* ── Mnemonic / tip ── */
.mnem-line{{
  margin:0 16px 14px;padding:10px 14px;
  background:rgba(255,220,130,0.08);border:1px solid rgba(255,220,130,0.15);
  border-radius:10px;font-size:11px;color:rgba(255,220,150,0.85);line-height:1.6;
}}
.qtip{{
  margin:0 16px 14px;padding:10px 14px;
  background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);
  border-radius:10px;font-size:10px;color:rgba(255,255,255,0.4);line-height:1.6;
}}

/* ── Footer ── */
.qfoot{{text-align:center;padding:6px 0 12px;font-size:9px;color:rgba(255,255,255,0.2);letter-spacing:0.5px}}
audio{{display:none!important}}
::-webkit-scrollbar{{width:3px}}::-webkit-scrollbar-thumb{{background:rgba(255,255,255,0.2)}}
</style>
</head>
<body>
<div class="qcard">

  <div class="qhead">
    <div class="qflag-name"><span class="qflag">{lang_flag}</span>{lang_name}</div>
    <div class="qdeco">{deco}</div>
  </div>

  <div class="qhero">
    <div class="qword">{word}</div>
    {roman_html}
    {ipa_html}
    <div class="badges">{pos_html}{tone_html}</div>
    {trans_html}
  </div>

  <div class="syl-strip" id="sstrip_{pid}">{pills_html}</div>
  <div class="beat-row qwave-playing" id="beats_{pid}">{dots_html}</div>

  <div class="qwaveform" id="qwv_{pid}">{bars}</div>

  <div class="qcontrols">
    <button class="qbtn qbtn-normal" id="qbtnN_{pid}">
      <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M8 5v14l11-7z"/></svg>
      Normal
    </button>
    {'<button class="qbtn qbtn-slow" id="qbtnS_'+pid+'"><svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M8 5v14l11-7z"/></svg>🐢 Slow</button>' if slow_src else ''}
  </div>

  {mnem_html}
  <div class="qtip">{tip}</div>
  <div class="qfoot">{lang_flag} {lang_name} quick pronunciation</div>
</div>

<audio id="qaN_{pid}" preload="auto" src="data:audio/mpeg;base64,{normal_b64}"></audio>
{'<audio id="qaS_'+pid+'" preload="auto" src="'+slow_src+'"></audio>' if slow_src else ''}

<script>
(function(){{
  var pid='{pid}';
  var wv=document.getElementById('qwv_'+pid);
  var beats=document.getElementById('beats_'+pid);
  var aN=document.getElementById('qaN_'+pid);
  var aS={'document.getElementById("qaS_"+pid)' if slow_src else 'null'};
  var btnN=document.getElementById('qbtnN_'+pid);
  var btnS={'document.getElementById("qbtnS_"+pid)' if slow_src else 'null'};

  function wave(on){{
    wv.classList.toggle('playing',on);
    beats.classList.toggle('qwave-playing',on);
  }}

  function playAudio(a,btn){{
    if(!a)return;
    // Stop both
    [aN,aS].forEach(function(x){{if(x){{x.pause();x.currentTime=0;}}}});
    [btnN,btnS].forEach(function(b){{if(b)b.classList.remove('playing','active');}});
    wave(true);
    if(btn)btn.classList.add('playing','active');
    a.currentTime=0;
    a.onended=function(){{a.onended=null;wave(false);if(btn)btn.classList.remove('playing','active');}};
    a.onerror=function(){{a.onerror=null;wave(false);if(btn)btn.classList.remove('playing','active');}};
    a.play().catch(function(){{wave(false);if(btn)btn.classList.remove('playing','active');}});
  }}

  btnN.addEventListener('click',function(){{
    if(btnN.classList.contains('playing')){{aN.pause();aN.currentTime=0;wave(false);btnN.classList.remove('playing','active');return;}}
    playAudio(aN,btnN);
  }});
  if(btnS){{
    btnS.addEventListener('click',function(){{
      if(btnS.classList.contains('playing')){{aS.pause();aS.currentTime=0;wave(false);btnS.classList.remove('playing','active');return;}}
      playAudio(aS,btnS);
    }});
  }}

  // Auto-play normal on load
  window.addEventListener('load',function(){{
    setTimeout(function(){{btnN.click();}},350);
  }});

  // Resize reporter for OWUI iframe
  function reportH(){{window.parent.postMessage({{type:'iframe:resize',height:document.body.scrollHeight}},'*')}}
  window.addEventListener('load',reportH);
  new MutationObserver(reportH).observe(document.body,{{subtree:true,childList:true,attributes:true}});
}})();
</script>
</body>
</html>"""
    return html


# ── Quick-pronounce emit ─────────────────────────────────────────────────────


async def _quick_pronounce_emit(
    word: str,
    language: str,
    ipa: str,
    syllables: list[str],
    phonetic_syllables: list[str],
    romanization: str,
    tone: str,
    mnemonic: str,
    part_of_speech: str,
    translation: str,
    __event_emitter__,
) -> str:
    await _status(__event_emitter__, "🔍 Resolving language…", False)
    try:
        lang_code, lang_name = _resolve_language(language)
    except ValueError as exc:
        await _status(__event_emitter__, f"❌ {exc}", True)
        return str(exc)

    lang_flag = LANGUAGE_FLAGS.get(lang_code, "🌐")
    word = word.strip()

    await _status(
        __event_emitter__, f"🎙️ Generating audio for {lang_flag} {lang_name}…", False
    )
    try:
        results = await asyncio.gather(
            _audio_b64_async(word, lang_code, False),
            _audio_b64_async(word, lang_code, True),
            return_exceptions=True,
        )

        def safe(val, slow):
            if isinstance(val, Exception):
                try:
                    return _audio_b64(word, lang_code, slow)
                except Exception:
                    return ""
            return val

        normal_b64 = safe(results[0], False)
        slow_b64 = safe(results[1], True)
    except Exception as exc:
        msg = f"❌ Audio failed: {exc}"
        await _status(__event_emitter__, msg, True)
        return msg

    await _status(__event_emitter__, "🎨 Building quick pronunciation card…", False)

    html = _build_quick_html(
        word=word,
        lang_code=lang_code,
        lang_name=lang_name,
        lang_flag=lang_flag,
        ipa=ipa,
        syllables=syllables,
        phonetic_syllables=phonetic_syllables,
        romanization=romanization,
        tone=tone,
        mnemonic=mnemonic,
        part_of_speech=part_of_speech,
        translation=translation,
        normal_b64=normal_b64,
        slow_b64=slow_b64,
    )

    if __event_emitter__:
        await __event_emitter__({"type": "embeds", "data": {"embeds": [html]}})

    await _status(
        __event_emitter__,
        f"✅ Quick pronunciation ready — {lang_flag} {lang_name}",
        True,
    )
    syl_display = (
        " · ".join(phonetic_syllables) if phonetic_syllables else " · ".join(syllables)
    )
    return (
        f'Quick pronunciation card for **"{word}"** in {lang_name} shown above.\n\n'
        f"**Sounds like:** {syl_display}"
        + (f"\n**IPA:** {ipa}" if ipa else "")
        + (f"\n**Mnemonic:** {mnemonic}" if mnemonic else "")
    )


# ── Status helper ───────────────────────────────────────────────────────────


async def _status(emitter, description: str, done: bool) -> None:
    if emitter is None:
        return
    await emitter(
        {
            "type": "status",
            "data": {"description": description, "done": done, "hidden": False},
        }
    )


# ── Core audio + HTML generation ────────────────────────────────────────────


async def _generate_and_emit(
    phrase: str,
    language: str,
    word_data: Optional[str],
    fun_fact: Optional[str],
    related_phrases: Optional[str],
    navigator_mode: bool,
    user_language: str,
    source_text: str,
    use_speech_api: bool,
    generate_slow_audio: bool,
    max_words: int,
    __event_emitter__,
) -> str:
    await _status(__event_emitter__, "🔍 Resolving language…", False)
    try:
        lang_code, lang_name = _resolve_language(language)
    except ValueError as exc:
        await _status(__event_emitter__, f"❌ {exc}", True)
        return str(exc)

    lang_flag = LANGUAGE_FLAGS.get(lang_code, "🌐")
    tip = PHONETIC_TIPS.get(lang_code, PHONETIC_TIPS["default"])
    cultural_emojis = CULTURAL_EMOJIS.get(lang_code, CULTURAL_EMOJIS["default"])

    parsed_word_data: list[dict] = []
    if word_data:
        try:
            parsed_word_data = json.loads(word_data)
        except Exception:
            parsed_word_data = []

    parsed_related: list[dict] = []
    if related_phrases:
        try:
            parsed_related = json.loads(related_phrases)
        except Exception:
            parsed_related = []

    phrase = phrase.strip()
    if lang_code in CJK_LANGS:
        raw_words = [phrase]
    else:
        raw_words = [w for w in phrase.split() if w]
    raw_words = raw_words[:max_words]
    word_count = len(raw_words)

    await _status(
        __event_emitter__, f"🎙️ Generating audio for {lang_flag} {lang_name}…", False
    )

    try:
        audio_tasks = [_audio_b64_async(phrase, lang_code, False)]
        if generate_slow_audio:
            audio_tasks.append(_audio_b64_async(phrase, lang_code, True))

        # Always generate per-word gTTS audio.
        # When use_speech_api=True the browser Speech API is tried first in JS,
        # but gTTS audio serves as a guaranteed fallback (iframe CSP, browser
        # policy, or the notorious cancel()→speak() race can all silently drop
        # Web Speech utterances).
        for w in raw_words:
            audio_tasks.append(_audio_b64_async(w, lang_code, False))
            audio_tasks.append(_audio_b64_async(w, lang_code, True))

        results = await asyncio.gather(*audio_tasks, return_exceptions=True)

        def safe(val, text, lc, slow):
            if isinstance(val, Exception):
                try:
                    return _audio_b64(text, lc, slow)
                except Exception:
                    return ""
            return val

        phrase_normal_b64 = safe(results[0], phrase, lang_code, False)
        idx = 1
        phrase_slow_b64 = ""
        if generate_slow_audio:
            phrase_slow_b64 = safe(results[idx], phrase, lang_code, True)
            idx += 1

        words_for_html: list[dict] = []
        for i, w in enumerate(raw_words):
            entry = dict(parsed_word_data[i]) if i < len(parsed_word_data) else {}
            entry["word"] = entry.get("word", w)
            # Always embed both gTTS word audio tracks
            entry["b64_normal"] = safe(results[idx], w, lang_code, False)
            idx += 1
            entry["b64_slow"] = safe(results[idx], w, lang_code, True)
            idx += 1
            words_for_html.append(entry)

    except Exception as exc:
        msg = f"❌ Audio generation failed: {exc}. Ensure container has internet access (gTTS calls Google)."
        await _status(__event_emitter__, msg, True)
        return msg

    await _status(__event_emitter__, "🎨 Building pronunciation player…", False)

    html = _build_player_html(
        phrase=phrase,
        lang_code=lang_code,
        lang_name=lang_name,
        lang_flag=lang_flag,
        words=words_for_html,
        phrase_normal_b64=phrase_normal_b64,
        phrase_slow_b64=phrase_slow_b64,
        tip=tip,
        fun_fact=fun_fact or "",
        related_phrases=parsed_related,
        cultural_emojis=cultural_emojis,
        navigator_mode=navigator_mode,
        use_speech_api=use_speech_api,
        user_language=user_language,
        source_text=source_text,
    )

    if __event_emitter__:
        await __event_emitter__({"type": "embeds", "data": {"embeds": [html]}})

    mode_label = "🧭 Navigator" if navigator_mode else "📚 Learn"
    await _status(
        __event_emitter__,
        f"✅ Ready — {word_count} word{'s' if word_count!=1 else ''} | {lang_flag} {lang_name} | {mode_label} mode",
        True,
    )
    return (
        f'Pronunciation guide for **"{phrase}"** in {lang_name} displayed above.\n\n'
        f"**Tabs:** 📚 Learn (flip-cards, IPA, mnemonics) · 🧭 Navigate (show to locals, word meanings)\n"
        f"**Controls:** Play All · 🐢 Slow · Copy · Loop · Repeat 1×/3×/5×\n\n"
        f"_{tip}_"
    )


# ── Tools class ─────────────────────────────────────────────────────────────


class Tools:
    """
    Language Pronunciation Guide + Travel Translator — v5 Quick Edition.

    Three tools:
    - quick_pronounce_word(): compact single-word banner with syllable pills,
      English phonetics, IPA, normal + slow audio, mnemonic. Fast and focused.
    - pronounce(): full learning experience with flip-cards and cultural theming.
    - translate_and_play(): instant travel tool for "how do I say X in Y" queries.
    """

    def __init__(self):
        self.valves = self.Valves()

    class Valves(BaseModel):
        max_words: int = Field(
            default=14,
            description="Maximum word chips to render.",
        )
        word_audio_mode: str = Field(
            default="speech_api",
            description=(
                "'speech_api' = use browser Web Speech API for word chips (zero bandwidth, instant). "
                "'gtts' = generate high-quality gTTS audio for every word (more bandwidth)."
            ),
        )
        generate_slow_audio: bool = Field(
            default=False,
            description=(
                "If False (default), slow mode uses browser speech synthesis at 0.65× rate (zero bandwidth). "
                "If True, generates a separate gTTS slow audio file for the full phrase."
            ),
        )

    async def pronounce(
        self,
        phrase: str,
        language: str,
        word_data: Optional[str] = None,
        fun_fact: Optional[str] = None,
        related_phrases: Optional[str] = None,
        user_language: str = "English",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Generate an interactive pronunciation guide for any word or phrase.

        Renders a dual-tab player:
        - 📚 Learn tab: flip-card word chips (IPA, translation, POS, syllables, mnemonic,
          example sentence), sequential Play All with word highlighting, speed toggle,
          full-phrase seekable player, phonetic tips, fun fact, related phrases with audio.
        - 🧭 Navigate tab: giant phrase display for showing to locals, one-tap autoplay,
          loop & repeat controls, word-by-word meaning breakdown.

        ALWAYS provide word_data for the richest experience.

        :param phrase: The word or phrase to learn (e.g. "merci beaucoup").
        :param language: Language name ("French") or BCP-47 code ("fr", "zh-CN").
        :param word_data: JSON array — one object per word:
            {
              "word": str,               # word as written
              "translation": str,        # meaning in user_language
              "ipa": str,                # IPA e.g. /mɛʁ.si/
              "romanization": str,       # for non-Latin scripts
              "part_of_speech": str,     # noun / verb / adjective / etc.
              "syllables": [str],        # e.g. ["mer","ci"]
              "difficulty": int,         # 1–5 (1=easy, 5=very hard)
              "mnemonic": str,           # memory trick
              "example": str,            # example sentence in target language
              "example_translation": str,# example sentence in user_language
              "formality": str,          # "formal" | "informal" | "neutral"
              "gender": str,             # "masculine" | "feminine" | "neuter"
              "tone": str                # for tonal languages, e.g. "tone 2"
            }
        :param fun_fact: Interesting cultural or linguistic fact.
        :param related_phrases: JSON array: [{"phrase": str, "translation": str}, ...] (up to 6).
        :param user_language: The user's native language for word meaning explanations
            (default "English"). Provide translations in this language inside word_data.
        """
        return await _generate_and_emit(
            phrase=phrase,
            language=language,
            word_data=word_data,
            fun_fact=fun_fact,
            related_phrases=related_phrases,
            navigator_mode=False,
            user_language=user_language,
            source_text="",
            use_speech_api=(self.valves.word_audio_mode == "speech_api"),
            generate_slow_audio=self.valves.generate_slow_audio,
            max_words=self.valves.max_words,
            __event_emitter__=__event_emitter__,
        )

    async def quick_pronounce_word(
        self,
        word: str,
        language: str,
        ipa: str = "",
        syllables: Optional[str] = None,
        phonetic_syllables: Optional[str] = None,
        romanization: str = "",
        tone: str = "",
        mnemonic: str = "",
        part_of_speech: str = "",
        translation: str = "",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        USE THIS TOOL for single-word pronunciation requests: "how do I say X",
        "how do you pronounce X in Y", "what does X sound like".

        Renders a compact, focused pronunciation banner — NOT the full flip-card
        player. Shows the word large, syllable pills with English phonetic
        spellings (e.g. "ko · nee · chee · wa"), IPA, normal + slow audio
        buttons (auto-plays on load), and a memory mnemonic. No tabs, no cards.

        YOU must provide:
        - ipa: full IPA transcription e.g. "/koɲitɕiwa/"
        - syllables: JSON array of syllables in target script e.g. ["こん","に","ち","は"]
        - phonetic_syllables: JSON array of English phonetic approximations,
          one per syllable e.g. ["kon","nee","chee","wa"].
          Use hyphens for sub-syllable stress: "koh-n", "nee", "chee", "wah"
          This is the "English speaker sounds it out" spelling — be creative
          and helpful: Spanish "rr" → "rrr (trill)", French "eu" → "uh (lips rounded)"
        - romanization: full romanized form if non-Latin script e.g. "konnichiwa"
        - tone: tonal language marker e.g. "tone 3 (dip-rise)" for Mandarin
        - mnemonic: a vivid memory trick e.g. "Sounds like 'cone + knee + chee + wah'"
        - part_of_speech: "greeting", "noun", "verb" etc.
        - translation: meaning in user's language e.g. "Hello / Good afternoon"

        :param word: The single word in target language script e.g. "こんにちは"
        :param language: Language name or BCP-47 code e.g. "Japanese" or "ja"
        :param ipa: IPA transcription e.g. "/koɲitɕiwa/"
        :param syllables: JSON array of syllables e.g. '["kon","ni","chi","wa"]'
        :param phonetic_syllables: JSON array of English phonetics e.g. '["kohn","nee","chee","wah"]'
        :param romanization: Romanized spelling for non-Latin scripts
        :param tone: Tone marker for tonal languages
        :param mnemonic: Memory trick / sound-alike phrase
        :param part_of_speech: Grammatical category
        :param translation: Meaning in user's language
        """
        parsed_syl = []
        if syllables:
            try:
                parsed_syl = json.loads(syllables)
            except Exception:
                parsed_syl = [s.strip() for s in syllables.split(",") if s.strip()]

        parsed_phon = []
        if phonetic_syllables:
            try:
                parsed_phon = json.loads(phonetic_syllables)
            except Exception:
                parsed_phon = [
                    s.strip() for s in phonetic_syllables.split(",") if s.strip()
                ]

        return await _quick_pronounce_emit(
            word=word,
            language=language,
            ipa=ipa,
            syllables=parsed_syl,
            phonetic_syllables=parsed_phon,
            romanization=romanization,
            tone=tone,
            mnemonic=mnemonic,
            part_of_speech=part_of_speech,
            translation=translation,
            __event_emitter__=__event_emitter__,
        )

    async def translate_and_play(
        self,
        source_text: str,
        translated_phrase: str,
        language: str,
        word_data: Optional[str] = None,
        fun_fact: Optional[str] = None,
        related_phrases: Optional[str] = None,
        user_language: str = "English",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        USE THIS TOOL when the user asks "how do I say X in Y language" or any
        request to translate a phrase for use in a foreign country.

        Renders the player starting on the 🧭 Navigate tab (optimised for showing
        to locals) with autoplay, and shows the original source text so the user
        remembers what they asked for. The Learn tab remains accessible for
        deeper study.

        You (the LLM) MUST translate source_text into translated_phrase BEFORE
        calling this tool. Also generate word_data with translations in user_language.

        :param source_text: The original phrase in the user's language
            e.g. "Where is the nearest pharmacy?"
        :param translated_phrase: Your translation into the target language
            e.g. "最寄りの薬局はどこですか？"
        :param language: Target language name or BCP-47 code.
        :param word_data: Same schema as pronounce() — translations MUST be in user_language.
        :param fun_fact: A travel or cultural tip relevant to the phrase.
        :param related_phrases: Useful companion phrases in target language.
        :param user_language: The user's native language (default "English").
            Determines language of all word explanations shown in the Navigate tab.
        """
        return await _generate_and_emit(
            phrase=translated_phrase,
            language=language,
            word_data=word_data,
            fun_fact=fun_fact,
            related_phrases=related_phrases,
            navigator_mode=True,
            user_language=user_language,
            source_text=source_text,
            use_speech_api=(self.valves.word_audio_mode == "speech_api"),
            generate_slow_audio=self.valves.generate_slow_audio,
            max_words=self.valves.max_words,
            __event_emitter__=__event_emitter__,
        )
