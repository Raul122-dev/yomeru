"""
Fonts and low-level text drawing for the scanline engine.

- One font file per lettering style (regular, bold, thought, narration, sfx):
  the run's choice (settings → rendering.fonts) or the default of the drawn
  language's script (core.languages.SCRIPT_FONTS). Files are looked up among
  the user's fonts (data/fonts) first, then the shipped ones (assets/fonts).
- Per-character fallback to a symbol font for glyphs the main font lacks
- Outline (stroke) drawing for free text
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from PIL import ImageDraw, ImageFont

from yomeru.core.languages import FONT_STYLES, SCRIPT_FONTS
from yomeru.core.paths import FONTS_DIR, USER_FONTS_DIR

_FONTS_DIR = FONTS_DIR
FONT_EXTS = (".ttf", ".otf", ".ttc")


def find_font(name: str) -> Path | None:
    """A font file by name: the user's fonts first, then the shipped ones."""
    for d in (USER_FONTS_DIR, FONTS_DIR):
        p = d / Path(name).name
        if p.is_file():
            return p
    return None


def resolve_fonts(choices: dict[str, str] | None, script: str = "latin") -> dict[str, str]:
    """Font file per style for one render: the chosen file when it exists,
    else the script's default, else the Latin default."""
    defaults = SCRIPT_FONTS.get(script) or SCRIPT_FONTS["latin"]
    out = {}
    for style in FONT_STYLES:
        for name in ((choices or {}).get(style), defaults.get(style), SCRIPT_FONTS["latin"][style]):
            p = find_font(name) if name else None
            if p is not None:
                out[style] = str(p)
                break
    return out


_active: ContextVar[dict[str, str] | None] = ContextVar("yomeru_fonts", default=None)


@contextmanager
def use_fonts(fonts: dict[str, str] | None):
    """Fonts for everything drawn inside the block (one render)."""
    token = _active.set(fonts or None)
    try:
        yield
    finally:
        _active.reset(token)


_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_font(style: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts = _active.get() or resolve_fonts(None)
    path = fonts.get(style) or fonts.get("regular")
    key = (path or "", size)
    if key in _font_cache:
        return _font_cache[key]
    try:
        f = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    except OSError:
        f = ImageFont.load_default(size)
    _font_cache[key] = f
    return f


def _tone_to_style(tone: str, bubble_type: str, font_style: str | None = None) -> str:
    if font_style and font_style.lower() in FONT_STYLES:
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

_SYMBOL_FONT_PATHS = [_FONTS_DIR / "NotoSansCJK-Regular.ttc"]   # shipped: same glyphs on every host

_symbol_font_cache: dict[int, ImageFont.FreeTypeFont | None] = {}


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
