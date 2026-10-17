"""
Inpainting stage — public interface.

Usage:
    from yomeru.stages.inpainting import build_inpainter, build_text_mask

    inpainter = build_inpainter("auto")      # or "lama" / "opencv"
    clean_img = inpainter.inpaint(image, mask)

    # Text mask for one region (shape depends on its label)
    mask = build_text_mask(image, region_bbox, region_label=label)

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations

from yomeru.config.labels import TEXT_BUBBLE, is_free as is_free_label
from typing import Any

import numpy as np
from PIL import Image


_cache: dict[str, Any] = {}


def build_inpainter(backend: str = "auto") -> Any:
    """
    Return a cached inpainter instance.

    backend: "auto" | "lama" | "opencv"
      - "auto"   → LaMa if model present, else OpenCV
      - "lama"   → LaMa deep learning (big-lama.pt)
      - "opencv" → OpenCV NS/Telea (always available)
    """
    import sys
    from .lama import LamaInpainter
    from .opencv import OpenCVInpainter

    if backend == "auto":
        backend = "lama" if LamaInpainter.is_available() else "opencv"
        print(f"  [inpaint] auto → {backend}", file=sys.stderr)

    if backend in _cache:
        return _cache[backend]

    if backend == "lama":
        inst: Any = LamaInpainter()
    elif backend == "opencv":
        inst = OpenCVInpainter()
    else:
        raise ValueError(f"unknown inpainter backend: {backend!r}")

    _cache[backend] = inst
    return inst


def lama_available() -> bool:
    from .lama import LamaInpainter
    return LamaInpainter.is_available()


def build_text_mask(
    image: Image.Image,
    region_bbox: tuple[int, int, int, int],
    region_label: str = TEXT_BUBBLE,
) -> np.ndarray:
    """
    Build a binary mask for inpainting a text region.

    For text_bubble:
      1. Crop → grayscale → Otsu threshold
      2. Remove edge-touching components (bubble borders)
      3. Morphological close + dilate

    For text_free / sfx:
      1. Crop → median blur (reduce halftone) → grayscale → Otsu threshold
      2. Do NOT remove edge-touching components (text can touch bbox edges)
      3. Morphological close + stronger dilate for full character coverage

    Args:
        image: Full page image (RGB)
        region_bbox: (x1, y1, x2, y2) bounding box of the region
        region_label: a core.labels label (TEXT_LABELS)

    Returns:
        uint8 mask of same HxW as `image` (255 = inpaint, 0 = preserve).
    """
    import cv2

    img_w, img_h = image.size
    x1, y1, x2, y2 = region_bbox
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img_w, x2), min(img_h, y2)

    full = np.zeros((img_h, img_w), dtype=np.uint8)

    # 1. Crop the region
    arr = np.array(image)
    crop = arr[y1:y2, x1:x2]
    if crop.size == 0:
        return full

    h, w = crop.shape[:2]
    is_free = is_free_label(region_label)

    # For text_free: use full bbox as mask — let LaMa reconstruct the entire area.
    # LaMa has full page context and produces best results with clean, complete masks.
    # Character-level thresholding for free text is unreliable across manga styles.
    if is_free:
        full[y1:y2, x1:x2] = 255
        return full

    # 2. Pre-processing: reduce halftone noise for free text
    if is_free:
        # Stronger median blur for halftone reduction
        crop_processed = cv2.medianBlur(crop, 5)
    else:
        crop_processed = crop

    # 3. Grayscale
    gray = cv2.cvtColor(crop_processed, cv2.COLOR_RGB2GRAY)

    # 4. Threshold to isolate text
    mean_brightness = float(gray.mean())
    gray_std = float(gray.std())

    if is_free:
        # For free text on manga: use strategy based on image characteristics
        if gray_std > 80:
            # High contrast bimodal image (text on halftone/patterned background)
            # Strategy: aggressive low threshold to capture dark text,
            # then filter by component size (text = large blobs, halftone = tiny dots)
            # Use a percentile-based threshold: text is the darkest cluster
            dark_threshold = int(np.percentile(gray, 25))  # darkest 25%
            dark_threshold = max(60, min(120, dark_threshold))
            _, binary = cv2.threshold(gray, dark_threshold, 255, cv2.THRESH_BINARY_INV)

            # Close with larger kernel to connect text strokes
            text_close = np.ones((5, 5), np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, text_close, iterations=2)

            # Remove small components (halftone remnants) — keep only text-sized blobs
            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
            total_area = h * w
            min_text_area = max(30, total_area // 500)  # text chars are at least this big
            for lbl in range(1, num_labels):
                if stats[lbl, cv2.CC_STAT_AREA] < min_text_area:
                    binary[labels == lbl] = 0
        else:
            # Lower contrast: use Otsu + adaptive combined approach
            if mean_brightness > 140:
                _, otsu_binary = cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
                )
            else:
                _, otsu_binary = cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )

            # Adaptive threshold for local contrast variations
            block_size = max(11, (min(h, w) // 8) | 1)
            adaptive_binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV if mean_brightness > 140 else cv2.THRESH_BINARY,
                block_size, 5
            )

            binary = cv2.bitwise_or(otsu_binary, adaptive_binary)
    else:
        # For bubbles: Otsu alone is sufficient (clean white backgrounds)
        if mean_brightness > 140:
            _, binary = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )
        else:
            _, binary = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

    # 5. Connected component filtering
    if not is_free:
        # For bubbles: remove components touching edges (those are bubble borders)
        num_labels, labels = cv2.connectedComponents(binary)
        edge_labels = set()
        edge_labels.update(labels[0, :].tolist())       # top row
        edge_labels.update(labels[-1, :].tolist())      # bottom row
        edge_labels.update(labels[:, 0].tolist())       # left col
        edge_labels.update(labels[:, -1].tolist())      # right col
        edge_labels.discard(0)  # background

        for lbl in edge_labels:
            binary[labels == lbl] = 0
    else:
        # For free text: remove only very small noise components (not text)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
        min_area = max(15, (h * w) // 200)  # minimum component size
        for lbl in range(1, num_labels):
            if stats[lbl, cv2.CC_STAT_AREA] < min_area:
                binary[labels == lbl] = 0

    # 6. Morphological close to fill gaps within characters
    if is_free and gray_std > 80:
        # Stronger close for bimodal regions — fills internal gaps in characters
        close_kernel = np.ones((5, 5), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel, iterations=2)

        # Fill internal holes: any enclosed zero-area inside a text blob becomes mask
        # Use floodFill from the edges to find external background, then invert
        flood = binary.copy()
        fill_mask = np.zeros((h + 2, w + 2), np.uint8)
        cv2.floodFill(flood, fill_mask, (0, 0), 255)
        holes = cv2.bitwise_not(flood)
        binary = cv2.bitwise_or(binary, holes)
    else:
        close_kernel = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    # 7. Dilate to cover character edges (stronger for free text)
    if is_free:
        dilate_kernel = np.ones((5, 5), np.uint8)
        binary = cv2.dilate(binary, dilate_kernel, iterations=2)
    else:
        dilate_kernel = np.ones((3, 3), np.uint8)
        binary = cv2.dilate(binary, dilate_kernel, iterations=1)

    # 8. Place into full-page mask
    full[y1:y2, x1:x2] = binary

    return full