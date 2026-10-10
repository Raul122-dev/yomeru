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

            from yomeru.core.matches import effective_matches
            matches_data = effective_matches(log, debug_dir, page_num)
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

            # Scanline engine renders the page; a failure here fails the page
            # (it used to be logged as a warning and the page counted as done).
            from yomeru.core.gpu import gpu_lock
            from yomeru.lib.rendering.scanline_engine import render_page
            with gpu_lock():
                rendered = render_page(run, page_num)
            scanline_prod = rendered.production_path

            import shutil
            out_path = typeset_dir / page_path.name
            if out_path.suffix.lower() in (".jpg", ".jpeg"):
                shutil.copy2(str(scanline_prod), str(out_path))
            else:
                with Image.open(scanline_prod) as im:
                    im.save(str(out_path))
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
    from yomeru.core.paths import list_page_files
    pages = list_page_files(folder)
    return [(i, p) for i, p in enumerate(pages, 1)]


from yomeru.lib.rendering.scanline_engine import _expand_free_text_bbox  # noqa: E402,F401  (compat)
