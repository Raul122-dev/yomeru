"""
PIL rendering backend v2.

Advanced text rendering with:
- Outline/stroke for legibility on complex backgrounds
- Rotation support for angled free text
- CJK character-level line breaking
- Shape-aware fitting (largest inscribed rect in bubble)
- Adaptive color detection (text + outline colors)
- SFX subtitle mode (small text nearby, no replace)
- Vertical text for CJK in tall bubbles
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .text_layout import (
    LANG_MAP,
    extract_embedded_breaks,
    hyphen_count,
    is_cjk_text,
    measure_line_height,
    measure_width,
    wrap_cjk,
    wrap_latin,
    wrap_segments,
    wrap_text,
)
from .color_detect import (
    compute_outline_color,
    detect_background_color,
    detect_text_color,
    is_colored_text,
)
from .shape_fit import find_usable_rect
from .angle_detect import detect_text_angle

# ── font registry ─────────────────────────────────────────────────────────────

_FONTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "assets" / "fonts"

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
    # Draw outline in 8 directions
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            if abs(dx) + abs(dy) > outline_width + 1:
                continue  # Skip corners for smoother outline
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Draw fill on top
    draw.text((x, y), text, font=font, fill=fill)


# ── vertical text ─────────────────────────────────────────────────────────────

def _is_vertical_bubble(bubble_w: int, bubble_h: int, text: str) -> bool:
    """Detect if text should be rendered vertically."""
    # Aspect ratio check: very tall and narrow
    if bubble_h > bubble_w * 2.0:
        return True
    # CJK in moderately tall bubbles
    if is_cjk_text(text) and bubble_h > bubble_w * 1.5:
        return True
    return False


def _render_vertical(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    x1: int, y1: int, x2: int, y2: int,
    pad: int,
    size: int,
    fill: tuple[int, int, int],
    outline_color: tuple[int, int, int] | None = None,
    outline_width: int = 0,
) -> list[str]:
    """
    Render text vertically (top-to-bottom, right-to-left columns).
    Returns list of column strings for RenderResult.
    """
    char_h = measure_line_height(font, size)
    char_w = size

    usable_w = x2 - x1 - pad * 2
    usable_h = y2 - y1 - pad * 2

    # Flatten and remove spaces for vertical layout
    flat = text.replace(" ", "")

    chars_per_col = max(1, usable_h // char_h)
    cols = [flat[i:i + chars_per_col] for i in range(0, len(flat), chars_per_col)]

    # Draw right-to-left
    for col_idx, col in enumerate(reversed(cols)):
        col_x = x2 - pad - char_w - col_idx * (char_w + 2)
        if col_x < x1 + pad:
            break
        for row_idx, ch in enumerate(col):
            cy = y1 + pad + row_idx * char_h
            if outline_color and outline_width > 0:
                _draw_text_with_outline(draw, (col_x, cy), ch, font, fill, outline_color, outline_width)
            else:
                draw.text((col_x, cy), ch, font=font, fill=fill)

    return cols


# ── fit algorithm ─────────────────────────────────────────────────────────────

def _find_fit(
    text: str,
    embedded_lines: list[str] | None,
    box_w: int,
    box_h: int,
    min_size: int,
    max_size: int,
    style: str,
    lang_code: str | None,
) -> tuple[int, list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, str] | None:
    """
    Find the largest font size that fits the text within the box.
    Simple and predictable: iterate from max to min, return first fit.
    """
    is_cjk = is_cjk_text(text)
    best: tuple[int, list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, str] | None = None

    for size in range(max_size, min_size - 1, -1):
        font = _get_font(style, size)
        lh = measure_line_height(font, size)
        max_lines = max(1, box_h // lh)

        # 1. Try embedded newlines first
        if embedded_lines:
            seg_lines = wrap_segments(embedded_lines, box_w, max_lines, font, lang_code, is_cjk)
            if seg_lines is not None:
                return size, seg_lines, font, "embedded"

        # 2. Auto-wrap
        lines = wrap_text(text, box_w, max_lines, font, lang_code)
        if lines is None:
            continue

        # Accept immediately if no hyphens (clean wrap)
        if hyphen_count(lines) == 0:
            return size, lines, font, "wrap"

        # Keep as candidate but continue looking for cleaner fit
        if best is None:
            best = (size, lines, font, "hyphen")

    return best


# ── result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RenderResult:
    """Diagnostic information from a render attempt."""
    text: str
    status: str  # "ok" | "skip"
    skip_reason: str = ""
    lines: list[str] = field(default_factory=list)
    font_size: int = 0
    font_style: str = ""
    line_source: str = ""  # "embedded" | "wrap" | "hyphen" | "vertical" | "sfx"
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    box_size: tuple[int, int] = (0, 0)
    angle: float = 0.0
    text_color: tuple[int, int, int] = (0, 0, 0)
    has_outline: bool = False

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
            "angle": self.angle,
            "text_color": list(self.text_color),
            "has_outline": self.has_outline,
        }


# ── SFX subtitle mode ─────────────────────────────────────────────────────────

def _render_sfx_subtitle(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    text: str,
    style: str = "bold",
) -> tuple[Image.Image, RenderResult]:
    """
    Render SFX as a small subtitle near the original (Option D).
    Does NOT erase the original — just adds translated text nearby.
    """
    x1, y1, x2, y2 = bbox
    # Position subtitle below the SFX region
    sub_y = min(y2 + 2, image.height - 20)
    sub_x = x1

    font_size = max(10, min(14, (x2 - x1) // max(1, len(text)) + 4))
    font = _get_font(style, font_size)

    img = image.copy()
    draw = ImageDraw.Draw(img)

    # Determine colors from area below SFX
    bg_sample = np.array(image)[
        max(0, sub_y - 5):min(image.height, sub_y + 20),
        max(0, sub_x):min(image.width, sub_x + 80),
        :3
    ]
    if bg_sample.size > 0 and float(bg_sample.mean()) > 128:
        fill = (40, 40, 40)
        outline = (255, 255, 255)
    else:
        fill = (240, 240, 240)
        outline = (20, 20, 20)

    # Draw with outline for legibility
    _draw_text_with_outline(draw, (sub_x, sub_y), f"({text})", font, fill, outline, 1)

    r = RenderResult(
        text=text, status="ok",
        lines=[text], font_size=font_size, font_style=style,
        line_source="sfx", bbox=(x1, y1, x2, y2),
        box_size=(x2 - x1, y2 - y1),
        text_color=fill, has_outline=True,
    )
    return img, r


# ── main render function ──────────────────────────────────────────────────────

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
    is_free_text: bool = False,
) -> tuple[Image.Image, RenderResult]:
    """
    Render translated text in a region.

    Handles:
    - Bubble text (shape fitting, centered)
    - Free text (outline, rotation, adaptive color)
    - SFX (subtitle mode)
    - Vertical CJK
    """
    # SFX mode: subtitle nearby
    if (bubble_type or "").lower() == "sfx":
        return _render_sfx_subtitle(image, bbox, text)

    # Clamp bbox
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(x1, image.width - 1))
    y1 = max(0, min(y1, image.height - 1))
    x2 = max(x1 + 1, min(x2, image.width))
    y2 = max(y1 + 1, min(y2, image.height))

    # Extract embedded breaks
    clean_text, embedded_lines = extract_embedded_breaks(text)

    if not clean_text.strip():
        r = RenderResult(text=text, status="skip", skip_reason="empty_text", bbox=(x1, y1, x2, y2))
        return image, r

    # ── Determine rendering parameters ──

    # Color detection
    use_outline = is_free_text
    if is_colored_text(detect_text_color(image, (x1, y1, x2, y2))):
        text_color = detect_text_color(image, (x1, y1, x2, y2))
    else:
        # Standard: black on light, white on dark
        bg_color = detect_background_color(image, (x1, y1, x2, y2))
        lum = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
        text_color = (0, 0, 0) if lum > 128 else (255, 255, 255)

    outline_color = compute_outline_color(
        detect_background_color(image, (x1, y1, x2, y2))
    ) if use_outline else (0, 0, 0)
    # Invert: outline should contrast with text_color for free text
    if use_outline:
        outline_color = (255, 255, 255) if sum(text_color) < 384 else (0, 0, 0)

    # Angle detection for free text
    angle = 0.0
    if is_free_text:
        angle = detect_text_angle(image, (x1, y1, x2, y2))

    # Usable text area: simple padding (stable approach)
    bubble_w, bubble_h = x2 - x1, y2 - y1

    if is_free_text:
        pad = max(4, padding // 2)
    elif bubble_w < 50 or bubble_h < 35:
        pad = 2
        min_font_size = min(min_font_size, 6)
    elif bubble_w < 80 or bubble_h < 55:
        pad = max(3, padding // 3)
        min_font_size = min(min_font_size, 7)
    else:
        pad = padding

    fx1, fy1, fx2, fy2 = x1 + pad, y1 + pad, x2 - pad, y2 - pad
    box_w = fx2 - fx1
    box_h = fy2 - fy1

    if box_w < 6 or box_h < 6:
        reason = f"too_small_{bubble_w}x{bubble_h}px"
        r = RenderResult(text=text, status="skip", skip_reason=reason,
                         bbox=(x1, y1, x2, y2), box_size=(box_w, box_h))
        return image, r

    style = _tone_to_style(tone, bubble_type, font_style)
    lang_code = LANG_MAP.get(source_language, "en_US")

    # ── Vertical text check ──
    if _is_vertical_bubble(bubble_w, bubble_h, clean_text):
        font = _get_font(style, max_font_size)
        img = image.copy()
        draw = ImageDraw.Draw(img)
        cols = _render_vertical(
            draw, clean_text, font, fx1, fy1, fx2, fy2, 4, max_font_size,
            text_color,
            outline_color if use_outline else None,
            2 if use_outline else 0,
        )
        r = RenderResult(
            text=clean_text, status="ok", lines=cols,
            font_size=max_font_size, font_style=style, line_source="vertical",
            bbox=(x1, y1, x2, y2), box_size=(box_w, box_h),
            text_color=text_color, has_outline=use_outline,
        )
        return img, r

    # ── Find best fit (simple bbox approach) ──
    fit = _find_fit(
        text=clean_text, embedded_lines=embedded_lines,
        box_w=box_w, box_h=box_h,
        min_size=min_font_size, max_size=max_font_size,
        style=style, lang_code=lang_code,
    )

    if fit is None:
        reason = f"cannot_fit_in_{box_w}x{box_h}px"
        r = RenderResult(text=text, status="skip", skip_reason=reason,
                         bbox=(x1, y1, x2, y2), box_size=(box_w, box_h))
        print(f"  [render] SKIP '{clean_text[:20]}' — {reason}", file=sys.stderr)
        return image, r

    size, lines, font, line_source = fit
    lh = measure_line_height(font, size)
    total_h = len(lines) * lh
    start_y = fy1 + max(0, (box_h - total_h) // 2)

    outline_w = max(1, size // 12) if use_outline else 0

    # ── Render (with optional rotation) ──
    if abs(angle) > 3:
        img = _render_rotated(
            image, lines, font, fx1, fy1, fx2, fy2, start_y, lh,
            text_color, outline_color if use_outline else None, outline_w, angle,
        )
    else:
        img = image.copy()
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            lw = measure_width(line, font)
            line_x = (fx1 + fx2) // 2 - lw // 2
            line_x = max(fx1, min(line_x, fx2 - max(0, lw)))
            pos = (line_x, start_y + i * lh)
            if use_outline:
                _draw_text_with_outline(draw, pos, line, font, text_color, outline_color, outline_w)
            else:
                draw.text(pos, line, font=font, fill=text_color)

    r = RenderResult(
        text=clean_text, status="ok", lines=lines,
        font_size=size, font_style=style, line_source=line_source,
        bbox=(x1, y1, x2, y2), box_size=(box_w, box_h),
        angle=angle, text_color=text_color, has_outline=use_outline,
    )
    print(f"  [render] '{clean_text[:20]}' → {len(lines)}L {size}px {style} [{line_source}]"
          + (f" rot={angle}°" if angle else ""), file=sys.stderr)
    return img, r


def _render_rotated(
    image: Image.Image,
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fx1: int, fy1: int, fx2: int, fy2: int,
    start_y: int,
    lh: int,
    fill: tuple[int, int, int],
    outline_color: tuple[int, int, int] | None,
    outline_w: int,
    angle: float,
) -> Image.Image:
    """Render text on a temporary canvas, rotate it, and composite."""
    box_w, box_h = fx2 - fx1, fy2 - fy1

    # Create transparent canvas for the text
    canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    for i, line in enumerate(lines):
        lw = measure_width(line, font)
        line_x = box_w // 2 - lw // 2
        pos = (line_x, (start_y - fy1) + i * lh)
        if outline_color and outline_w > 0:
            _draw_text_with_outline(draw, pos, line, font, fill + (255,), outline_color + (255,), outline_w)
        else:
            draw.text(pos, line, font=font, fill=fill + (255,))

    # Rotate canvas
    rotated = canvas.rotate(angle, expand=False, resample=Image.BICUBIC)

    # Composite onto original
    img = image.copy().convert("RGBA")
    img.paste(rotated, (fx1, fy1), rotated)
    return img.convert("RGB")


# ── class wrapper ─────────────────────────────────────────────────────────────

class PILRenderer:
    """PIL v2 text renderer. Implements the BaseRenderer protocol."""

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
        line_break_hint: str | None = None,
        source_language: str = "auto",
        padding: int = 10,
        min_font_size: int = 8,
        max_font_size: int = 30,
        is_free_text: bool = False,
    ) -> tuple[Image.Image, RenderResult]:
        """Render text into region. Returns (image_with_text, RenderResult)."""
        return render_text_in_bubble(
            image=image, bbox=bbox, text=text,
            tone=tone, bubble_type=bubble_type,
            font_style=font_style, line_break_hint=line_break_hint,
            source_language=source_language,
            padding=padding, min_font_size=min_font_size,
            max_font_size=max_font_size, is_free_text=is_free_text,
        )
