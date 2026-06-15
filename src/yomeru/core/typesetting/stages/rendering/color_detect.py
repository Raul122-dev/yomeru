"""
Color detection for text rendering.

Detects the dominant text color in a region (for manhwa/colored manga)
and determines optimal outline color based on background.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def detect_text_color(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """
    Detect the dominant text color in a region.

    For colored manga/manhwa, the original text may be colored.
    Uses Otsu to segment text pixels, then takes their median color.

    Returns RGB tuple.
    """
    x1, y1, x2, y2 = bbox
    arr = np.array(image)
    crop = arr[y1:y2, x1:x2]

    if crop.size == 0:
        return (0, 0, 0)

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    mean_br = float(gray.mean())

    if mean_br > 140:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    text_pixels = crop[mask > 127]

    if len(text_pixels) < 10:
        return (0, 0, 0) if mean_br > 128 else (255, 255, 255)

    # Median color of text pixels
    r = int(np.median(text_pixels[:, 0]))
    g = int(np.median(text_pixels[:, 1]))
    b = int(np.median(text_pixels[:, 2]))
    return (r, g, b)


def detect_background_color(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """
    Detect the dominant background color in a region.
    Uses Otsu to segment, then takes median of NON-text pixels.
    """
    x1, y1, x2, y2 = bbox
    arr = np.array(image)
    crop = arr[y1:y2, x1:x2]

    if crop.size == 0:
        return (255, 255, 255)

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    mean_br = float(gray.mean())

    if mean_br > 140:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    bg_pixels = crop[mask < 128]

    if len(bg_pixels) < 10:
        return (255, 255, 255) if mean_br > 128 else (0, 0, 0)

    r = int(np.median(bg_pixels[:, 0]))
    g = int(np.median(bg_pixels[:, 1]))
    b = int(np.median(bg_pixels[:, 2]))
    return (r, g, b)


def compute_outline_color(bg_color: tuple[int, int, int]) -> tuple[int, int, int]:
    """
    Compute an outline color that contrasts with the background.
    Uses luminance to decide: dark bg → light outline, light bg → dark outline.
    """
    lum = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
    if lum > 128:
        return (0, 0, 0)
    return (255, 255, 255)


def is_colored_text(text_color: tuple[int, int, int]) -> bool:
    """
    Determine if text is 'colored' (not just black or white).
    A text is colored if its saturation is notable.
    """
    r, g, b = text_color
    # Check if it's near grayscale
    spread = max(r, g, b) - min(r, g, b)
    return spread > 40
