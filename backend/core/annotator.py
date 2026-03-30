"""
Annotator — prepares detection-first images for VLM analysis.

Two modes:
  1. annotate_page()         — run detector + draw numbered boxes
  2. annotate_from_detections() — draw numbered boxes from saved region dicts
                                  (no detector, used when detections already exist)
"""
from __future__ import annotations
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class AnnotatedPage:
    """Result of annotating a page image with detection boxes."""
    annotated_image: Image.Image
    regions: list[dict]           # {id, x1, y1, x2, y2, label, score}
    original_size: tuple[int, int]


def annotate_page(
    image: Image.Image,
    detector_backend: str = "auto",
    detector_threshold: float = 0.4,
) -> AnnotatedPage:
    """Run detector on image and draw numbered boxes. Returns AnnotatedPage."""
    from core.typesetting.detector import build_detector

    detector = build_detector(detector_backend)
    try:
        regions = detector.detect(image, threshold=detector_threshold)  # type: ignore[call-arg]
    except TypeError:
        regions = detector.detect(image)

    print(f"  [annotator] {len(regions)} regions detected", file=sys.stderr)
    annotated = _draw_numbered_boxes(image.copy(), regions)

    region_dicts = [
        {
            "id": i + 1,
            "x1": r.x1, "y1": r.y1, "x2": r.x2, "y2": r.y2,
            "label": r.label,
            "score": round(float(r.score), 3),
        }
        for i, r in enumerate(regions)
    ]
    return AnnotatedPage(
        annotated_image=annotated,
        regions=region_dicts,
        original_size=image.size,
    )


def annotate_from_detections(
    image: Image.Image,
    regions: list[dict],
) -> AnnotatedPage:
    """
    Draw numbered boxes from saved region dicts — no detector needed.
    Used when detection already ran and we want to re-use results.

    regions: list of {id, x1, y1, x2, y2, label, score}
    """
    print(f"  [annotator] annotating from {len(regions)} saved regions", file=sys.stderr)

    # create proxy objects that match the interface _draw_numbered_boxes expects
    class _RegionProxy:
        def __init__(self, d: dict):
            self.x1 = d["x1"]; self.y1 = d["y1"]
            self.x2 = d["x2"]; self.y2 = d["y2"]
            self.label = d.get("label", "bubble")
            self.score = d.get("score", 1.0)

    proxies = [_RegionProxy(r) for r in regions]
    annotated = _draw_numbered_boxes(image.copy(), proxies)
    return AnnotatedPage(
        annotated_image=annotated,
        regions=regions,
        original_size=image.size,
    )


def save_detections(
    regions: list[dict],
    output_dir: Path,
    page_number: int,
    original_size: tuple[int, int],
    refined: bool = False,
) -> None:
    """Save detection results. refined=True writes to page_detections_refined.json."""
    fname = "page_detections_refined.json" if refined else "page_detections.json"
    det_file = output_dir / fname

    if det_file.exists():
        try:
            all_dets: list[dict] = json.loads(det_file.read_text())
        except Exception:
            all_dets = []
    else:
        all_dets = []

    all_dets = [d for d in all_dets if d.get("page_number") != page_number]
    all_dets.append({
        "page_number": page_number,
        "original_w": original_size[0],
        "original_h": original_size[1],
        "regions": regions,
    })
    all_dets.sort(key=lambda d: d.get("page_number", 0))
    det_file.write_text(json.dumps(all_dets, indent=2, ensure_ascii=False))


def load_detections(output_dir: Path, page_number: int) -> dict[int, dict]:
    """
    Load detections for a page (prefers refined if exists).
    Returns {region_id: region_dict}.
    """
    # prefer refined
    for fname in ("page_detections_refined.json", "page_detections.json"):
        det_file = output_dir / fname
        if not det_file.exists():
            continue
        try:
            all_dets: list[dict] = json.loads(det_file.read_text())
            for page_det in all_dets:
                if page_det.get("page_number") == page_number:
                    return {r["id"]: r for r in page_det.get("regions", [])}
        except Exception as e:
            print(f"  [annotator] error loading {fname}: {e}", file=sys.stderr)
    return {}


def load_page_detections_list(output_dir: Path, page_number: int) -> list[dict]:
    """Load detections as a plain list (prefers refined). Returns [] if none."""
    d = load_detections(output_dir, page_number)
    return list(d.values())


# ── drawing ────────────────────────────────────────────────────────────────────

_REGION_COLORS = {
    "bubble":       (30, 140, 255),
    "text_bubble":  (30, 140, 255),
    "text_free":    (255, 140, 30),
    "sfx":          (220, 60, 60),
    "caption":      (60, 180, 60),
}
_DEFAULT_COLOR = (100, 100, 200)


def _draw_numbered_boxes(image: Image.Image, regions: list) -> Image.Image:
    overlay = image.convert("RGBA")
    draw_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(draw_layer)

    for i, region in enumerate(regions):
        num = i + 1
        color = _REGION_COLORS.get(region.label, _DEFAULT_COLOR)
        r, g, b = color
        x1, y1, x2, y2 = region.x1, region.y1, region.x2, region.y2
        draw.rectangle([x1, y1, x2, y2], fill=(r, g, b, 40))
        draw.rectangle([x1, y1, x2, y2], outline=(r, g, b, 220), width=2)

        badge_size = max(18, min(28, (x2 - x1) // 4))
        bx1, by1 = x1, max(0, y1 - badge_size // 2)
        bx2, by2 = bx1 + badge_size, by1 + badge_size
        draw.ellipse([bx1, by1, bx2, by2], fill=(r, g, b, 240))

        font_size = max(9, badge_size - 6)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
        draw.text((cx, cy), str(num), fill=(255, 255, 255, 255), font=font, anchor="mm")

    return Image.alpha_composite(overlay, draw_layer).convert("RGB")