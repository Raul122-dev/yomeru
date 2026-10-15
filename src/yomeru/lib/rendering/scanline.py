# -*- coding: utf-8 -*-
"""
Scanline-based text layout engine for bubble-aware typesetting.

Given a bubble contour (extracted from the inpainted image), computes
the available width at each vertical position using scanline intersection.
This allows text to fill irregular shapes (circles, ovals, clouds, stars)
without overflow.

Pipeline:
  1. Extract bubble contour from inpainted image region
  2. Erode contour for internal padding
  3. Compute scanline segments (available width per line_y)
  4. Variable-width word wrap using real font metrics
  5. Return positioned lines for rendering
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageFont

from .text_layout import (
    is_cjk_text,
    measure_width,
    measure_line_height,
)



@dataclass
class PositionedLine:
    """A line of text with its exact rendering position."""
    text: str
    x: int  # left edge (for centered: computed from segment)
    y: int
    width: int  # available width at this line


def extract_bubble_contour(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
) -> np.ndarray | None:
    """
    Extract the bubble contour from the ORIGINAL image (not inpainted).

    Uses the approach from manga-image-translator:
    1. Canny edge detection on the cropped region
    2. Draw rectangle at crop borders (closes contours touching edges)
    3. Find contours and draw them as lines
    4. FloodFill from center to find the enclosed bubble area
    5. Return the contour of the filled area

    The image should be the ORIGINAL page (with bubble borders visible),
    NOT the inpainted image.

    Returns contour points in image coordinates, or None if extraction fails.
    """
    x1, y1, x2, y2 = bbox
    arr = np.array(image)
    crop = arr[y1:y2, x1:x2].copy()

    if crop.size == 0:
        return None

    h, w = crop.shape[:2]
    if h < 20 or w < 20:
        return None

    img_area = h * w

    # 1. Gaussian blur + Canny edge detection
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 70, 140, L2gradient=True, apertureSize=3)

    # 2. Draw rectangle at borders to close contours touching edges
    cv2.rectangle(edges, (0, 0), (w - 1, h - 1), 255, 1)

    # 3. Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)

    # Remove the border rect
    cv2.rectangle(edges, (0, 0), (w - 1, h - 1), 0, 1)

    # 4. Draw qualifying contours and floodFill from center
    seed = (w // 2, h // 2)
    min_retval = float("inf")
    best_mask: np.ndarray | None = None

    mask = np.zeros((h, w), np.uint8)
    for cnt in contours:
        rect = cv2.boundingRect(cnt)
        # Only consider contours that cover significant area
        if rect[2] * rect[3] < img_area * 0.3:
            continue

        # Draw this contour
        cv2.drawContours(mask, [cnt], 0, 255, 2)

        # Try floodFill from center on a copy
        test_mask = mask.copy()
        cv2.rectangle(test_mask, (0, 0), (w - 1, h - 1), 255, 1)
        fill_mask = test_mask.copy()
        retval, _, _, _ = cv2.floodFill(
            fill_mask, mask=None, seedPoint=seed,
            newVal=127, loDiff=(10, 10, 10), upDiff=(10, 10, 10),
            flags=4,
        )

        if retval <= img_area * 0.2:
            # This contour didn't help, undo
            cv2.drawContours(mask, [cnt], 0, 0, 2)
            continue

        if retval < min_retval and retval > img_area * 0.2:
            min_retval = retval
            best_mask = fill_mask.copy()

    if best_mask is None:
        return None

    # 5. Extract the filled region as a binary mask
    # The filled area has value 127
    bubble_binary = np.zeros((h, w), np.uint8)
    bubble_binary[best_mask == 127] = 255

    # Clean up
    kernel = np.ones((3, 3), np.uint8)
    bubble_binary = cv2.morphologyEx(bubble_binary, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Find final contour
    final_contours, _ = cv2.findContours(bubble_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not final_contours:
        return None

    largest = max(final_contours, key=cv2.contourArea)

    # Minimum area check
    if cv2.contourArea(largest) < img_area * 0.15:
        return None

    # Offset to image coordinates
    largest = largest + np.array([x1, y1])

    return largest


def erode_contour(
    contour: np.ndarray,
    padding: int = 10,
    image_shape: tuple[int, int] = (0, 0),
) -> np.ndarray | None:
    """
    Erode (inset) a contour by `padding` pixels.

    Uses cv2.erode on a filled mask of the contour.
    Returns the eroded contour, or None if erosion makes it too small.
    """
    # Determine bounding rect
    x, y, w, h = cv2.boundingRect(contour)
    if w < 20 or h < 20:
        return None

    # Create mask from contour
    # Use a local coordinate system for efficiency
    margin = padding + 5
    mask = np.zeros((h + margin * 2, w + margin * 2), dtype=np.uint8)
    shifted = contour.reshape(-1, 2) - np.array([x - margin, y - margin])
    cv2.fillPoly(mask, [shifted.astype(np.int32)], 255)

    # Erode
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (padding * 2, padding * 2))
    eroded = cv2.erode(mask, kernel, iterations=1)

    # Extract new contour
    contours, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)

    # Check minimum size
    if cv2.contourArea(largest) < 200:
        return None

    # Shift back to image coordinates
    largest = largest.reshape(-1, 1, 2) + np.array([[[x - margin, y - margin]]])

    return largest


def _line_span(mask: np.ndarray, top: int, lh: int, cx: int) -> tuple[int, int] | None:
    """Horizontal span usable by a line occupying rows [top, top+lh) of the
    filled mask: the run around the bubble's centre x, intersected over the
    line's glyph rows (so ascenders/descenders don't hit a curving edge).
    One span per line — a concave row no longer yields two overlapping lines."""
    h, w = mask.shape
    lo, hi = 0, w
    for y in (top + lh // 5, top + lh // 2, top + (4 * lh) // 5):
        if y < 0 or y >= h:
            return None
        row = mask[y] > 0
        if not row.any():
            return None
        x = cx if 0 <= cx < w and row[cx] else int(np.flatnonzero(row)[np.argmin(np.abs(np.flatnonzero(row) - cx))])
        l = x
        while l > 0 and row[l - 1]:
            l -= 1
        r = x
        while r < w - 1 and row[r + 1]:
            r += 1
        lo, hi = max(lo, l), min(hi, r + 1)
    return (lo, hi) if hi - lo >= 20 else None


MIN_SPLIT_LEN = 8  # words of 7 letters or fewer are never split (unless forced)


def _splittable(word: str, protected: frozenset[str], force: bool) -> bool:
    """Proper names (words carried over verbatim from the source text) and
    short words are kept whole; `force` (nothing fits otherwise) only keeps
    names whole."""
    from .text_layout import _ELLIPSIS_INSIDE, _split_word_punct
    if _ELLIPSIS_INSIDE.search(word):
        return True   # breaks before the dots, never inside the word itself
    root = _split_word_punct(word)[1]
    if root.upper() in protected:
        return False
    return force or len(root) >= MIN_SPLIT_LEN


def _wrap_into(words: list[str], widths: list[int], font, is_cjk: bool, hyph,
               protected: frozenset[str] = frozenset(), force: bool = False) -> list[str] | None:
    """Fit the words into exactly these line widths (top to bottom). Search over
    break points, fullest line first, so a long word can move to a wider row
    instead of failing (greedy filling pushed a long word onto the narrow
    bottom row). A word that fits no row whole may be split at a syllable
    (Latin, never names/short words unless forced). None if impossible."""
    from functools import lru_cache
    from .text_layout import _try_hyphenate
    join = (lambda a, b: a + b) if is_cjk else (lambda a, b: f"{a} {b}" if a else b)
    n_lines = len(widths)

    @lru_cache(maxsize=None)
    def go(i: int, carry: str, line: int) -> tuple[str, ...] | None:
        # carry: tail of a split word that must start this line
        if i >= len(words) and not carry:
            return () if line == n_lines else None
        if line >= n_lines:
            return None
        w = widths[line]
        queue = ([carry] if carry else []) + list(words[i:])
        consumed_offset = 1 if carry else 0
        cur = ""
        options = []
        for k, word in enumerate(queue):
            cand = join(cur, word)
            if measure_width(cand, font) > w:
                if not cur and not is_cjk and _splittable(word, protected, force):
                    head, rest = _try_hyphenate(word, hyph, font, w, min_root_len=4)
                    if head:
                        nxt_i = i + (k + 1 - consumed_offset)
                        options.append((head, nxt_i, rest))
                break
            cur = cand
            options.append((cur, i + (k + 1 - consumed_offset), ""))
        for text, nxt_i, nxt_carry in reversed(options):  # fullest line first
            tail = go(nxt_i, nxt_carry, line + 1)
            if tail is not None:
                return (text,) + tail
        return None

    got = go(0, "", 0)
    return list(got) if got else None


def scanline_layout(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_size: int,
    lang_code: str | None,
    padding: int = 12,
    width_factor: float = 1.0,
    precomputed_contour: np.ndarray | None = None,
    hyphenate: bool | str = True,
    protected: frozenset[str] = frozenset(),
) -> list[PositionedLine] | None:
    """Lay text inside the bubble's (eroded) contour, centre-first.

    For N = 1, 2, ... lines: centre an N-line block on the bubble's centroid,
    take the contour's width at each of those lines, and wrap the words into
    exactly those widths (syllable split only when a word can't fit a line).
    The first N that fits wins — fewest breaks. The old version wrapped with
    widths measured from the contour's TOP and then re-centred the block on
    the bbox, so lines landed on rows of a different width ('YA / CONOCES /
    EL / ...' in 5 lines; overflow on narrow rows).
    """
    lh = measure_line_height(font, font_size)
    contour = precomputed_contour if precomputed_contour is not None else extract_bubble_contour(image, bbox)
    if contour is None:
        return None
    eroded = erode_contour(contour, padding=padding)
    if eroded is None:
        return None

    pts = eroded.reshape(-1, 2)
    ox, oy = int(pts[:, 0].min()), int(pts[:, 1].min())
    mw, mh = int(pts[:, 0].max()) - ox + 1, int(pts[:, 1].max()) - oy + 1
    if mw < 5 or mh < 5:
        return None
    mask = np.zeros((mh, mw), dtype=np.uint8)
    cv2.fillPoly(mask, [(pts - np.array([ox, oy])).astype(np.int32)], 255)
    m = cv2.moments(mask, binaryImage=True)
    if not m["m00"]:
        return None
    cx, cy = int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])

    is_cjk = is_cjk_text(text)
    words = list(text.replace(" ", "")) if is_cjk else text.split()
    if not words:
        return None
    from .text_layout import _get_hyphenator
    hyph = None if is_cjk or not lang_code or not hyphenate else _get_hyphenator(lang_code, aggressive=True)
    try:
        asc, desc = font.getmetrics()
        visual_offset = (asc - abs(desc)) // 4
    except Exception:
        visual_offset = lh // 8

    for n in range(1, max(1, mh // lh) + 1):
        top = cy - (n * lh) // 2 + visual_offset
        top = min(max(top, 0), max(0, mh - n * lh))
        spans = [_line_span(mask, top + i * lh, lh, cx) for i in range(n)]
        if any(sp is None for sp in spans):
            continue
        lines = _wrap_into(words, [int((hi - lo) * width_factor) for lo, hi in spans], font, is_cjk, hyph,
                           protected=protected, force=hyphenate == "force")
        if lines is None:
            continue
        out = []
        for i, (txt, (lo, hi)) in enumerate(zip(lines, spans)):
            lw = measure_width(txt, font)
            out.append(PositionedLine(text=txt, x=ox + lo + (hi - lo - lw) // 2, y=oy + top + i * lh, width=hi - lo))
        return out
    return None
