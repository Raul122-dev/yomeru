"""
Phase 4: Inpainting — erase the original text of matched regions.

Orchestrator only: the technique is a registered backend
(yomeru/plugins/inpainting.py, selected by `inpainting.backend`).

Input:  effective matches (render log + refined matches), skipped dialogues,
        the user's mask edit (pNN_mask_refined.png)
Output: typeset/debug/pNN_s4_inpainted.jpg, pNN_mask_current.png,
        pNN_s4_mask_debug.jpg, render_log.s4_inpainting
"""
from __future__ import annotations

import sys
import time
from contextlib import nullcontext

from PIL import Image

from yomeru.core.labels import TEXT_BUBBLE
from yomeru.core.runs import Run
from yomeru.phases import PageResult, PhaseResult, ProgressCallback, null_progress


def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """
    Options:
        backend: str          registered inpainting backend (default "classic")
        backend_options: dict validated by that backend's options model
    """
    from yomeru.core import artifacts
    from yomeru.core.contracts import InpaintRequest, InpaintTarget
    from yomeru.core.gpu import gpu_lock
    from yomeru.plugins import get_backend
    from yomeru.plugins.inpainting import load_mask_edit

    if not artifacts.debug_dir(run).exists():
        return PhaseResult(phase="inpainting", status="failed", error="Run matching phase first")

    spec, backend = get_backend("inpainting", options.get("backend", "classic"), options.get("backend_options"))

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
    print(f"\n[inpainting] {total} pages, backend={spec.name}", file=sys.stderr)

    results: list[PageResult] = []
    for page_num, page_path in pages_to_process:
        on_progress({"type": "page_start", "phase": "inpainting", "page": page_num, "filename": page_path.name})
        t0 = time.time()
        try:
            img = Image.open(page_path).convert("RGB")
            log = artifacts.load_render_log(run, page_num) or {}
            skipped = artifacts.skipped_dialogues(artifacts.page_analysis(analyses, page_num),
                                                  artifacts.load_render_overrides(run, page_num))
            targets = [
                InpaintTarget(
                    bbox=(m["region"]["x1"], m["region"]["y1"], m["region"]["x2"], m["region"]["y2"]),
                    label=m["region"].get("label", TEXT_BUBBLE),
                    dialogue_index=m.get("dialogue_index", -1),
                )
                for m in artifacts.effective_matches(run, page_num, log)
                if m.get("dialogue_index", -1) not in skipped
            ]
            edit_path = artifacts.page_artifact(run, page_num, artifacts.MASK_REFINED)
            mask_edit = load_mask_edit(edit_path, img.size) if edit_path.exists() else None

            with (gpu_lock() if spec.needs_gpu else nullcontext()):
                res = backend.inpaint_page(InpaintRequest(image=img, targets=targets, mask_edit=mask_edit))

            if "mask_debug" in res.debug:
                res.debug["mask_debug"].save(
                    str(artifacts.page_artifact(run, page_num, artifacts.S4_MASK_DEBUG)), quality=90)
            # Starting point of the mask editor (auto + edits)
            Image.fromarray(res.mask).save(artifacts.page_artifact(run, page_num, artifacts.MASK_CURRENT))
            res.image.save(str(artifacts.page_artifact(run, page_num, artifacts.S4_INPAINTED)), quality=88)
            artifacts.update_render_log(run, page_num, "s4_inpainting", res.stats)

            mask_pixels = res.stats.get("mask_pixels", 0)
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
