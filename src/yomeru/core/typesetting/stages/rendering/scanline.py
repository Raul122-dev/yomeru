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
    wrap_cjk,
    wrap_latin,
    hyphen_count,
    LANG_MAP,
)


@dataclass
class ScanlineSegment:
    """A horizontal segment of available space at a given Y."""
    y: int
    x_start: int
    x_end: int

    @property
    def width(self) -> int:
        return self.x_end - self.x_start


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


def compute_scanlines(
    contour: np.ndarray,
    line_height: int,
    bbox: tuple[int, int, int, int],
) -> list[ScanlineSegment]:
    """
    Compute horizontal scanline segments within the contour.

    For each line_y (spaced by line_height), finds the intersection
    of a horizontal ray with the contour polygon.

    Returns list of ScanlineSegment with available width per line.
    """
    x1, y1, x2, y2 = bbox

    # Get vertical extent of contour
    contour_points = contour.reshape(-1, 2)
    cy_min = int(contour_points[:, 1].min())
    cy_max = int(contour_points[:, 1].max())

    segments: list[ScanlineSegment] = []

    # Create filled mask for fast scanline queries
    mask_y1 = cy_min
    mask_y2 = cy_max
    mask_x1 = int(contour_points[:, 0].min())
    mask_x2 = int(contour_points[:, 0].max())
    mask_h = mask_y2 - mask_y1 + 1
    mask_w = mask_x2 - mask_x1 + 1

    if mask_h < 5 or mask_w < 5:
        return segments

    mask = np.zeros((mask_h, mask_w), dtype=np.uint8)
    shifted = contour.reshape(-1, 2) - np.array([mask_x1, mask_y1])
    cv2.fillPoly(mask, [shifted.astype(np.int32)], 255)

    # Scan from top to bottom with line_height step
    # Start half a line_height from top for vertical centering
    start_y = cy_min + line_height // 2

    for scan_y in range(start_y, cy_max - line_height // 4, line_height):
        local_y = scan_y - mask_y1
        if local_y < 0 or local_y >= mask_h:
            continue

        # Get the row from the mask
        row = mask[local_y]

        # Find continuous white segments
        in_segment = False
        seg_start = 0

        for px in range(mask_w):
            if row[px] > 127 and not in_segment:
                in_segment = True
                seg_start = px
            elif row[px] <= 127 and in_segment:
                in_segment = False
                seg_x1 = mask_x1 + seg_start
                seg_x2 = mask_x1 + px
                if seg_x2 - seg_x1 >= 20:  # minimum segment width
                    segments.append(ScanlineSegment(y=scan_y, x_start=seg_x1, x_end=seg_x2))

        # Handle segment that extends to end of row
        if in_segment:
            seg_x1 = mask_x1 + seg_start
            seg_x2 = mask_x1 + mask_w
            if seg_x2 - seg_x1 >= 20:
                segments.append(ScanlineSegment(y=scan_y, x_start=seg_x1, x_end=seg_x2))

    return segments


def variable_width_wrap(
    text: str,
    segments: list[ScanlineSegment],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    lang_code: str | None,
    min_segment_width: int = 30,
    width_factor: float = 1.0,
) -> list[PositionedLine] | None:
    """
    Wrap text using variable widths from scanline segments.

    Greedy algorithm: fills each segment's width before moving to next line.
    Skips segments that are too narrow.
    width_factor: scale available width (0.5-1.0) to force more lines.

    Returns positioned lines or None if text doesn't fit.
    """
    if not segments or not text.strip():
        return None

    is_cjk = is_cjk_text(text)
    words: list[str]

    if is_cjk:
        # CJK: each character is a word
        words = list(text.replace(" ", ""))
    else:
        words = text.split()

    if not words:
        return None

    lines: list[PositionedLine] = []
    word_idx = 0

    for seg in segments:
        if word_idx >= len(words):
            break

        if seg.width < min_segment_width:
            continue

        available_w = int(seg.width * width_factor)
        current = ""

        while word_idx < len(words):
            word = words[word_idx]
            if is_cjk:
                candidate = current + word
            else:
                candidate = (current + " " + word).strip() if current else word

            if measure_width(candidate, font) <= available_w:
                current = candidate
                word_idx += 1
            else:
                break

        if current.strip():
            # Center the line within the segment
            line_w = measure_width(current, font)
            line_x = seg.x_start + (seg.width - line_w) // 2
            lines.append(PositionedLine(
                text=current.strip(),
                x=line_x,
                y=seg.y,
                width=seg.width,
            ))

    # Check if all words were placed
    if word_idx < len(words):
        return None  # Text doesn't fit

    return lines if lines else None


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
) -> list[PositionedLine] | None:
    """
    Full scanline layout pipeline:
    1. Extract bubble contour from ORIGINAL image (or use precomputed)
    2. Erode for padding
    3. Compute scanlines
    4. Variable-width wrap
    5. Vertically center the text block

    Returns positioned lines or None if layout fails.
    """
    lh = measure_line_height(font, font_size)

    # 1. Extract contour (or use cached)
    contour = precomputed_contour if precomputed_contour is not None else extract_bubble_contour(image, bbox)
    if contour is None:
        return None

    # 2. Erode for padding
    eroded = erode_contour(contour, padding=padding)
    if eroded is None:
        return None

    # 3. Compute ALL scanlines (densely, every pixel row)
    #    We'll select the right subset for vertical centering later
    all_segments = compute_scanlines(eroded, lh, bbox)
    if not all_segments:
        return None

    # 4. First pass: determine how many lines we need
    #    Try wrapping with the full set of segments
    positioned = variable_width_wrap(text, all_segments, font, lang_code, width_factor=width_factor)
    if not positioned:
        return None

    # 5. Vertical centering: center text block within the BUBBLE BBOX
    #    Use scanlines only for X positioning (width at each height).
    #    Y positioning is pure bbox centering for consistent visual result.
    num_lines = len(positioned)
    total_available = len(all_segments)

    x1, y1, x2, y2 = bbox
    bbox_height = y2 - y1
    text_block_h = num_lines * lh
    # Visual compensation: font ascender is larger than descender,
    # making text appear slightly high. Shift down by (ascender - descender) / 4
    try:
        asc, desc = font.getmetrics()
        visual_offset = (asc - abs(desc)) // 4
    except Exception:
        visual_offset = lh // 8
    start_y = y1 + (bbox_height - text_block_h) // 2 + visual_offset

    # For each line, find the scanline segment closest to its Y position
    # to determine the available width for X centering
    result_lines: list[PositionedLine] = []
    words = text.split() if not is_cjk_text(text) else list(text.replace(" ", ""))
    word_idx = 0

    for line_idx in range(num_lines):
        line_y = start_y + line_idx * lh

        # Find the scanline segment closest to this Y
        best_seg = None
        best_dist = float("inf")
        for seg in all_segments:
            dist = abs(seg.y - line_y)
            if dist < best_dist:
                best_dist = dist
                best_seg = seg

        if best_seg is None:
            best_seg = all_segments[len(all_segments) // 2]  # fallback to middle

        # Use the text from the original wrap for this line
        if line_idx < len(positioned):
            line_text = positioned[line_idx].text
            line_w = measure_width(line_text, font)
            # Center horizontally within the segment width
            line_x = best_seg.x_start + (best_seg.width - line_w) // 2
            result_lines.append(PositionedLine(text=line_text, x=line_x, y=line_y, width=best_seg.width))

    return result_lines if result_lines else positioned
