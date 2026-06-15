"""
Inpainting stage — public interface.

Usage:
    from yomeru.core.typesetting.stages.inpainting import build_inpainter, build_text_mask

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
    region_label: str = "text_bubble",
) -> np.ndarray:
    """
    Build a binary mask for inpainting a text region.

    Approach (same for all region types):
      1. Crop the region from the full page image
      2. Convert to grayscale
      3. Threshold (Otsu) to isolate text as foreground blobs
      4. Filter out connected components touching the bbox edges
         (those are bubble borders, not text)
      5. Morphological close + mild dilate for character coverage
      6. The resulting blob = mask (follows the exact text shape)

    Args:
        image: Full page image (RGB)
        region_bbox: (x1, y1, x2, y2) bounding box of the region
        region_mask: Optional pre-existing mask (from detection model)
        region_label: "text_bubble", "text_free", "sfx", etc.

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

    # 2. Grayscale
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

    # 3. Otsu threshold — text becomes foreground (white=255 in binary)
    mean_brightness = float(gray.mean())
    if mean_brightness > 140:
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
    else:
        _, binary = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

    # 4. Remove connected components touching the edges (bubble borders)
    #    Text characters are centered, borders run along edges.
    num_labels, labels = cv2.connectedComponents(binary)
    edge_labels = set()
    # Collect labels touching any edge
    edge_labels.update(labels[0, :].tolist())       # top row
    edge_labels.update(labels[-1, :].tolist())      # bottom row
    edge_labels.update(labels[:, 0].tolist())       # left col
    edge_labels.update(labels[:, -1].tolist())      # right col
    edge_labels.discard(0)  # background

    # Remove edge-touching components
    for lbl in edge_labels:
        binary[labels == lbl] = 0

    # 5. Morphological close to fill gaps within characters
    close_kernel = np.ones((3, 3), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    # 6. Mild dilate to cover anti-aliased character edges
    dilate_kernel = np.ones((3, 3), np.uint8)
    binary = cv2.dilate(binary, dilate_kernel, iterations=1)

    # 7. Place into full-page mask
    full[y1:y2, x1:x2] = binary

    return full