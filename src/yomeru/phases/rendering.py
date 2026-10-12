"""
Phase 5: Rendering — Render translated text into inpainted bubbles.

Input:  Inpainted images + matching logs + analyses
Output: output/typeset/<filename> (final page) + render_log.s5_rendering
        (the engine's per-dialogue records: status, text, font size, lines, box)
"""
from __future__ import annotations

import sys
import time

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
        use_translation: bool = True   (False renders the original text — layout check)
    """
    use_translation = options.get("use_translation", True)

    from yomeru.core import artifacts

    typeset_dir = artifacts.typeset_dir(run, create=True)
    if not artifacts.debug_dir(run).exists():
        return PhaseResult(phase="rendering", status="failed", error="Run inpainting phase first")

    analyses = artifacts.load_analyses(run)
    page_map = dict(artifacts.page_files(run))

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
                artifacts.page_artifact(run, page_num, artifacts.SCANLINE_PREVIEW),
                artifacts.page_artifact(run, page_num, artifacts.SCANLINE_PRODUCTION),
            ):
                if scan_file.exists():
                    scan_file.unlink()

            # Check prerequisites
            if not artifacts.page_artifact(run, page_num, artifacts.S4_INPAINTED).exists():
                on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": "No inpainted image"})
                results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error="No inpainted image"))
                continue

            log = artifacts.load_render_log(run, page_num)
            if log is None:
                on_progress({"type": "page_error", "phase": "rendering", "page": page_num, "error": "No match log"})
                results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error="No match log"))
                continue

            # Scanline engine renders the page; a failure here fails the page
            # (it used to be logged as a warning and the page counted as done).
            from yomeru.core.gpu import gpu_lock
            from yomeru.lib.rendering.scanline_engine import render_page
            with gpu_lock():
                rendered = render_page(run, page_num, use_translation=use_translation)
            scanline_prod = rendered.production_path

            import shutil
            out_path = typeset_dir / page_path.name
            if out_path.suffix.lower() in (".jpg", ".jpeg"):
                shutil.copy2(str(scanline_prod), str(out_path))
            else:
                with Image.open(scanline_prod) as im:
                    im.save(str(out_path))
            # The engine's own records: what was really drawn (size, lines, box)
            ok_count = sum(1 for e in rendered.events if e["status"] == "ok")
            skip_count = len(rendered.events) - ok_count
            artifacts.update_render_log(run, page_num, "s5_rendering",
                                        {"ok": ok_count, "skipped": skip_count, "renders": rendered.events})

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

