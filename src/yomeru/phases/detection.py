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
    Detect text regions in all pages (or a subset).

    Options:
        backend: str = "auto"       (detection model: "auto", "ogkalu", "ctd")
        threshold: float = 0.4      (confidence threshold)
    """
    from yomeru.lib.detection import build_detector

    backend = options.get("backend", run.meta().get("detector_backend", "auto"))
    threshold = options.get("threshold", run.meta().get("detector_threshold", 0.4))

    pages_dir = run.pages_dir()
    output_dir = run.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = _collect_pages(pages_dir)
    if page_scope:
        pages = [(i, p) for i, p in pages if i in page_scope]

    total = len(pages)
    on_progress({"type": "phase_progress", "phase": "detection", "total": total, "processed": 0})
    print(f"\n[detection] {total} pages, backend={backend}, threshold={threshold}", file=sys.stderr)

    detector = build_detector(backend)
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
            regions = detector.detect(img)

            # Apply threshold filter
            regions = [r for r in regions if r.score >= threshold]

            # Convert to serializable dicts
            region_dicts = []
            for rid, r in enumerate(regions, 1):
                region_dicts.append({
                    "id": rid,
                    "x1": r.x1, "y1": r.y1, "x2": r.x2, "y2": r.y2,
                    "label": r.label,
                    "score": round(r.score, 4),
                })

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


def get_status(run: Run) -> dict:
    """Check detection phase status and outputs."""
    det_file = run.output_dir() / "page_detections.json"
    if not det_file.exists():
        return {"status": "pending", "pages_detected": 0}
    import json
    data = json.loads(det_file.read_text())
    return {
        "status": run.get_phase_status("detection"),
        "pages_detected": len(data),
        "total_regions": sum(len(entry["regions"]) for entry in data),
    }


def _collect_pages(folder: Path) -> list[tuple[int, Path]]:
    """Returns list of (page_number, path) sorted."""
    pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    if not pages:
        raise FileNotFoundError(f"No images found in {folder}")
    return [(i, p) for i, p in enumerate(pages, 1)]


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
