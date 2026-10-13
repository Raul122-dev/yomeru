"""
Angle detection for rotated free text.

Uses centroid-based line fitting: divides the text region into vertical strips,
computes the center of mass of text pixels in each strip, then fits a line
through those centroids. The slope of that line IS the text baseline angle.
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

    Uses centroid line-fitting on text pixels for robust angle detection.
    Returns angle in degrees, counter-clockwise positive (text rising to the right),
    i.e. PIL's Image.rotate convention.
    Only returns non-zero for significant rotations (>3°).
    """
    x1, y1, x2, y2 = bbox
    arr = np.array(image)
    crop = arr[y1:y2, x1:x2]

    if crop.size == 0:
        return 0.0

    h, w = crop.shape[:2]
    if w < 20 or h < 10:
        return 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    mean_br = float(gray.mean())

    # Threshold to get text pixels
    if mean_br > 140:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Method 1: Centroid line fitting
    # Divide into vertical strips, compute centroid Y for each strip
    n_strips = max(5, w // 10)
    strip_w = w / n_strips
    centroids: list[tuple[float, float]] = []

    for i in range(n_strips):
        sx = int(i * strip_w)
        ex = int((i + 1) * strip_w)
        strip = binary[:, sx:ex]
        text_pixels = np.where(strip > 0)
        if len(text_pixels[0]) > 5:
            cy = float(text_pixels[0].mean())
            cx = (sx + ex) / 2.0
            centroids.append((cx, cy, len(text_pixels[0])))

    if len(centroids) < 3:
        return 0.0

    # Filter out strips with very few pixels (likely noise/edge artifacts)
    if len(centroids) > 3:
        median_count = sorted(c[2] for c in centroids)[len(centroids) // 2]
        min_count = max(10, median_count // 4)
        centroids = [c for c in centroids if c[2] >= min_count]

    if len(centroids) < 3:
        return 0.0

    # Fit a line through centroids using least squares
    xs = np.array([c[0] for c in centroids])
    ys = np.array([c[1] for c in centroids])

    # Linear regression: y = mx + b
    n = len(xs)
    sum_x = xs.sum()
    sum_y = ys.sum()
    sum_xx = (xs * xs).sum()
    sum_xy = (xs * ys).sum()

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-6:
        return 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom

    # Check R² to ensure the fit is good (not just noise)
    y_pred = slope * xs + (sum_y - slope * sum_x) / n
    ss_res = ((ys - y_pred) ** 2).sum()
    ss_tot = ((ys - ys.mean()) ** 2).sum()
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Only trust the angle if the linear fit is reasonable (R² > 0.3)
    if r_squared < 0.3:
        return 0.0

    # Convert slope to angle in degrees
    # Negate because image Y-axis points DOWN (positive slope = visual tilt downward)
    angle = -float(np.degrees(np.arctan(slope)))

    # Only report significant angles
    if abs(angle) < 3:
        return 0.0

    # Clamp to reasonable text rotation range
    angle = max(-35, min(35, angle))

    return round(angle, 1)
