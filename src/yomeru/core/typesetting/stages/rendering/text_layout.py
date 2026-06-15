# -*- coding: utf-8 -*-
"""
Text layout and wrapping engine.

Handles:
- Standard word-level wrapping with pyphen hyphenation
- CJK character-level line breaking (no spaces needed)
- Embedded newline hints from translation
- Binary search for optimal font size
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


# ── unicode ranges ─────────────────────────────────────────────────────────────

_CJK_RANGES = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x3000, 0x303F),    # CJK Symbols and Punctuation
    (0x3040, 0x309F),    # Hiragana
    (0x30A0, 0x30FF),    # Katakana
    (0xAC00, 0xD7AF),    # Hangul Syllables
    (0xFF00, 0xFFEF),    # Fullwidth Forms
    (0x20000, 0x2A6DF),  # CJK Extension B
]

# Characters that should not start a line (Japanese/CJK typographic rules)
_NO_START = set(
    "\u3001\u3002\uff0c\uff0e\u30fb\uff1a\uff1b\uff1f\uff01"  # 、。，．・：；？！
    "\u309b\u309c\u30fd\u30fe\u309d\u309e\u3005\u30fc"          # ゛゜ヽヾゝゞ々ー
    "\uff09\uff3d\uff5d\u3015\u3009\u300b\u300d\u300f"          # ）］｝〕〉》」』
    "\u3011\u3019\u3017\u301f\u2019\u201d\u00bb"                # 】〙〗〟'»"
    "\u30a1\u30a3\u30a5\u30a7\u30a9\u30c3\u30e3\u30e5"          # ァィゥェォッャュ
    "\u30e7\u30ee\u30f5\u30f6"                                   # ョヮヵヶ
    "\u3041\u3043\u3045\u3047\u3049\u3063\u3083\u3085\u3087\u308e"  # ぁぃぅぇぉっゃゅょゎ
)
# Characters that should not end a line
_NO_END = set(
    "\uff08\uff3b\uff5b\u3014\u3008\u300a\u300c\u300e"  # （［｛〔〈《「『
    "\u3010\u3018\u3016\u301d\u2018\u201c\u00ab"          # 【〘〖〝'«"
)


def is_cjk_text(text: str) -> bool:
    """Check if text is predominantly CJK (>50% CJK characters)."""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if _is_cjk_char(ch))
    return cjk_count > len(text) * 0.5


def _is_cjk_char(ch: str) -> bool:
    """Check if a character is in CJK unicode ranges."""
    cp = ord(ch)
    return any(start <= cp <= end for start, end in _CJK_RANGES)


# ── measurement helpers ────────────────────────────────────────────────────────

def measure_width(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    """Pixel width of a single-line string."""
    try:
        return int(font.getlength(text))
    except (AttributeError, UnicodeEncodeError):
        try:
            bb = font.getbbox(text)
            return int(bb[2] - bb[0])
        except Exception:
            # Fallback: estimate based on character count
            # CJK chars are roughly square, Latin chars are ~0.6x height
            return sum(14 if ord(c) > 0x2E80 else 8 for c in text)


def measure_line_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size: int) -> int:
    """Line height for a font at given size."""
    try:
        asc, desc = font.getmetrics()
        return asc + abs(desc) + 2
    except Exception:
        return size + 4


# ── hyphenation ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=8)
def _get_hyphenator(lang: str):
    try:
        import pyphen
        for code in (lang, lang.split("_")[0], lang.split("-")[0]):
            try:
                return pyphen.Pyphen(lang=code)
            except Exception:
                continue
    except ImportError:
        pass
    return None


LANG_MAP = {
    "English": "en_US",
    "Spanish": "es",
    "Portuguese": "pt_BR",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Dutch": "nl",
    "Russian": "ru",
    "Polish": "pl",
    "Turkish": "tr",
    "Indonesian": "id",
    "Thai": None,
    "Vietnamese": None,
    "Arabic": None,
    "Japanese": None,
    "Korean": None,
    "Chinese (Simplified)": None,
    "Chinese (Traditional)": None,
    "auto": "en_US",
}


# ── CJK line breaking ─────────────────────────────────────────────────────────

def wrap_cjk(
    text: str,
    box_w: int,
    max_lines: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> list[str] | None:
    """
    Wrap CJK text character-by-character respecting typographic rules.
    CJK text has no spaces — each character is a valid break point
    (with exceptions for punctuation that can't start/end lines).
    """
    # Remove spaces (CJK doesn't use them for layout)
    text = text.replace(" ", "")
    if not text:
        return None

    lines: list[str] = []
    current = ""

    for ch in text:
        candidate = current + ch

        if measure_width(candidate, font) <= box_w:
            current = candidate
            continue

        # Character doesn't fit — need to break
        if not current:
            # Single char too wide for box
            current = ch
            continue

        # Check kinsoku (typographic rules)
        if ch in _NO_START and current:
            # This char can't start next line → keep it on current
            lines.append(current + ch)
            current = ""
            if len(lines) >= max_lines:
                return None
            continue

        if current and current[-1] in _NO_END:
            # Last char of current can't end line → move it to next
            carry = current[-1]
            lines.append(current[:-1])
            current = carry + ch
        else:
            lines.append(current)
            current = ch

        if len(lines) >= max_lines:
            return None

    if current:
        lines.append(current)

    return lines if lines and len(lines) <= max_lines else None


# ── Latin/word-based wrapping ──────────────────────────────────────────────────

def _split_word_punct(word: str) -> tuple[str, str, str]:
    """Split word into (leading_punct, root, trailing_punct)."""
    i = 0
    while i < len(word) and not (word[i].isalpha() or word[i].isdigit()):
        i += 1
    j = len(word)
    while j > i and not (word[j - 1].isalpha() or word[j - 1].isdigit()):
        j -= 1
    return word[:i], word[i:j], word[j:]


def _try_hyphenate(
    word: str,
    hyph: object | None,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    box_w: int,
) -> tuple[str, str]:
    """Try syllabic hyphenation on a word that's too wide."""
    if hyph is None:
        return "", word
    lead, root, trail = _split_word_punct(word)
    if not root:
        return "", word
    parts = hyph.positions(root)  # type: ignore[attr-defined]
    for pos in reversed(parts):
        prefix = lead + root[:pos] + "-"
        remaining = root[pos:] + trail
        if measure_width(prefix, font) <= box_w:
            return prefix, remaining
    return "", word


def wrap_latin(
    text: str,
    box_w: int,
    max_lines: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    lang_code: str | None,
) -> list[str] | None:
    """
    Wrap Latin text (word-level) with optional hyphenation.
    Guarantees no words are lost.
    """
    hyph = _get_hyphenator(lang_code) if lang_code else None
    words = text.split()
    if not words:
        return None

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = (current + " " + word).strip() if current else word

        if measure_width(candidate, font) <= box_w:
            current = candidate
            continue

        if current:
            lines.append(current)
            if len(lines) >= max_lines:
                return None
            current = word
            if measure_width(current, font) <= box_w:
                continue

        # Word too long — try hyphenation
        prefix, remaining = _try_hyphenate(word, hyph, font, box_w)
        if prefix:
            lines.append(prefix)
            if len(lines) >= max_lines:
                return None
            current = remaining
            continue

        # No good break — place as-is
        lines.append(current)
        if len(lines) >= max_lines:
            return None
        current = ""

    if current.strip():
        lines.append(current)

    lines = [l for l in lines if l.strip()]
    return lines if lines and len(lines) <= max_lines else None


def wrap_segments(
    segments: list[str],
    box_w: int,
    max_lines: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    lang_code: str | None,
    is_cjk: bool = False,
) -> list[str] | None:
    """Wrap text with mandatory break points (from embedded newlines)."""
    all_lines: list[str] = []
    for segment in segments:
        remaining = max_lines - len(all_lines)
        if remaining <= 0:
            return None
        if is_cjk:
            seg_lines = wrap_cjk(segment.strip(), box_w, remaining, font)
        else:
            seg_lines = wrap_latin(segment.strip(), box_w, remaining, font, lang_code)
        if seg_lines is None:
            return None
        all_lines.extend(seg_lines)
    return all_lines if len(all_lines) <= max_lines else None


# ── unified wrapping ───────────────────────────────────────────────────────────

def wrap_text(
    text: str,
    box_w: int,
    max_lines: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    lang_code: str | None,
) -> list[str] | None:
    """
    Auto-detect CJK vs Latin and wrap accordingly.
    """
    if is_cjk_text(text):
        return wrap_cjk(text, box_w, max_lines, font)
    return wrap_latin(text, box_w, max_lines, font, lang_code)


# ── text cleaning ──────────────────────────────────────────────────────────────

def extract_embedded_breaks(text: str) -> tuple[str, list[str] | None]:
    """
    If text contains embedded newlines, extract them as a line list.
    Returns (clean_text, lines_or_None).
    """
    normalized = text.replace("\\n", "\n").replace(r"\n", "\n")
    if "\n" in normalized:
        lines = [l.strip() for l in normalized.split("\n") if l.strip()]
        clean = " ".join(lines)
        return clean, lines
    return text, None


def hyphen_count(lines: list[str]) -> int:
    """Count lines ending with hyphens."""
    return sum(1 for l in lines if l.endswith("-"))
