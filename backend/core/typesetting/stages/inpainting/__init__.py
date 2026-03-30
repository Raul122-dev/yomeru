"""
Inpainting stage — public interface.

Usage:
    from core.typesetting.stages.inpainting import build_inpainter, build_text_mask

    inpainter = build_inpainter("auto")      # or "lama" / "opencv"
    clean_img = inpainter.inpaint(image, mask)

    # Build mask from detected region
    mask = build_text_mask(image, region.bbox, region.mask)

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from PIL import Image


class BaseInpainter(Protocol):
    """Interface every inpainting backend must satisfy."""
    @property
    def name(self) -> str: ...

    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image: ...


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
    region_mask: np.ndarray | None = None,
) -> np.ndarray:
    """
    Build a binary mask of text pixels within a detected region.

    Uses Otsu thresholding adapted to the region's background brightness.
    Returns a uint8 mask of the same HxW as `image` (255 = text, 0 = background).
    """
    import cv2
    arr = np.array(image)
    h, w = arr.shape[:2]
    x1, y1, x2, y2 = region_bbox
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, max(x1+1, x2)), min(h, max(y1+1, y2))

    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    region_gray = gray[y1:y2, x1:x2]
    if region_gray.size == 0:
        return np.zeros((h, w), dtype=np.uint8)

    roi_mask = region_mask[y1:y2, x1:x2] if region_mask is not None else None
    pixels = (region_gray[roi_mask > 0] if roi_mask is not None else region_gray).flatten()
    mean_br = float(pixels.mean()) if len(pixels) > 0 else 127.0

    if mean_br > 150:
        _, text = cv2.threshold(region_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, text = cv2.threshold(region_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if roi_mask is not None:
        text = cv2.bitwise_and(text, roi_mask)

    kernel = np.ones((3, 3), np.uint8)
    text = cv2.dilate(text, kernel, iterations=2)

    full = np.zeros((h, w), dtype=np.uint8)
    full[y1:y2, x1:x2] = text
    return full