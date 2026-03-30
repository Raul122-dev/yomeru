"""
PIL rendering backend.

Uses PIL (Pillow) for text drawing with pyphen for language-aware
syllabic hyphenation. Pure Python — no GPU required.

Font resolution, line-breaking algorithm, and vertical text support
are fully documented in SPEC.md.
"""
from __future__ import annotations
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── font registry ─────────────────────────────────────────────────────────────

_FONTS_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"

# ── font paths ────────────────────────────────────────────────────────────────
#
# Priority order for all styles:
#   1. Custom fonts in assets/fonts/  (user-uploaded or manually added)
#   2. Noto Sans  — best multilingual coverage (Latin, CJK, Arabic, etc.)
#   3. IPA Gothic — Japanese-specific (hiragana/katakana/kanji)
#   4. System fallbacks (DejaVu, Liberation, Carlito)
#
# Recommended fonts to place in assets/fonts/:
#   Manga/manhwa (speech):    AnimeAce.ttf      — free, dafont.com
#   Manga/manhwa (action):    Bangers-Regular.ttf — Google Fonts OFL
#   Alternative speech:       CC Wild Words.ttf  — comic standard
#   Alternative bold:         BadaBoom BB.ttf    — Blambot, free personal
#   Multilingual/CJK:         NotoSansCJK-Regular.ttf — Google Noto
#   (all non-CJK languages are covered by Noto Sans itself)

_IPA_FONT  = Path("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf")
_IPA_ALT   = Path("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf")
_NOTO_SANS = Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf")
_NOTO_BOLD = Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
_NOTO_CJK  = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")

_FONT_STYLES: dict[str, list[Path]] = {
    # bold — action, SFX, shouting
    "bold": [
        _FONTS_DIR / "Bangers-Regular.ttf",
        _FONTS_DIR / "AnimeAce-Bold.ttf",
        _FONTS_DIR / "BadaBoom BB.ttf",
        _FONTS_DIR / "CC Wild Words Bold.ttf",
        _NOTO_BOLD, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ],
    # regular — normal speech bubbles
    "regular": [
        _FONTS_DIR / "AnimeAce.ttf",
        _FONTS_DIR / "CC Wild Words Roman.ttf",
        _FONTS_DIR / "manga.ttf",
        _NOTO_SANS, _NOTO_CJK, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ],
    # thought — internal monologue, thought bubbles
    "thought": [
        _FONTS_DIR / "AnimeAce.ttf",
        _FONTS_DIR / "CC Wild Words Italic.ttf",
        _NOTO_SANS, _NOTO_CJK, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ],
    # narration — caption boxes, narrator text
    "narration": [
        _FONTS_DIR / "AnimeAce.ttf",
        _NOTO_SANS, _NOTO_CJK, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ],
}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_font(style: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (style, size)
    if key in _font_cache:
        return _font_cache[key]
    candidates = list(_FONT_STYLES.get(style, _FONT_STYLES["regular"])) + [
        Path("/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    ]
    for p in candidates:
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                _font_cache[key] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def _tone_to_style(tone: str, bubble_type: str, font_style: str | None = None) -> str:
    if font_style and font_style.lower() in _FONT_STYLES:
        return font_style.lower()
    bt = (bubble_type or "").lower()
    if bt in ("thought", "internal"):
        return "thought"
    if bt == "narration":
        return "narration"
    if any(w in (tone or "").lower() for w in ("shout", "scream", "yell")):
        return "bold"
    return "regular"


def _lw(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    """Pixel width of a single-line string."""
    try:
        return int(font.getlength(text))  # type: ignore[attr-defined]
    except AttributeError:
        try:
            bb = font.getbbox(text)  # type: ignore[attr-defined]
            return int(bb[2] - bb[0])
        except Exception:
            return len(text) * 8


def _lh(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size: int) -> int:
    try:
        asc, desc = font.getmetrics()  # type: ignore[attr-defined]
        return asc + abs(desc) + 2
    except Exception:
        return size + 4


def _split_hint(hint: str) -> list[str]:
    """
    Split a line_break_hint on newlines.
    Handles both actual \\n (from JSON) and literal backslash-n written by the model.
    """
    # normalize literal \\n sequences the model might write
    normalized = hint.replace("\\n", "\n").replace(r"\n", "\n")
    return [l.strip() for l in normalized.split("\n") if l.strip()]


def _clean_text(text: str) -> str:
    """
    Remove embedded newlines from text_translated.
    If the model put newlines in the text, extract them as a hint instead.
    Returns the cleaned text (newlines → spaces).
    """
    return re.sub(r"[\n\r\\n]+", " ", text).strip()


def _extract_embedded_breaks(text: str) -> tuple[str, list[str] | None]:
    """
    If text contains embedded newlines (\\n or actual), extract them as a line list.
    Returns (clean_text, lines_or_None).
    """
    normalized = text.replace("\\n", "\n").replace(r"\n", "\n")
    if "\n" in normalized:
        lines = [l.strip() for l in normalized.split("\n") if l.strip()]
        clean = " ".join(lines)
        return clean, lines
    return text, None


# ── hyphenation ───────────────────────────────────────────────────────────────

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


_LANG_MAP = {
    "English":               "en_US",
    "Spanish":               "es",
    "Portuguese":            "pt",
    "French":                "fr",
    "German":                "de",
    "Italian":               "it",
    "Japanese":              None,
    "Korean":                None,
    "Chinese (Simplified)":  None,
    "Chinese (Traditional)": None,
    "auto":                  "en_US",
}


def _split_word_punct(word: str) -> tuple[str, str, str]:
    """Split word into (leading_punct, alphabetic_root, trailing_punct)."""
    i = 0
    while i < len(word) and not (word[i].isalpha() or word[i].isdigit()):
        i += 1
    j = len(word)
    while j > i and not (word[j-1].isalpha() or word[j-1].isdigit()):
        j -= 1
    return word[:i], word[i:j], word[j:]


def _try_hyphenate(
    word: str,
    hyph: "object | None",
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    box_w: int,
) -> tuple[str, str]:
    """
    Try to hyphenate a word that is too wide for one line.
    Strips leading/trailing punctuation before calling pyphen so that
    characters like ¿, !, ? don't confuse syllabic positions.
    Returns (prefix_with_hyphen, remaining) or ("", word) if no break.
    """
    if hyph is None:
        return "", word
    lead, root, trail = _split_word_punct(word)
    if not root:
        return "", word
    parts = hyph.positions(root)  # type: ignore[attr-defined]
    # try longest prefix that fits first; lead punctuation (¿, ¡) stays in prefix only
    for pos in reversed(parts):
        prefix = lead + root[:pos] + "-"
        remaining = root[pos:] + trail   # no lead in remaining — it belonged to the opening syllable
        if _lw(prefix, font) <= box_w:
            return prefix, remaining
    return "", word


def _wrap_with_hyphenation(
    text: str,
    box_w: int,
    max_lines: int,
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    lang_code: str | None,
) -> list[str] | None:
    """
    Wrap text fitting within box_w pixels using at most max_lines lines.
    Uses pyphen for language-aware syllabic hyphenation on words with stripped
    leading/trailing punctuation (¿, !, ?, etc.) so breaks are always correct.
    Guarantees no words are lost — overflowing words are placed as-is.
    """
    hyph = _get_hyphenator(lang_code) if lang_code else None
    words = text.split()
    if not words:
        return None

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = (current + " " + word).strip() if current else word

        if _lw(candidate, font) <= box_w:
            current = candidate
            continue

        # word doesn't fit on current line — flush and try on new line
        if current:
            lines.append(current)
            if len(lines) >= max_lines:
                return None
            current = word
            if _lw(current, font) <= box_w:
                continue

        # word is too long even alone — try syllabic hyphenation
        prefix, remaining = _try_hyphenate(word, hyph, font, box_w)
        if prefix:
            lines.append(prefix)
            if len(lines) >= max_lines:
                return None
            current = remaining
            continue

        # no good hyphenation found — place word as-is (may overflow slightly)
        # IMPORTANT: at this point `current == word` (it was just assigned above).
        # Append current (== word) once, do NOT also append `word` separately.
        lines.append(current)
        if len(lines) >= max_lines:
            return None
        current = ""

    if current.strip():
        lines.append(current)

    lines = [l for l in lines if l.strip()]
    return lines if lines and len(lines) <= max_lines else None



# ── result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RenderResult:
    """Diagnostic information from a render attempt."""
    text: str
    status: str          # "ok" | "skip"
    skip_reason: str = ""
    lines: list[str] = field(default_factory=list)
    font_size: int = 0
    font_style: str = ""
    line_source: str = ""  # "hint" | "embedded" | "hyphen" | "word"
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    box_size: tuple[int, int] = (0, 0)

    def to_dict(self) -> dict:
        return {
            "text": self.text[:40],
            "status": self.status,
            "skip_reason": self.skip_reason,
            "lines": self.lines,
            "font_size": self.font_size,
            "font_style": self.font_style,
            "line_source": self.line_source,
            "bbox": list(self.bbox),
            "box_size": list(self.box_size),
        }


# ── main renderer ─────────────────────────────────────────────────────────────


def _is_vertical_bubble(bubble_w: int, bubble_h: int) -> bool:
    """Detect vertical text orientation — common in Japanese/Chinese manga."""
    return bubble_h > bubble_w * 2.0


def _render_vertical_text(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    x1: int, y1: int, x2: int, y2: int,
    pad: int,
    size: int,
    text_color: tuple[int, int, int],
) -> None:
    """
    Render text vertically (top-to-bottom, right-to-left columns).
    Each character is drawn individually, stacked vertically.
    Columns are arranged right-to-left to match Japanese reading order.
    """
    char_h = _lh(font, size)
    char_w = size  # approximate; Japanese chars are square

    # compute how many columns fit horizontally
    usable_w = x2 - x1 - pad * 2
    usable_h = y2 - y1 - pad * 2

    # flatten lines into one string (vertical text ignores soft line breaks)
    text = " ".join(lines).replace(" ", "")

    # compute column layout
    chars_per_col = max(1, usable_h // char_h)
    cols = [text[i:i+chars_per_col] for i in range(0, len(text), chars_per_col)]

    # draw right-to-left
    for col_idx, col in enumerate(reversed(cols)):
        col_x = x2 - pad - char_w - col_idx * (char_w + 2)
        if col_x < x1 + pad:
            break
        for row_idx, ch in enumerate(col):
            cy = y1 + pad + row_idx * char_h
            draw.text((col_x, cy), ch, font=font, fill=text_color)

def render_text_in_bubble(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    text: str,
    tone: str = "neutral",
    bubble_type: str = "speech",
    font_style: str | None = None,
    line_break_hint: str | None = None,
    source_language: str = "auto",
    padding: int = 10,
    min_font_size: int = 8,
    max_font_size: int = 30,
) -> tuple[Image.Image, RenderResult]:
    """
    Render translated text in a bubble region.
    Returns (image, RenderResult) — image unchanged on skip.
    """
    # clamp bbox
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(x1, image.width - 1))
    y1 = max(0, min(y1, image.height - 1))
    x2 = max(x1 + 1, min(x2, image.width))
    y2 = max(y1 + 1, min(y2, image.height))

    # extract any embedded newlines from text before passing to fit algorithm
    clean_text, embedded_lines = _extract_embedded_breaks(text)

    if not clean_text.strip():
        r = RenderResult(text=text, status="skip", skip_reason="empty_text", bbox=(x1,y1,x2,y2))
        print(f"  [render] SKIP '{text[:20]}' — empty", file=sys.stderr)
        return image, r

    bubble_w, bubble_h = x2 - x1, y2 - y1

    # adaptive padding: shrink proportionally so tiny bubbles keep usable text area
    if bubble_w < 50 or bubble_h < 35:
        pad = 2
        min_font_size = min(min_font_size, 6)
    elif bubble_w < 80 or bubble_h < 55:
        pad = max(3, padding // 4)
        min_font_size = min(min_font_size, 7)
    else:
        pad = padding

    box_w = bubble_w - pad * 2
    box_h = bubble_h - pad * 2

    if box_w < 6 or box_h < 6:
        reason = f"too_small_{bubble_w}x{bubble_h}px"
        r = RenderResult(text=text, status="skip", skip_reason=reason, bbox=(x1,y1,x2,y2), box_size=(box_w, box_h))
        print(f"  [render] SKIP '{clean_text[:20]}' — {reason}", file=sys.stderr)
        return image, r

    style = _tone_to_style(tone, bubble_type, font_style)
    lang_code = _LANG_MAP.get(source_language, "en_US")

    # text color from bubble interior
    import numpy as np
    arr = np.array(image)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    sample = arr[max(0, cy-12):min(image.height, cy+12), max(0, cx-12):min(image.width, cx+12), :3]
    text_color: tuple[int, int, int] = (0, 0, 0) if (float(sample.mean()) > 128 if sample.size > 0 else True) else (255, 255, 255)

    fit = _find_fit(
        text=clean_text,
        hint=line_break_hint,
        embedded_lines=embedded_lines,
        box_w=box_w,
        box_h=box_h,
        min_size=min_font_size,
        max_size=max_font_size,
        style=style,
        lang_code=lang_code,
    )

    if fit is None:
        reason = f"cannot_fit_in_{box_w}x{box_h}px"
        r = RenderResult(text=text, status="skip", skip_reason=reason, bbox=(x1,y1,x2,y2), box_size=(box_w, box_h))
        print(f"  [render] SKIP '{clean_text[:20]}' — {reason}", file=sys.stderr)
        return image, r

    size, lines, font, line_source = fit
    lh = _lh(font, size)
    total_h = len(lines) * lh
    start_y = y1 + pad + max(0, (box_h - total_h) // 2)

    img = image.copy()
    draw = ImageDraw.Draw(img)

    if _is_vertical_bubble(bubble_w, bubble_h):
        _render_vertical_text(draw, lines, font, x1, y1, x2, y2, pad, size, text_color)
    else:
        for i, line in enumerate(lines):
            lw = _lw(line, font)
            line_x = (x1 + x2) // 2 - lw // 2
            line_x = max(x1 + pad, min(line_x, x2 - pad - max(0, lw)))
            draw.text((line_x, start_y + i * lh), line, font=font, fill=text_color)

    r = RenderResult(
        text=clean_text, status="ok",
        lines=lines, font_size=size, font_style=style,
        line_source=line_source,
        bbox=(x1, y1, x2, y2), box_size=(box_w, box_h),
    )
    print(f"  [render] '{clean_text[:20]}' → {len(lines)}L {size}px {style} [{line_source}]", file=sys.stderr)
    return img, r




def _wrap_segments(
    segments: list[str],
    box_w: int,
    max_lines: int,
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    lang_code: str | None,
) -> list[str] | None:
    """
    Wrap text that has semantic break points (from embedded \n in text_translated).
    Each segment is a preferred visual unit. If a segment is too wide, it's
    further wrapped using hyphenation. Segment boundaries act as mandatory
    line breaks between units.
    """
    all_lines: list[str] = []
    for segment in segments:
        remaining = max_lines - len(all_lines)
        if remaining <= 0:
            return None
        seg_lines = _wrap_with_hyphenation(segment.strip(), box_w, remaining, font, lang_code)
        if seg_lines is None:
            return None
        all_lines.extend(seg_lines)
    return all_lines if len(all_lines) <= max_lines else None

def _hyphen_count(lines: list[str]) -> int:
    """Count lines that end with a hyphen (proxy for visual disruption)."""
    return sum(1 for l in lines if l.endswith("-"))


def _find_fit(
    text: str,
    hint: str | None,
    embedded_lines: list[str] | None,
    box_w: int,
    box_h: int,
    min_size: int,
    max_size: int,
    style: str,
    lang_code: str | None,
) -> "tuple[int, list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, str] | None":

    best: "tuple[int, list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, str] | None" = None

    for size in range(max_size, min_size - 1, -1):
        font = _get_font(style, size)
        lh = _lh(font, size)
        max_lines = max(1, box_h // lh)

        # 1. Embedded newlines in text_translated
        if embedded_lines:
            seg_lines = _wrap_segments(embedded_lines, box_w, max_lines, font, lang_code)
            if seg_lines is not None:
                return size, seg_lines, font, "embedded"

        # 2. Hyphenation-aware wrapping
        lines = _wrap_with_hyphenation(text, box_w, max_lines, font, lang_code)
        if lines is None:
            continue

        # Accept immediately if no hyphens needed (clean wrap)
        if _hyphen_count(lines) == 0:
            return size, lines, font, "hyphen"

        # Keep as candidate but continue scanning for a cleaner fit at smaller size
        if best is None:
            best = (size, lines, font, "hyphen")

    return best

# ── class wrapper (implements BaseRenderer protocol) ──────────────────────────

class PILRenderer:
    """PIL + pyphen text renderer. Implements the BaseRenderer protocol."""

    @property
    def name(self) -> str:
        return "pil"

    def render(
        self,
        image: Image.Image,
        bbox: tuple[int, int, int, int],
        text: str,
        tone: str = "neutral",
        bubble_type: str = "speech",
        font_style: str | None = None,
        source_language: str = "auto",
        padding: int = 10,
        min_font_size: int = 8,
        max_font_size: int = 30,
    ) -> "tuple[Image.Image, RenderResult]":
        """Render text into bubble. Returns (image_with_text, RenderResult)."""
        return render_text_in_bubble(
            image=image,
            bbox=bbox,
            text=text,
            tone=tone,
            bubble_type=bubble_type,
            font_style=font_style,
            source_language=source_language,
            padding=padding,
            min_font_size=min_font_size,
            max_font_size=max_font_size,
        )