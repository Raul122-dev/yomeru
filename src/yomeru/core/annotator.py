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
    from yomeru.core.typesetting.detector import build_detector

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

# Alternating color palette for overlapping regions
_OVERLAP_PALETTE = [
    (30, 140, 255),   # blue
    (220, 60, 180),   # magenta
    (60, 180, 60),    # green
    (255, 160, 30),   # orange
    (120, 80, 220),   # purple
    (0, 200, 200),    # cyan
]


def _compute_overlaps(regions: list) -> dict[int, set[int]]:
    """Find which regions overlap (IoU > 0.05 or intersection area > 10% of smaller)."""
    overlaps: dict[int, set[int]] = {}
    for i, a in enumerate(regions):
        for j, b in enumerate(regions):
            if j <= i:
                continue
            # compute intersection
            ix1 = max(a.x1, b.x1)
            iy1 = max(a.y1, b.y1)
            ix2 = min(a.x2, b.x2)
            iy2 = min(a.y2, b.y2)
            if ix1 >= ix2 or iy1 >= iy2:
                continue
            inter = (ix2 - ix1) * (iy2 - iy1)
            area_a = max(1, (a.x2 - a.x1) * (a.y2 - a.y1))
            area_b = max(1, (b.x2 - b.x1) * (b.y2 - b.y1))
            smaller = min(area_a, area_b)
            if inter / smaller > 0.05:
                overlaps.setdefault(i, set()).add(j)
                overlaps.setdefault(j, set()).add(i)
    return overlaps


def _assign_overlap_colors(regions: list, overlaps: dict[int, set[int]]) -> dict[int, tuple[int, int, int]]:
    """Assign contrasting colors to overlapping regions using graph coloring."""
    color_assignments: dict[int, int] = {}
    for idx in sorted(overlaps.keys()):
        used = {color_assignments[n] for n in overlaps[idx] if n in color_assignments}
        for c in range(len(_OVERLAP_PALETTE)):
            if c not in used:
                color_assignments[idx] = c
                break
        else:
            color_assignments[idx] = 0
    return {idx: _OVERLAP_PALETTE[c % len(_OVERLAP_PALETTE)] for idx, c in color_assignments.items()}


def _draw_numbered_boxes(image: Image.Image, regions: list) -> Image.Image:
    """Draw numbered region boxes with improved visual clarity for VLM consumption.
    
    Improvements over basic annotation:
    - Overlapping regions get contrasting colors (graph coloring)
    - Larger, higher-contrast number badges with white background
    - Dashed separator lines between overlapping regions
    - text_bubble regions get thicker borders (they MUST contain text)
    """
    overlay = image.convert("RGBA")
    draw_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(draw_layer)

    overlaps = _compute_overlaps(regions)
    overlap_colors = _assign_overlap_colors(regions, overlaps)

    for i, region in enumerate(regions):
        num = i + 1
        # Use overlap color if assigned, otherwise default by label
        if i in overlap_colors:
            r, g, b = overlap_colors[i]
        else:
            r, g, b = _REGION_COLORS.get(region.label, _DEFAULT_COLOR)

        x1, y1, x2, y2 = region.x1, region.y1, region.x2, region.y2
        is_text_region = region.label in ("text_bubble", "text_free", "sfx", "caption")
        border_width = 3 if is_text_region else 2

        # Semi-transparent fill (lighter for non-text regions)
        fill_alpha = 35 if is_text_region else 20
        draw.rectangle([x1, y1, x2, y2], fill=(r, g, b, fill_alpha))
        draw.rectangle([x1, y1, x2, y2], outline=(r, g, b, 230), width=border_width)

        # Number badge — larger with white background for max contrast
        badge_size = max(22, min(34, (x2 - x1) // 3))
        # Position badge at top-left corner, slightly inside
        bx1 = x1 + 2
        by1 = max(0, y1 - badge_size // 3)
        bx2 = bx1 + badge_size
        by2 = by1 + badge_size

        # White circle background + colored border for max readability
        draw.ellipse([bx1 - 1, by1 - 1, bx2 + 1, by2 + 1], fill=(255, 255, 255, 240))
        draw.ellipse([bx1, by1, bx2, by2], fill=(r, g, b, 250), outline=(255, 255, 255, 255), width=1)

        font_size = max(11, badge_size - 8)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
        draw.text((cx, cy), str(num), fill=(255, 255, 255, 255), font=font, anchor="mm")

    # Draw dashed separator lines between overlapping region pairs
    for i, neighbors in overlaps.items():
        for j in neighbors:
            if j <= i:
                continue
            a, b = regions[i], regions[j]
            # Draw separator at intersection boundary
            ix1 = max(a.x1, b.x1)
            iy1 = max(a.y1, b.y1)
            ix2 = min(a.x2, b.x2)
            iy2 = min(a.y2, b.y2)
            if ix2 > ix1 and iy2 > iy1:
                # Draw a white dashed line along the longer edge of intersection
                if (ix2 - ix1) > (iy2 - iy1):
                    # Horizontal separator
                    mid_y = (iy1 + iy2) // 2
                    for dx in range(ix1, ix2, 6):
                        draw.line([(dx, mid_y), (min(dx + 3, ix2), mid_y)],
                                  fill=(255, 255, 255, 200), width=2)
                else:
                    # Vertical separator
                    mid_x = (ix1 + ix2) // 2
                    for dy in range(iy1, iy2, 6):
                        draw.line([(mid_x, dy), (mid_x, min(dy + 3, iy2))],
                                  fill=(255, 255, 255, 200), width=2)

    return Image.alpha_composite(overlay, draw_layer).convert("RGB")