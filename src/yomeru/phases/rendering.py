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
    from yomeru.lib.rendering import build_renderer

    meta = run.meta()
    renderer_backend = options.get("renderer_backend", "pil")
    use_translation = options.get("use_translation", True)
    skip_sfx = options.get("skip_sfx", True)
    skip_narration = options.get("skip_narration", False)
    padding = options.get("padding", 12)
    min_font_size = options.get("min_font_size", 9)
    max_font_size = options.get("max_font_size", 30)
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
    print(f"\n[rendering] {total} pages, backend={renderer_backend}", file=sys.stderr)

    renderer = build_renderer(renderer_backend)
    results: list[PageResult] = []

    for analysis in sorted(analyses, key=lambda a: a.get("page_number", 0)):
        page_num = analysis.get("page_number", 0)
        page_path = page_map.get(page_num)
        if not page_path:
            continue

        on_progress({"type": "page_start", "phase": "rendering", "page": page_num, "filename": page_path.name})
        t0 = time.time()

        try:
            # Load inpainted image
            inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
            if not inpainted_path.exists():
                on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": "No inpainted image"})
                results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error="No inpainted image"))
                continue

            inpainted = Image.open(inpainted_path).convert("RGB")

            # Load matching data
            log_path = debug_dir / f"p{page_num:02d}_render_log.json"
            if not log_path.exists():
                on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": "No match log"})
                results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error="No match log"))
                continue

            log = json.loads(log_path.read_text())
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

            result_img = inpainted.copy()
            render_events: list[dict] = []
            ok_count = 0
            skip_count = 0

            for m in matches_data:
                dlg_i = m.get("dialogue_index", -1)
                if dlg_i < 0:
                    continue
                ovr = overrides.get(dlg_i, {})

                # Check for skip override
                if ovr.get("skip"):
                    render_events.append({"dialogue_index": dlg_i, "status": "skip", "skip_reason": "override"})
                    skip_count += 1
                    continue

                dlg = dialogues[dlg_i] if 0 <= dlg_i < len(dialogues) else {}

                # Filter by bubble type (SFX uses subtitle mode, not skipped)
                if skip_narration and dlg.get("bubble_type") == "narration":
                    skip_count += 1
                    continue

                # Get text to render
                text = ""
                if use_translation:
                    text = ovr.get("text_translated") or dlg.get("text_translated") or dlg.get("text", "")
                else:
                    text = ovr.get("text") or dlg.get("text", "")

                if not text.strip():
                    render_events.append({"dialogue_index": dlg_i, "status": "skip", "skip_reason": "empty_text"})
                    skip_count += 1
                    continue

                r = m["region"]
                bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
                region_label = r.get("label", "text_bubble")
                is_free = region_label in ("text_free", "sfx")

                rendered_img, rr = renderer.render(
                    image=result_img, bbox=bbox, text=text,
                    tone=ovr.get("tone") or dlg.get("tone", "neutral"),
                    bubble_type=dlg.get("bubble_type", "speech"),
                    font_style=ovr.get("font_style") or dlg.get("font_style"),
                    source_language=source_lang,
                    padding=padding, min_font_size=min_font_size,
                    max_font_size=ovr.get("font_size_override") or max_font_size,
                    is_free_text=is_free,
                )

                if rr.status == "ok":
                    result_img = rendered_img
                    ok_count += 1
                else:
                    skip_count += 1

                ev = rr.to_dict()
                ev["dialogue_index"] = dlg_i
                ev["region_id"] = m.get("region_id")
                ev["text"] = text
                ev["tone"] = dlg.get("tone", "neutral")
                ev["bubble_type"] = dlg.get("bubble_type", "speech")
                render_events.append(ev)

            # Save final output
            out_path = typeset_dir / page_path.name
            save_kwargs = {"quality": 95} if out_path.suffix.lower() in (".jpg", ".jpeg") else {}
            result_img.save(str(out_path), **save_kwargs)
            result_img.save(str(debug_dir / f"p{page_num:02d}_s5_final.jpg"), quality=88)

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
    f = run.active_analyses_file()
    if not f.exists():
        return []
    return json.loads(f.read_text())


def _collect_pages(folder: Path) -> list[tuple[int, Path]]:
    pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    return [(i, p) for i, p in enumerate(pages, 1)]
