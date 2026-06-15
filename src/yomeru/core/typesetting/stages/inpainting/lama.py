"""
LaMa deep learning inpainting backend.

Model: big-lama.pt
- LaMa (Large Mask inpainting) with Fourier convolutions
- Best quality for complex manga backgrounds and irregular shapes
- Requires: models/lama/big-lama.pt
  Download: python backend/setup_typesetting.py --download-lama
- Falls back to OpenCV automatically if model not found or inference fails

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

LAMA_MODEL_PATH = Path(__file__).parent.parent.parent.parent.parent / "models" / "lama" / "big-lama.pt"

_lama_model: Any = None


class LamaInpainter:
    """LaMa deep learning inpainter (big-lama.pt checkpoint)."""

    @property
    def name(self) -> str:
        return "lama"

    @classmethod
    def is_available(cls) -> bool:
        return LAMA_MODEL_PATH.exists()

    def inpaint(self, image: Image.Image, mask: np.ndarray) -> Image.Image:
        if mask.sum() == 0:
            return image
        return _inpaint_lama(image, mask)


def _get_lama() -> Any:
    global _lama_model
    if _lama_model is not None:
        return _lama_model
    if not LAMA_MODEL_PATH.exists():
        return None
    try:
        import torch
        print(f"  [inpaint] loading LaMa from {LAMA_MODEL_PATH}…", file=sys.stderr)
        checkpoint = torch.load(str(LAMA_MODEL_PATH), map_location="cpu", weights_only=False)
        import torch.nn as nn
        raw: Any = checkpoint
        if isinstance(raw, dict):
            raw = raw.get("model") or raw.get("state_dict") or raw
        model: Any = raw
        if not hasattr(model, "eval"):
            print("  [inpaint] checkpoint format unrecognized, falling back to OpenCV", file=sys.stderr)
            return None
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()
        _lama_model = model
        print("  [inpaint] LaMa ready", file=sys.stderr)
        return _lama_model
    except Exception as e:
        print(f"  [inpaint] LaMa load error: {e}", file=sys.stderr)
        return None


def _pad_to_stride(t: "Any", stride: int = 8) -> "tuple[Any, tuple[int,int]]":
    import torch.nn.functional as F
    h, w = t.shape[-2], t.shape[-1]
    pad_h = (stride - h % stride) % stride
    pad_w = (stride - w % stride) % stride
    if pad_h == 0 and pad_w == 0:
        return t, (0, 0)
    return F.pad(t, (0, pad_w, 0, pad_h), mode="reflect"), (pad_h, pad_w)


def _inpaint_lama(image: Image.Image, mask: np.ndarray) -> Image.Image:
    from .opencv import _inpaint_opencv
    try:
        import torch
        model = _get_lama()
        if model is None:
            return _inpaint_opencv(image, mask)

        orig_h, orig_w = image.height, image.width
        img_arr = np.array(image).astype(np.float32) / 255.0
        mask_f  = (mask > 0).astype(np.float32)

        img_t  = torch.from_numpy(img_arr.transpose(2, 0, 1)).unsqueeze(0)
        mask_t = torch.from_numpy(mask_f).unsqueeze(0).unsqueeze(0)

        img_t,  (ph, pw) = _pad_to_stride(img_t,  stride=8)
        mask_t, _        = _pad_to_stride(mask_t, stride=8)

        if torch.cuda.is_available():
            img_t, mask_t = img_t.cuda(), mask_t.cuda()

        with torch.no_grad():
            result = model(img_t, mask_t)

        out = result[0] if isinstance(result, (list, tuple)) else result
        if isinstance(out, dict):
            out = out.get("inpainted", list(out.values())[0])

        out_crop = out[..., :orig_h, :orig_w]
        out_np = out_crop[0].cpu().numpy().transpose(1, 2, 0)
        out_np = (out_np * 255).clip(0, 255).astype(np.uint8)
        print("  [inpaint] LaMa OK", file=sys.stderr)
        return Image.fromarray(out_np)
    except Exception as e:
        print(f"  [inpaint] LaMa inference error: {e}", file=sys.stderr)
        return _inpaint_opencv(image, mask)