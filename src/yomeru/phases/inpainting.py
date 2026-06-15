"""
Phase 4: Inpainting — Remove text from matched regions.

Input:  Source images + output/typeset/debug/pXX_render_log.json (matching data)
Output: output/typeset/debug/pXX_s4_inpainted.jpg
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from yomeru.core.runs import Run
from yomeru.phases import PageResult, PhaseResult, ProgressCallback, null_progress

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """
    Inpaint (remove) text from matched regions.

    Options:
        inpainter_backend: str = "auto"  ("auto", "lama", "opencv")
    """
    from yomeru.lib.inpainting import build_inpainter, build_text_mask, lama_available

    meta = run.meta()
    backend = options.get("inpainter_backend", meta.get("inpainter_backend", "auto"))

    output_dir = run.output_dir()
    pages_dir = run.pages_dir()
    debug_dir = output_dir / "typeset" / "debug"

    if not debug_dir.exists():
        return PhaseResult(
            phase="inpainting", status="failed", error="Run matching phase first",
        )

    all_pages = _collect_pages(pages_dir)
    page_map = {i: p for i, p in all_pages}

    # Determine which pages to process
    pages_to_process = []
    for page_num, page_path in all_pages:
        if page_scope and page_num not in page_scope:
            continue
        log_path = debug_dir / f"p{page_num:02d}_render_log.json"
        if log_path.exists():
            pages_to_process.append((page_num, page_path, log_path))

    total = len(pages_to_process)
    on_progress({"type": "phase_progress", "phase": "inpainting", "total": total, "processed": 0})
    print(f"\n[inpainting] {total} pages, backend={backend}", file=sys.stderr)

    # Build inpainters: OpenCV for bubbles, LaMa for free text (if available)
    opencv_inpainter = build_inpainter("opencv")
    lama_inpainter = build_inpainter("lama") if lama_available() else None
    if lama_inpainter:
        print("  [inpaint] using LaMa for text_free/sfx, OpenCV for text_bubble", file=sys.stderr)
    else:
        print("  [inpaint] LaMa not available, using OpenCV for all regions", file=sys.stderr)

    results: list[PageResult] = []

    for page_num, page_path, log_path in pages_to_process:
        on_progress({"type": "page_start", "phase": "inpainting", "page": page_num, "filename": page_path.name})
        t0 = time.time()

        try:
            img = Image.open(page_path).convert("RGB")
            img_w, img_h = img.size

            # Check for manually edited mask
            refined_mask_path = debug_dir / f"p{page_num:02d}_mask_refined.png"
            if refined_mask_path.exists():
                mask_img = Image.open(refined_mask_path).convert("L").resize(img.size)
                combined_mask = np.array(mask_img)
                # Manual mask → use single inpainter (prefer lama)
                mask_pixels = int(combined_mask.sum() // 255)
                if combined_mask.sum() > 0:
                    inpainter = lama_inpainter or opencv_inpainter
                    inpainted = inpainter.inpaint(img, combined_mask)
                else:
                    inpainted = img.copy()
            else:
                # Build per-region masks and inpaint progressively
                log = json.loads(log_path.read_text())
                combined_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                per_region_masks: list[tuple[tuple[int,int,int,int], str, np.ndarray]] = []

                bubble_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                free_mask = np.zeros((img_h, img_w), dtype=np.uint8)

                for m in log.get("s3_matching", {}).get("matches", []):
                    r = m["region"]
                    bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
                    label = r.get("label", "text_bubble")
                    text_mask = build_text_mask(img, bbox, region_label=label)
                    per_region_masks.append((bbox, label, text_mask))
                    combined_mask = np.maximum(combined_mask, text_mask)

                    if label in ("text_free", "sfx"):
                        free_mask = np.maximum(free_mask, text_mask)
                    else:
                        bubble_mask = np.maximum(bubble_mask, text_mask)

                # Save mask debug overlay
                _save_mask_debug(img, per_region_masks, debug_dir, page_num)

                mask_pixels = int(combined_mask.sum() // 255)

                if combined_mask.sum() > 0:
                    # Inpaint in two passes: bubbles with OpenCV, free text with LaMa
                    inpainted = img.copy()
                    if bubble_mask.sum() > 0:
                        inpainted = opencv_inpainter.inpaint(inpainted, bubble_mask)
                    if free_mask.sum() > 0:
                        painter = lama_inpainter or opencv_inpainter
                        inpainted = painter.inpaint(inpainted, free_mask)
                else:
                    inpainted = img.copy()

            # Save inpainted image
            inpainted.save(str(debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"), quality=88)

            # Update render log with inpainting info
            log = json.loads(log_path.read_text())
            log["s4_inpainting"] = {
                "backend_bubble": "opencv",
                "backend_free": "lama" if lama_inpainter else "opencv",
                "backend": "opencv+lama" if lama_inpainter else "opencv",
                "mask_pixels": mask_pixels,
                "total_pixels": img_w * img_h,
                "coverage_pct": round(mask_pixels / (img_w * img_h) * 100, 2),
                "skipped": mask_pixels == 0,
            }
            log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))

            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: inpainted ({mask_pixels}px masked) [{elapsed}s]", file=sys.stderr)
            on_progress({
                "type": "page_done", "phase": "inpainting", "page": page_num,
                "mask_pixels": mask_pixels, "elapsed": elapsed,
            })
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=True))

        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: error — {e}", file=sys.stderr)
            on_progress({"type": "page_error", "phase": "inpainting", "page": page_num, "error": str(e)})
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error=str(e)))

    done = sum(1 for r in results if r.success)
    failed = [r.page_num for r in results if not r.success]
    status = "done" if not failed else ("partial" if done > 0 else "failed")
    print(f"[inpainting] done — {done}/{total} pages", file=sys.stderr)

    return PhaseResult(
        phase="inpainting", status=status, total_pages=total,
        processed_pages=done, failed_pages=failed, page_results=results,
    )


def _collect_pages(folder: Path) -> list[tuple[int, Path]]:
    pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    return [(i, p) for i, p in enumerate(pages, 1)]


def _save_mask_debug(
    image: Image.Image,
    per_region_masks: list[tuple[tuple[int, int, int, int], str, np.ndarray]],
    debug_dir: Path,
    page_num: int,
) -> None:
    """Save a debug image showing the generated masks overlaid on the original."""
    import cv2

    arr = np.array(image).copy()

    # Colors per region type
    colors = {
        "text_bubble": (255, 0, 255),   # magenta
        "text_free": (0, 200, 255),     # cyan
        "sfx": (255, 165, 0),           # orange
    }

    for bbox, label, mask in per_region_masks:
        color = colors.get(label, (255, 0, 255))
        x1, y1, x2, y2 = bbox

        # Overlay mask area with semi-transparent color
        mask_bool = mask > 127
        overlay = arr.copy()
        overlay[mask_bool] = color
        arr = cv2.addWeighted(arr, 0.55, overlay, 0.45, 0)

        # Draw bbox rectangle
        cv2.rectangle(arr, (x1, y1), (x2, y2), color, 2)

    # Add legend
    legend_y = 30
    for label, color in colors.items():
        cv2.rectangle(arr, (10, legend_y - 15), (25, legend_y), color, -1)
        cv2.putText(arr, label, (32, legend_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        legend_y += 25

    out_path = debug_dir / f"p{page_num:02d}_s4_mask_debug.jpg"
    Image.fromarray(arr).save(str(out_path), quality=90)
