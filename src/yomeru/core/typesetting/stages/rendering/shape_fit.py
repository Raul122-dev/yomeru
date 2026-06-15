"""
Shape fitting for bubble-aware text placement.

Instead of using raw bbox, fits text within the actual bubble shape
by computing the largest inscribed rectangle from the inpaint mask.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def find_usable_rect(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    padding: int = 8,
) -> tuple[int, int, int, int]:
    """
    Find the largest usable rectangle inside a bubble region.

    Uses the image content to detect the bubble interior:
    1. Crop the bbox region
    2. Threshold to find the white/light bubble area
    3. Find largest inscribed rectangle in that area
    4. Apply padding and return the usable rect

    Falls back to bbox with padding if detection fails.

    Returns (x1, y1, x2, y2) in image coordinates.
    """
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1

    if w < 20 or h < 20:
        # Too small for shape analysis, use bbox
        return (x1 + padding, y1 + padding, x2 - padding, y2 - padding)

    arr = np.array(image)
    crop = arr[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

    # Threshold: bubble interior is the lighter area
    mean_br = float(gray.mean())
    if mean_br > 140:
        # Light interior — the bubble IS the light area
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        # Dark interior (dark bubble, narration box)
        binary = np.ones_like(gray) * 255  # treat entire region as usable

    # Find largest inscribed rectangle
    rect = _largest_inscribed_rect(binary)

    if rect is None or rect[2] < 15 or rect[3] < 15:
        # Fallback to bbox with padding
        return (x1 + padding, y1 + padding, x2 - padding, y2 - padding)

    rx, ry, rw, rh = rect
    # Convert to image coordinates and apply padding
    ix1 = x1 + rx + padding
    iy1 = y1 + ry + padding
    ix2 = x1 + rx + rw - padding
    iy2 = y1 + ry + rh - padding

    # Ensure valid rect
    if ix2 <= ix1 or iy2 <= iy1:
        return (x1 + padding, y1 + padding, x2 - padding, y2 - padding)

    return (ix1, iy1, ix2, iy2)


def _largest_inscribed_rect(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    Find largest axis-aligned rectangle inscribed in a binary mask.
    Uses the histogram-based maximal rectangle algorithm (O(n*m)).

    Returns (x, y, w, h) or None if no valid rectangle found.
    """
    h, w = binary.shape

    # Build height histogram (consecutive white pixels from top)
    heights = np.zeros((h, w), dtype=np.int32)
    heights[0] = (binary[0] > 127).astype(np.int32)
    for row in range(1, h):
        for col in range(w):
            if binary[row, col] > 127:
                heights[row, col] = heights[row - 1, col] + 1
            else:
                heights[row, col] = 0

    best_area = 0
    best_rect = None

    for row in range(h):
        rect = _max_rect_in_histogram(heights[row])
        if rect is not None:
            rx, rw, rh = rect
            area = rw * rh
            if area > best_area:
                best_area = area
                best_rect = (rx, row - rh + 1, rw, rh)

    return best_rect


def _max_rect_in_histogram(hist: np.ndarray) -> tuple[int, int, int] | None:
    """
    Find max rectangle in histogram row.
    Returns (x_start, width, height) or None.
    """
    n = len(hist)
    stack: list[int] = []
    best_area = 0
    best: tuple[int, int, int] | None = None

    for i in range(n + 1):
        h = int(hist[i]) if i < n else 0
        while stack and int(hist[stack[-1]]) > h:
            height = int(hist[stack.pop()])
            width = i if not stack else i - stack[-1] - 1
            x_start = 0 if not stack else stack[-1] + 1
            area = height * width
            if area > best_area:
                best_area = area
                best = (x_start, width, height)
        stack.append(i)

    return best
