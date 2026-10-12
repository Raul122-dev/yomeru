"""
Phase 4: Inpainting — Remove text from matched regions.

Input:  Source images + output/typeset/debug/pXX_render_log.json (matching data)
Output: output/typeset/debug/pXX_s4_inpainted.jpg
"""
from __future__ import annotations

from yomeru.core.labels import TEXT_BUBBLE, is_free as is_free_label
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from yomeru.core.runs import Run
from yomeru.phases import PageResult, PhaseResult, ProgressCallback, null_progress

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

    from yomeru.core import artifacts

    debug_dir = artifacts.debug_dir(run)
    if not debug_dir.exists():
        return PhaseResult(
            phase="inpainting", status="failed", error="Run matching phase first",
        )

    # Pages that went through matching (have a render log)
    pages_to_process = [
        (page_num, page_path)
        for page_num, page_path in artifacts.page_files(run)
        if (not page_scope or page_num in page_scope)
        and artifacts.page_artifact(run, page_num, artifacts.RENDER_LOG).exists()
    ]
    analyses = artifacts.load_analyses(run)

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

    for page_num, page_path in pages_to_process:
        on_progress({"type": "page_start", "phase": "inpainting", "page": page_num, "filename": page_path.name})
        t0 = time.time()

        try:
            img = Image.open(page_path).convert("RGB")
            img_w, img_h = img.size

            log = artifacts.load_render_log(run, page_num) or {}
            combined_mask = np.zeros((img_h, img_w), dtype=np.uint8)
            per_region_masks: list[tuple[tuple[int,int,int,int], str, np.ndarray]] = []
            bubble_mask = np.zeros((img_h, img_w), dtype=np.uint8)
            free_mask = np.zeros((img_h, img_w), dtype=np.uint8)

            matches_list = artifacts.effective_matches(run, page_num, log)
            _skipped_indices = artifacts.skipped_dialogues(artifacts.page_analysis(analyses, page_num))

            for m in matches_list:
                if m.get("dialogue_index", -1) in _skipped_indices:
                    continue
                r = m["region"]
                bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
                label = r.get("label", TEXT_BUBBLE)
                text_mask = build_text_mask(img, bbox, region_label=label)
                per_region_masks.append((bbox, label, text_mask))
                combined_mask = np.maximum(combined_mask, text_mask)
                if is_free_label(label):
                    # LaMa for free text — it needs full page context
                    free_mask = np.maximum(free_mask, text_mask)
                else:
                    bubble_mask = np.maximum(bubble_mask, text_mask)

            # Manual mask edits are a DELTA on top of the auto mask:
            # transparent = keep auto, white = add, black = remove.
            refined_mask_path = artifacts.page_artifact(run, page_num, artifacts.MASK_REFINED)
            if refined_mask_path.exists():
                combined_mask, bubble_mask, free_mask = _apply_mask_edits(
                    refined_mask_path, img.size, combined_mask, bubble_mask, free_mask,
                )

            _save_mask_debug(img, per_region_masks, artifacts.page_artifact(run, page_num, artifacts.S4_MASK_DEBUG))
            # What the mask editor shows as the starting point (auto + edits)
            Image.fromarray(combined_mask).save(artifacts.page_artifact(run, page_num, artifacts.MASK_CURRENT))

            mask_pixels = int(combined_mask.sum() // 255)
            if combined_mask.sum() > 0:
                # Two passes: bubbles with OpenCV, free text with LaMa
                inpainted = img.copy()
                if bubble_mask.sum() > 0:
                    inpainted = opencv_inpainter.inpaint(inpainted, bubble_mask)
                if free_mask.sum() > 0:
                    painter = lama_inpainter or opencv_inpainter
                    inpainted = painter.inpaint(inpainted, free_mask)
            else:
                inpainted = img.copy()

            # Save inpainted image
            inpainted.save(str(artifacts.page_artifact(run, page_num, artifacts.S4_INPAINTED)), quality=88)

            artifacts.update_render_log(run, page_num, "s4_inpainting", {
                "backend_bubble": "opencv",
                "backend_free": "lama" if lama_inpainter else "opencv",
                "backend": "opencv+lama" if lama_inpainter else "opencv",
                "mask_pixels": mask_pixels,
                "total_pixels": img_w * img_h,
                "coverage_pct": round(mask_pixels / (img_w * img_h) * 100, 2),
                "skipped": mask_pixels == 0,
            })

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


def _apply_mask_edits(path, size, combined, bubble, free):
    """Apply the user's mask edits.

    RGBA (current editor): alpha=0 keeps the auto mask, white adds, black removes.
    Added pixels go to the LaMa pass (no region label to route them by).
    Legacy grayscale/RGB files are a full replacement mask.
    """
    edit = Image.open(path)
    if edit.mode != "RGBA":
        full = np.array(edit.convert("L").resize(size, Image.NEAREST))
        full = np.where(full > 127, 255, 0).astype(np.uint8)
        return full, np.zeros_like(full), full
    arr = np.array(edit.resize(size, Image.NEAREST))
    touched = arr[:, :, 3] > 0
    add = touched & (arr[:, :, 0] > 127)
    remove = touched & ~add
    combined = combined.copy(); bubble = bubble.copy(); free = free.copy()
    for m in (combined, bubble, free):
        m[remove] = 0
    combined[add] = 255
    free[add] = 255
    bubble[add] = 0
    return combined, bubble, free


def _save_mask_debug(
    image: Image.Image,
    per_region_masks: list[tuple[tuple[int, int, int, int], str, np.ndarray]],
    out_path: Path,
) -> None:
    """Save a debug image showing the generated masks overlaid on the original."""
    import cv2

    arr = np.array(image).copy()

    # Colors per region type
    colors = {
        "text_bubble": (255, 0, 255),   # magenta
        "text_free": (0, 200, 255),     # cyan
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

    Image.fromarray(arr).save(str(out_path), quality=90)
