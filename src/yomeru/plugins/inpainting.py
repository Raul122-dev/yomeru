"""
Inpainting backends.

`classic` — the original technique, moved here unchanged:
  per-region text mask by label (core/labels):
    text_bubble → Otsu inside the box minus border-touching components → OpenCV
    text_free   → whole box → LaMa (needs page context); OpenCV if unavailable
  then the user's mask edit (RGBA delta) is applied on top.

A new technique (e.g. a diffusion inpainter) registers here or in its own
module with the same request/result contract (core/contracts).
"""
from __future__ import annotations

import sys
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from yomeru.core.contracts import InpaintRequest, InpaintResult
from yomeru.core.labels import is_free
from yomeru.plugins import register


class ClassicOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    free_text: Literal["lama", "opencv"] = Field(
        default="lama", title="Free text",
        description="Engine for text outside bubbles (needs surrounding context). "
                    "Bubble interiors are flat, so they always use a fast OpenCV fill.")


@register("inpainting", "classic", options=ClassicOptions, needs_gpu=True,
          description="Text masks per region; OpenCV inside bubbles, LaMa for free text")
class ClassicInpainter:
    def __init__(self, options: ClassicOptions):
        from yomeru.lib.inpainting import build_inpainter, lama_available
        self.options = options
        self.opencv = build_inpainter("opencv")
        use_lama = options.free_text == "lama" and lama_available()
        self.free = build_inpainter("lama") if use_lama else self.opencv
        self.free_name = "lama" if use_lama else "opencv"
        if options.free_text == "lama" and not use_lama:
            print("  [inpaint] LaMa not available, using OpenCV for all regions", file=sys.stderr)

    def inpaint_page(self, req: InpaintRequest) -> InpaintResult:
        from yomeru.lib.inpainting import build_text_mask

        img = req.image
        img_w, img_h = img.size
        combined = np.zeros((img_h, img_w), dtype=np.uint8)
        bubble = np.zeros((img_h, img_w), dtype=np.uint8)
        free = np.zeros((img_h, img_w), dtype=np.uint8)
        per_region: list[tuple[tuple[int, int, int, int], str, np.ndarray]] = []

        for t in req.targets:
            m = build_text_mask(img, t.bbox, region_label=t.label)
            per_region.append((t.bbox, t.label, m))
            combined = np.maximum(combined, m)
            if is_free(t.label):
                free = np.maximum(free, m)
            else:
                bubble = np.maximum(bubble, m)

        if req.mask_edit is not None:
            combined, bubble, free = apply_mask_delta(req.mask_edit, combined, bubble, free)

        out = img.copy()
        if combined.sum() > 0:
            if bubble.sum() > 0:
                out = self.opencv.inpaint(out, bubble)
            if free.sum() > 0:
                out = self.free.inpaint(out, free)

        mask_pixels = int(combined.sum() // 255)
        return InpaintResult(
            image=out,
            mask=combined,
            stats={
                "backend": "opencv+lama" if self.free_name == "lama" else "opencv",
                "mask_pixels": mask_pixels,
                "coverage_pct": round(mask_pixels / (img_w * img_h) * 100, 2),
                "skipped": mask_pixels == 0,
            },
            debug={"mask_debug": mask_overlay(img, per_region)},
        )


def load_mask_edit(path, size: tuple[int, int]) -> np.ndarray:
    """Read the mask editor's file as an RGBA array at page size.

    Legacy grayscale/RGB files are a full replacement mask: returned as RGBA
    with alpha=255 everywhere, so white adds and black removes every pixel.
    """
    edit = Image.open(path)
    if edit.mode != "RGBA":
        full = np.array(edit.convert("L").resize(size, Image.NEAREST))
        rgba = np.zeros((size[1], size[0], 4), dtype=np.uint8)
        rgba[..., 0] = np.where(full > 127, 255, 0)
        rgba[..., 3] = 255
        return rgba
    return np.array(edit.resize(size, Image.NEAREST))


def apply_mask_delta(edit: np.ndarray, combined, bubble, free):
    """alpha=0 keeps the auto mask, white adds, black removes. Added pixels go
    to the free-text pass (no region label to route them by)."""
    touched = edit[:, :, 3] > 0
    add = touched & (edit[:, :, 0] > 127)
    remove = touched & ~add
    combined = combined.copy(); bubble = bubble.copy(); free = free.copy()
    for m in (combined, bubble, free):
        m[remove] = 0
    combined[add] = 255
    free[add] = 255
    bubble[add] = 0
    return combined, bubble, free


def mask_overlay(image: Image.Image, per_region) -> Image.Image:
    """Debug view: each region's mask tinted by label over the page."""
    import cv2

    arr = np.array(image).copy()
    colors = {"text_bubble": (255, 0, 255), "text_free": (0, 200, 255)}
    for bbox, label, mask in per_region:
        color = colors.get(label, (255, 0, 255))
        x1, y1, x2, y2 = bbox
        overlay = arr.copy()
        overlay[mask > 127] = color
        arr = cv2.addWeighted(arr, 0.55, overlay, 0.45, 0)
        cv2.rectangle(arr, (x1, y1), (x2, y2), color, 2)
    legend_y = 30
    for label, color in colors.items():
        cv2.rectangle(arr, (10, legend_y - 15), (25, legend_y), color, -1)
        cv2.putText(arr, label, (32, legend_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        legend_y += 25
    return Image.fromarray(arr)
