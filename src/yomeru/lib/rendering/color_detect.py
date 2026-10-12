"""
Background colour detection for text rendering (black vs white text).

Colour-preserving rendering (keeping the original text's colour in coloured
manhwa) is a Fase 3 idea; its unused helpers were removed — see vault
"Yomeru - Flujo de datos y backends" §2.5.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


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
