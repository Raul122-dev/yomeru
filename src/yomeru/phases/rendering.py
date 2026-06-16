"""
Phase 5: Rendering — Render translated text into inpainted bubbles.

Input:  Inpainted images + matching logs + analyses
Output: output/typeset/<filename> (final images) + debug/pXX_s5_final.jpg
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
    Render translated text into inpainted bubble regions.

    Options:
        renderer_backend: str = "pil"
        use_translation: bool = True
        skip_sfx: bool = True
        skip_narration: bool = False
        padding: int = 12
        min_font_size: int = 9
        max_font_size: int = 30
    """
    meta = run.meta()
    use_translation = options.get("use_translation", True)
    source_language = options.get("source_language", meta.get("source_language", "auto"))

    output_dir = run.output_dir()
    pages_dir = run.pages_dir()
    debug_dir = output_dir / "typeset" / "debug"
    typeset_dir = output_dir / "typeset"
    typeset_dir.mkdir(parents=True, exist_ok=True)

    if not debug_dir.exists():
        return PhaseResult(phase="rendering", status="failed", error="Run inpainting phase first")

    # Load analyses
    analyses = _load_analyses(run)
    all_pages = _collect_pages(pages_dir)
    page_map = {i: p for i, p in all_pages}

    if page_scope:
        analyses = [a for a in analyses if a.get("page_number") in page_scope]

    total = len(analyses)
    on_progress({"type": "phase_progress", "phase": "rendering", "total": total, "processed": 0})
    print(f"\n[rendering] {total} pages, engine=scanline", file=sys.stderr)

    results: list[PageResult] = []

    for analysis in sorted(analyses, key=lambda a: a.get("page_number", 0)):
        page_num = analysis.get("page_number", 0)
        page_path = page_map.get(page_num)
        if not page_path:
            continue

        on_progress({"type": "page_start", "phase": "rendering", "page": page_num, "filename": page_path.name})
        t0 = time.time()

        try:
            # Invalidate cached scanline previews so they regenerate on next view
            for scan_file in (
                debug_dir / f"p{page_num:02d}_scanline_preview.jpg",
                debug_dir / f"p{page_num:02d}_scanline_production.jpg",
            ):
                if scan_file.exists():
                    scan_file.unlink()

            # Check prerequisites
            inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
            if not inpainted_path.exists():
                on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": "No inpainted image"})
                results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error="No inpainted image"))
                continue

            log_path = debug_dir / f"p{page_num:02d}_render_log.json"
            if not log_path.exists():
                on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": "No match log"})
                results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error="No match log"))
                continue

            log = json.loads(log_path.read_text())

            # Prefer manually refined matches over auto-generated ones
            refined_matches_path = debug_dir / f"p{page_num:02d}_matches_refined.json"
            if refined_matches_path.exists():
                try:
                    refined = json.loads(refined_matches_path.read_text())
                    matches_data = _build_matches_from_refined(
                        refined, log.get("s3_matching", {})
                    )
                except (json.JSONDecodeError, KeyError):
                    matches_data = log.get("s3_matching", {}).get("matches", [])
            else:
                matches_data = log.get("s3_matching", {}).get("matches", [])
            dialogues = analysis.get("dialogues", [])
            source_lang = analysis.get("source_language", source_language)

            # Load render overrides if they exist
            overrides_path = debug_dir / f"p{page_num:02d}_render_overrides.json"
            overrides = {}
            if overrides_path.exists():
                try:
                    raw_overrides = json.loads(overrides_path.read_text())
                    if isinstance(raw_overrides, list):
                        overrides = {
                            o["dialogue_index"]: o
                            for o in raw_overrides
                            if isinstance(o, dict) and "dialogue_index" in o
                        }
                except (json.JSONDecodeError, KeyError):
                    overrides = {}

            # Build render events from match data (for log/editor sync)
            render_events: list[dict] = []
            for m in matches_data:
                dlg_i = m.get("dialogue_index", -1)
                if dlg_i < 0:
                    continue
                ovr = overrides.get(dlg_i, {})
                dlg = dialogues[dlg_i] if 0 <= dlg_i < len(dialogues) else {}

                if ovr.get("skip") or dlg.get("skip"):
                    render_events.append({
                        "dialogue_index": dlg_i, "status": "skip",
                        "skip_reason": ovr.get("skip_reason") or dlg.get("skip_reason", "analysis"),
                        "region_id": m.get("region_id"), "text": "",
                    })
                else:
                    text = ""
                    if use_translation:
                        text = ovr.get("text_translated") or dlg.get("text_translated") or dlg.get("text", "")
                    else:
                        text = ovr.get("text") or dlg.get("text", "")

                    render_events.append({
                        "dialogue_index": dlg_i,
                        "status": "ok" if text.strip() else "skip",
                        "skip_reason": "" if text.strip() else "empty_text",
                        "region_id": m.get("region_id"),
                        "text": text,
                        "tone": ovr.get("tone") or dlg.get("tone", "neutral"),
                        "bubble_type": dlg.get("bubble_type", "speech"),
                        "font_style": ovr.get("font_style") or dlg.get("font_style") or "bold",
                    })

            ok_count = sum(1 for e in render_events if e["status"] == "ok")
            skip_count = sum(1 for e in render_events if e["status"] == "skip")

            # Generate scanline production (the primary render engine)
            from yomeru.api.routes.phases import get_scanline_preview
            try:
                get_scanline_preview(run.id, page_num, force=1)
            except Exception as scan_err:
                print(f"  [render] scanline generation warning: {scan_err}", file=sys.stderr)

            # Copy scanline production as the final typeset output
            scanline_prod = debug_dir / f"p{page_num:02d}_scanline_production.jpg"
            out_path = typeset_dir / page_path.name
            if scanline_prod.exists():
                import shutil
                if out_path.suffix.lower() in (".jpg", ".jpeg"):
                    shutil.copy2(str(scanline_prod), str(out_path))
                else:
                    Image.open(scanline_prod).save(str(out_path))
                shutil.copy2(str(scanline_prod), str(debug_dir / f"p{page_num:02d}_s5_final.jpg"))

            # Update render log
            log["s5_rendering"] = {"ok": ok_count, "skipped": skip_count, "renders": render_events}
            log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))

            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: {ok_count} rendered, {skip_count} skipped [{elapsed}s]", file=sys.stderr)
            on_progress({
                "type": "page_done", "phase": "rendering", "page": page_num,
                "renders_ok": ok_count, "renders_skipped": skip_count, "elapsed": elapsed,
            })
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=True))

        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: error — {e}", file=sys.stderr)
            on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": str(e)})
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error=str(e)))

    done = sum(1 for r in results if r.success)
    failed = [r.page_num for r in results if not r.success]
    status = "done" if not failed else ("partial" if done > 0 else "failed")
    print(f"[rendering] done — {done}/{total} pages", file=sys.stderr)

    return PhaseResult(
        phase="rendering", status=status, total_pages=total,
        processed_pages=done, failed_pages=failed, page_results=results,
    )


def _load_analyses(run: Run) -> list[dict]:
    """Load analyses from the active file, merged with user edits (same as matching)."""
    f = run.active_analyses_file()
    if not f.exists():
        return []
    original = json.loads(f.read_text())
    from yomeru.core.annotations import AnnotationStore
    store = AnnotationStore(run.output_dir())
    return store.merged_analyses(original)


def _collect_pages(folder: Path) -> list[tuple[int, Path]]:
    pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    return [(i, p) for i, p in enumerate(pages, 1)]


def _expand_free_text_bbox(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    max_expand: int = 80,
    variance_threshold: float = 50.0,
) -> tuple[int, int, int, int]:
    """
    Expand a text_free bbox into surrounding homogeneous area.

    Checks strips of pixels outside the bbox in each direction.
    If the strip has low color variance (uniform background like a sign),
    expand the bbox in that direction.

    Only expands where the background is clearly uniform (not into detailed art).
    """
    arr = np.array(image)
    img_h, img_w = arr.shape[:2]
    x1, y1, x2, y2 = bbox

    def strip_std(strip: np.ndarray) -> float:
        """Compute std of a strip (lower = more uniform)."""
        if strip.size == 0:
            return 999.0
        return float(strip.astype(np.float32).std())

    # Try expanding LEFT
    new_x1 = x1
    for step in range(4, max_expand + 1, 4):
        check_x = max(0, x1 - step)
        strip = arr[y1:y2, check_x:check_x + 4]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_x1 = check_x
        else:
            break

    # Try expanding RIGHT
    new_x2 = x2
    for step in range(4, max_expand + 1, 4):
        check_end = min(img_w, x2 + step)
        check_start = check_end - 4
        if check_start < x2:
            check_start = x2
        strip = arr[y1:y2, check_start:check_end]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_x2 = check_end
        else:
            break

    # Try expanding UP (less aggressive)
    new_y1 = y1
    for step in range(4, max_expand // 2 + 1, 4):
        check_y = max(0, y1 - step)
        strip = arr[check_y:check_y + 4, x1:x2]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_y1 = check_y
        else:
            break

    # Try expanding DOWN
    new_y2 = y2
    for step in range(4, max_expand // 2 + 1, 4):
        check_end = min(img_h, y2 + step)
        check_start = check_end - 4
        if check_start < y2:
            check_start = y2
        strip = arr[check_start:check_end, x1:x2]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_y2 = check_end
        else:
            break

    return (new_x1, new_y1, new_x2, new_y2)


def _build_matches_from_refined(refined: list[dict], s3_data: dict) -> list[dict]:
    """
    Build a matches list from manually refined match overrides.

    The refined file contains user-corrected dialogue→region assignments.
    We merge them with the original auto-generated matches, preferring manual ones.
    """
    # Index original matches by dialogue_index for fallback
    original_matches = {m["dialogue_index"]: m for m in s3_data.get("matches", [])}

    # Index all detected regions by id for bbox lookup
    regions_by_id = {}
    for region in s3_data.get("regions", []):
        regions_by_id[region.get("id") or region.get("region_id")] = region

    # Also extract regions from original matches
    for m in s3_data.get("matches", []):
        rid = m.get("region_id")
        if rid is not None and rid not in regions_by_id:
            regions_by_id[rid] = m.get("region", {})

    result = []
    refined_indices = set()

    for override in refined:
        dlg_i = override.get("dialogue_index")
        if dlg_i is None:
            continue
        refined_indices.add(dlg_i)

        region_id = override.get("region_id")
        # Try to find region geometry from detection data or original matches
        region = None
        if region_id is not None:
            region = regions_by_id.get(region_id)
            if region and "bbox" in region and "x1" not in region:
                bbox = region["bbox"]
                region = {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3],
                          "label": region.get("label", "text_bubble"), "score": 1.0}

        if not region:
            # Fall back to original match's region
            orig = original_matches.get(dlg_i)
            if orig:
                region = orig.get("region", {})

        if region and "x1" in region:
            result.append({
                "dialogue_index": dlg_i,
                "region_id": region_id,
                "match_type": override.get("match_type", "manual"),
                "region": region,
                "scores": {"spatial": 1.0, "text": 1.0, "position": 1.0, "total": 1.0},
                "dialogue_text": override.get("dialogue_text", ""),
            })

    # Keep original matches that weren't overridden
    for dlg_i, m in original_matches.items():
        if dlg_i not in refined_indices:
            result.append(m)

    return result
