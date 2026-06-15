"""
Angle detection for rotated free text.

Detects the rotation angle of text in a region using line detection
or minimum area bounding rect of text contours.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def detect_text_angle(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
) -> float:
    """
    Detect the rotation angle of text in a region.

    Uses minAreaRect on text contours to find the dominant text angle.
    Returns angle in degrees (0 = horizontal, positive = counter-clockwise).
    Only returns non-zero for significant rotations (>5°).
    """
    x1, y1, x2, y2 = bbox
    arr = np.array(image)
    crop = arr[y1:y2, x1:x2]

    if crop.size == 0:
        return 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    mean_br = float(gray.mean())

    # Threshold to get text pixels
    if mean_br > 140:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Find contours of text
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return 0.0

    # Merge all text contour points
    all_points = np.vstack(contours)

    if len(all_points) < 5:
        return 0.0

    # Get minimum area bounding rectangle
    rect = cv2.minAreaRect(all_points)
    angle = rect[2]  # angle from minAreaRect
    w, h = rect[1]

    # minAreaRect returns angles in [-90, 0) range
    # Normalize: if the rect is wider than tall, the angle is the text angle
    # If it's taller than wide, add 90
    if w < h:
        angle = angle + 90

    # Only report angle if it's significant (>5 degrees from horizontal)
    if abs(angle) < 5:
        return 0.0

    # Clamp to reasonable range
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90

    return round(angle, 1)
