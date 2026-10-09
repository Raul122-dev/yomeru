"""
LaMa deep learning inpainting backend.

Runs the big-lama TorchScript checkpoint directly with torch (the same model
simple-lama-inpainting ships, without its pillow<10 / numpy<2 pins).
Weights are downloaded on first use into data/models/lama/.
Best for text_free/sfx regions where content-aware fill is needed.
"""
from __future__ import annotations
import sys
from typing import Any

import numpy as np
from PIL import Image

_lama_instance: Any = None


class LamaInpainter:
    """LaMa deep learning inpainter (big-lama TorchScript)."""

    @property
    def name(self) -> str:
        return "lama"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import torch  # noqa: F401
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
        from yomeru.core.weights import ensure_weight
        path = ensure_weight("lama")
        print("  [inpaint] loading LaMa model…", file=sys.stderr)
        _lama_instance = _Lama(path)
        print("  [inpaint] LaMa ready", file=sys.stderr)
        return _lama_instance
    except Exception as e:
        print(f"  [inpaint] LaMa load error: {e}", file=sys.stderr)
        return None


class _Lama:
    """Minimal big-lama TorchScript runner: pads to a multiple of 8, crops back."""

    def __init__(self, path) -> None:
        import torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = torch.jit.load(str(path), map_location=self.device)
        self.model.eval()

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        import torch
        img = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        msk = (np.asarray(mask.convert("L"), dtype=np.float32) > 0).astype(np.float32)
        h, w = msk.shape
        ph, pw = (-h) % 8, (-w) % 8
        img = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="symmetric")
        msk = np.pad(msk, ((0, ph), (0, pw)), mode="symmetric")
        t_img = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).to(self.device)
        t_msk = torch.from_numpy(msk)[None, None].to(self.device)
        with torch.inference_mode():
            out = self.model(t_img, t_msk)[0].permute(1, 2, 0).cpu().numpy()
        out = np.clip(out[:h, :w] * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(out)


MAX_LAMA_SIDE = 2048  # Downscale images larger than this for LaMa inference


def _inpaint_lama(image: Image.Image, mask: np.ndarray) -> Image.Image:
    from .opencv import _inpaint_opencv
    try:
        lama = _get_lama()
        if lama is None:
            return _inpaint_opencv(image, mask)

        orig_size = image.size  # (w, h)
        max_side = max(orig_size)

        if max_side > MAX_LAMA_SIDE:
            # Downscale for faster LaMa inference, then composite back
            scale = MAX_LAMA_SIDE / max_side
            new_w = int(orig_size[0] * scale)
            new_h = int(orig_size[1] * scale)

            small_img = image.resize((new_w, new_h), Image.LANCZOS)
            small_mask = Image.fromarray(mask).convert("L").resize((new_w, new_h), Image.NEAREST)

            small_result = lama(small_img, small_mask)

            # Upscale result back to original size
            result_upscaled = small_result.resize(orig_size, Image.LANCZOS)

            # Composite: use original pixels where mask=0, inpainted where mask>0
            # This preserves full-res detail in non-inpainted areas
            orig_arr = np.array(image)
            result_arr = np.array(result_upscaled)
            mask_bool = mask > 0
            # Dilate mask slightly to blend edges
            import cv2
            blend_mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
            blend_float = (blend_mask / 255.0)[:, :, np.newaxis]
            composited = (orig_arr * (1 - blend_float) + result_arr * blend_float).astype(np.uint8)

            print(f"  [inpaint] LaMa OK (scaled {orig_size[0]}x{orig_size[1]} → {new_w}x{new_h})", file=sys.stderr)
            return Image.fromarray(composited)
        else:
            # Image is small enough — process directly
            mask_img = Image.fromarray(mask).convert("L")
            result = lama(image, mask_img)
            print("  [inpaint] LaMa OK", file=sys.stderr)
            return result
    except Exception as e:
        print(f"  [inpaint] LaMa inference error: {e}, falling back to OpenCV", file=sys.stderr)
        return _inpaint_opencv(image, mask)