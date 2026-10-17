"""
Phase 1: Detection — Detect text regions/bubbles in comic pages.

Input:  Source images in run.pages_dir()
Output: output/page_detections.json
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

from yomeru.core import artifacts
from yomeru.core.runs import Run
from yomeru.phases import PageResult, PhaseResult, ProgressCallback, null_progress

def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """
    Detect text regions in all pages (or a subset).

    Orchestrator: the detector is a registered backend (yomeru/plugins/detection.py).

    Options:
        backend: str = "ogkalu"
        backend_options: dict
        threshold: float = 0.4      (confidence threshold)
    """
    from contextlib import nullcontext

    from yomeru.core.contracts import Region
    from yomeru.core.gpu import gpu_lock
    from yomeru.plugins import get_backend

    spec, detector = get_backend("detection", options.get("backend", "ogkalu"), options.get("backend_options"))
    threshold = options.get("threshold", 0.4)

    output_dir = run.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = artifacts.page_files(run)
    if page_scope:
        pages = [(i, p) for i, p in pages if i in page_scope]

    total = len(pages)
    on_progress({"type": "phase_progress", "phase": "detection", "total": total, "processed": 0})
    print(f"\n[detection] {total} pages, backend={spec.name}, threshold={threshold}", file=sys.stderr)

    results: list[PageResult] = []
    all_detections: dict[int, list[dict]] = {}
    page_sizes: dict[int, tuple[int, int]] = {}

    # Load existing detections if doing partial re-run
    det_file = output_dir / "page_detections.json"
    if page_scope and det_file.exists():
        import json
        for entry in json.loads(det_file.read_text()):
            all_detections[entry["page_number"]] = entry["regions"]
            if "original_w" in entry:
                page_sizes[entry["page_number"]] = (entry["original_w"], entry["original_h"])

    for idx, (page_num, page_path) in enumerate(pages):
        on_progress({
            "type": "page_start", "phase": "detection",
            "page": page_num, "filename": page_path.name,
        })
        t0 = time.time()
        try:
            img = Image.open(page_path).convert("RGB")
            page_sizes[page_num] = (img.width, img.height)
            with (gpu_lock() if spec.needs_gpu else nullcontext()):
                raw = detector.detect(img, threshold)

            # Ids 1..n in backend order; every region must speak the label
            # vocabulary the rest of the pipeline is keyed on (core/labels).
            region_dicts = [
                Region.model_validate({"id": rid, **r, "score": round(r["score"], 4)}).model_dump()
                for rid, r in enumerate(raw, 1)
            ]

            all_detections[page_num] = region_dicts
            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: {len(region_dicts)} regions ({elapsed}s)", file=sys.stderr)

            on_progress({
                "type": "page_done", "phase": "detection",
                "page": page_num, "filename": page_path.name,
                "regions": len(region_dicts), "elapsed": elapsed,
            })
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=True))

        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: error — {e}", file=sys.stderr)
            on_progress({
                "type": "page_error", "phase": "detection",
                "page": page_num, "error": str(e), "elapsed": elapsed,
            })
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error=str(e)))

    # Save detections
    _save_detections(all_detections, page_sizes, output_dir)

    done = sum(1 for r in results if r.success)
    failed = [r.page_num for r in results if not r.success]
    status = "done" if not failed else ("partial" if done > 0 else "failed")

    print(f"[detection] done — {done}/{total} pages", file=sys.stderr)
    run.update(detected_pages=done)

    return PhaseResult(
        phase="detection",
        status=status,
        total_pages=total,
        processed_pages=done,
        failed_pages=failed,
        page_results=results,
    )


def _save_detections(all_detections: dict[int, list[dict]], page_sizes: dict[int, tuple[int, int]], output_dir: Path) -> None:
    """Save all page detections to page_detections.json."""
    import json
    entries = []
    for page_num, regions in sorted(all_detections.items()):
        entry: dict = {"page_number": page_num, "regions": regions}
        if page_num in page_sizes:
            w, h = page_sizes[page_num]
            entry["original_w"] = w
            entry["original_h"] = h
        entries.append(entry)
    (output_dir / "page_detections.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False)
    )
