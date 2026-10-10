"""
Fonts and low-level text drawing for the scanline engine.

- Font lookup by style (bubble/bold/thought/narration) with custom fonts from
  assets/fonts/ first, then system Noto/IPA fallbacks
- Per-character fallback to a symbol font for glyphs the main font lacks
- Outline (stroke) drawing for free text
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw, ImageFont

from yomeru.core.paths import FONTS_DIR

_FONTS_DIR = FONTS_DIR

_IPA_FONT = Path("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf")
_IPA_ALT = Path("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf")
_NOTO_SANS = Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf")
_NOTO_BOLD = Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
_NOTO_CJK = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")

_FONT_STYLES: dict[str, list[Path]] = {
    "bold": [
        _FONTS_DIR / "ComicNeue-Bold.ttf",
        _FONTS_DIR / "Bangers-Regular.ttf",
        _FONTS_DIR / "AnimeAce-Bold.ttf",
        _FONTS_DIR / "BadaBoom BB.ttf",
        _NOTO_BOLD, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ],
    "regular": [
        _FONTS_DIR / "ComicNeue-Bold.ttf",
        _FONTS_DIR / "AnimeAce.ttf",
        _FONTS_DIR / "CC Wild Words Roman.ttf",
        _NOTO_SANS, _NOTO_CJK, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ],
    "thought": [
        _FONTS_DIR / "ComicNeue-Regular.ttf",
        _FONTS_DIR / "AnimeAce.ttf",
        _FONTS_DIR / "CC Wild Words Italic.ttf",
        _NOTO_SANS, _NOTO_CJK, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ],
    "narration": [
        _FONTS_DIR / "ComicNeue-Regular.ttf",
        _FONTS_DIR / "AnimeAce.ttf",
        _NOTO_SANS, _NOTO_CJK, _IPA_FONT, _IPA_ALT,
        Path("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ],
}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _discover_custom_fonts() -> list[Path]:
    """Discover all custom font files in assets/fonts/."""
    if not _FONTS_DIR.exists():
        return []
    return sorted(
        p for p in _FONTS_DIR.iterdir()
        if p.suffix.lower() in (".ttf", ".otf", ".ttc")
    )


def _get_font(style: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (style, size)
    if key in _font_cache:
        return _font_cache[key]
    candidates = list(_FONT_STYLES.get(style, _FONT_STYLES["regular"]))
    for p in _discover_custom_fonts():
        if p not in candidates:
            candidates.append(p)
    candidates += [
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


# ── symbol fallback ───────────────────────────────────────────────────────────

_SYMBOL_FONT_PATHS = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    _FONTS_DIR / "NotoSansCJK-Regular.ttc",
]

_symbol_font_cache: dict[int, ImageFont.FreeTypeFont | None] = {}
_notdef_signature: int | None = None


def _get_symbol_font(size: int) -> ImageFont.FreeTypeFont | None:
    """Get a fallback font for symbols/emoji not in the primary font."""
    if size in _symbol_font_cache:
        return _symbol_font_cache[size]
    for p in _SYMBOL_FONT_PATHS:
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                _symbol_font_cache[size] = f
                return f
            except Exception:
                continue
    _symbol_font_cache[size] = None
    return None


def _get_notdef_sig(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    """Get a signature of the .notdef glyph to detect missing characters."""
    global _notdef_signature
    if _notdef_signature is not None:
        return _notdef_signature
    # Render a character that definitely doesn't exist in the font
    from PIL import Image as _Img, ImageDraw as _ID
    img = _Img.new("L", (30, 30), 255)
    d = _ID.Draw(img)
    d.text((2, 2), "\U000E0000", font=font, fill=0)  # Tag character — never in display fonts
    import numpy as np
    _notdef_signature = int((np.array(img) < 128).sum())
    return _notdef_signature


def _is_symbol_char(ch: str) -> bool:
    """Check if a character is a symbol/emoji that might need a fallback font."""
    cp = ord(ch)
    # Common symbol Unicode ranges
    return (
        0x2600 <= cp <= 0x27BF  # Miscellaneous Symbols, Dingbats
        or 0x2500 <= cp <= 0x25FF  # Box Drawing, Geometric Shapes
        or 0x2190 <= cp <= 0x21FF  # Arrows
        or 0x1F300 <= cp <= 0x1FAFF  # Emoji/Symbols
        or 0x2700 <= cp <= 0x27BF  # Dingbats
        or 0xFE00 <= cp <= 0xFE0F  # Variation selectors
        or cp in (0x2665, 0x2661, 0x2605, 0x2606, 0x266A, 0x266B,  # ♥♡★☆♪♫
                  0x2764, 0x2763, 0x2660, 0x2666, 0x2663)  # ❤❣♠♦♣
    )


def _render_text_with_fallback(
    draw,
    pos: tuple[int, int],
    text: str,
    font,
    fill,
    size: int,
    outline_color=None,
    outline_width: int = 0,
):
    """Render text using primary font, falling back to symbol font for special chars."""
    # Quick check: if no symbols, render normally
    if not any(_is_symbol_char(ch) for ch in text):
        if outline_color and outline_width > 0:
            _draw_text_with_outline(draw, pos, text, font, fill, outline_color, outline_width)
        else:
            draw.text(pos, text, font=font, fill=fill)
        return

    # Has symbols — render character by character with font switching
    sym_font = _get_symbol_font(size)
    x, y = pos
    for ch in text:
        use_font = sym_font if (_is_symbol_char(ch) and sym_font) else font
        if outline_color and outline_width > 0:
            _draw_text_with_outline(draw, (x, y), ch, use_font, fill, outline_color, outline_width)
        else:
            draw.text((x, y), ch, font=use_font, fill=fill)
        x += int(use_font.getlength(ch))


# ── outline drawing ───────────────────────────────────────────────────────────

def _spaced_line_width(text: str, font, spacing: int) -> int:
    """Compute total width of text rendered with letter spacing."""
    if not text:
        return 0
    total = 0
    for ch in text:
        total += int(font.getlength(ch)) + spacing
    return total - spacing  # no trailing space


def _draw_text_spaced(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font,
    fill: tuple[int, int, int],
    outline_color: tuple[int, int, int] | None,
    outline_width: int,
    spacing: int,
    size: int = 20,
) -> None:
    """Draw text character by character with extra spacing and symbol fallback."""
    x, y = pos
    sym_font = _get_symbol_font(size) if any(_is_symbol_char(ch) for ch in text) else None
    for ch in text:
        use_font = sym_font if (_is_symbol_char(ch) and sym_font) else font
        if outline_color and outline_width > 0:
            _draw_text_with_outline(draw, (x, y), ch, use_font, fill, outline_color, outline_width)
        else:
            draw.text((x, y), ch, font=use_font, fill=fill)
        x += int(use_font.getlength(ch)) + spacing


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
    outline_color: tuple[int, int, int],
    outline_width: int = 2,
) -> None:
    """Draw text with an outline (stroke) for legibility."""
    x, y = pos
    # Draw outline using circular distance for smooth coverage
    ow_sq = (outline_width + 0.5) ** 2
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            if dx * dx + dy * dy > ow_sq:
                continue  # Circular clip for smooth outline
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Draw fill on top
    draw.text((x, y), text, font=font, fill=fill)


# ── vertical text ─────────────────────────────────────────────────────────────
