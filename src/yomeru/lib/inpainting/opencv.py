"""
OpenCV inpainting backend.

Uses OpenCV NS (Navier-Stokes) or Telea algorithms. Always available,
no GPU or model download needed.

  - NS    : better for large text blocks and complex backgrounds
  - Telea : better for small isolated characters

Selection is automatic based on the masked area coverage ratio.

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


class OpenCVInpainter:
    """OpenCV NS/Telea inpainting backend (no model required)."""

    @property
    def name(self) -> str:
        return "opencv"

    @classmethod
    def is_available(cls) -> bool:
        return True  # always available

    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        if mask.sum() == 0:
            return image
        return _inpaint_opencv(image, mask)


def _inpaint_opencv(image: Image.Image, mask: np.ndarray) -> Image.Image:
    arr = np.array(image)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    coverage = mask.sum() / 255 / max(1, mask.size)
    flags = cv2.INPAINT_NS if coverage > 0.01 else cv2.INPAINT_TELEA
    result = cv2.inpaint(bgr, mask, inpaintRadius=5, flags=flags)
    return Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))