"""
LaMa deep learning inpainting backend.

Uses `simple-lama-inpainting` package which handles model download
and inference automatically. Best for text_free/sfx regions where
content-aware fill is needed.

Install: pip install simple-lama-inpainting
"""
from __future__ import annotations
import sys
from typing import Any

import numpy as np
from PIL import Image

_lama_instance: Any = None


class LamaInpainter:
    """LaMa deep learning inpainter via simple-lama-inpainting."""

    @property
    def name(self) -> str:
        return "lama"

    @classmethod
    def is_available(cls) -> bool:
        try:
            from simple_lama_inpainting import SimpleLama  # noqa: F401
            return True
        except ImportError:
            return False

    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        if mask.sum() == 0:
            return image
        return _inpaint_lama(image, mask)


def _get_lama() -> Any:
    global _lama_instance
    if _lama_instance is not None:
        return _lama_instance
    try:
        from simple_lama_inpainting import SimpleLama
        print("  [inpaint] loading LaMa model…", file=sys.stderr)
        _lama_instance = SimpleLama()
        print("  [inpaint] LaMa ready", file=sys.stderr)
        return _lama_instance
    except Exception as e:
        print(f"  [inpaint] LaMa load error: {e}", file=sys.stderr)
        return None


def _inpaint_lama(image: Image.Image, mask: np.ndarray) -> Image.Image:
    from .opencv import _inpaint_opencv
    try:
        lama = _get_lama()
        if lama is None:
            return _inpaint_opencv(image, mask)

        # simple-lama expects PIL Image for both image and mask
        mask_img = Image.fromarray(mask).convert("L")
        result = lama(image, mask_img)
        print("  [inpaint] LaMa OK", file=sys.stderr)
        return result
    except Exception as e:
        print(f"  [inpaint] LaMa inference error: {e}, falling back to OpenCV", file=sys.stderr)
        return _inpaint_opencv(image, mask)