"""
Pipeline — orchestrates detection and analysis phases.

Three entry points:
  run_detection()  — Phase 1: detect text regions in all pages
  run_analysis()   — Phase 2: VLM analysis (uses saved/refined detections)
  run_pipeline()   — Phase 1+2 combined (backwards compat, used by "run all")
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from typing import Callable

from core.analyzer import analyze_page
from core.logger import PipelineLogger
from core.models import ContextObject, PageAnalysis

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}
CHUNK_SIZE = 5
RECENT_PAGES = 2


def collect_pages(folder: Path) -> list[Path]:
    pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    if not pages:
        raise FileNotFoundError(f"no images in {folder}")
    return pages


# ── Phase 1: Detection ────────────────────────────────────────────────────────

def run_detection(
    pages_folder: Path,
    output_folder: Path,
    detector_backend: str = "auto",
    detector_threshold: float = 0.4,
    on_progress: Callable[[dict], None] | None = None,
) -> int:
    """
    Run the text region detector on all pages and save page_detections.json.
    Returns number of pages successfully detected.
    """
    from core.annotator import annotate_page, save_detections
    from PIL import Image as _PIL

    output_folder.mkdir(parents=True, exist_ok=True)
    pages = collect_pages(pages_folder)

    _emit(on_progress, {"type": "detect_start", "total": len(pages)})
    print(f"\n[detection] starting — {len(pages)} pages, backend={detector_backend}", file=sys.stderr)

    done = 0
    for i, path in enumerate(pages, 1):
        _emit(on_progress, {"type": "detect_page_start", "page": i, "filename": path.name})
        t0 = time.time()
        try:
            img = _PIL.open(path).convert("RGB")
            annotated = annotate_page(img, detector_backend, detector_threshold)
            save_detections(annotated.regions, output_folder, i, annotated.original_size)
            elapsed = round(time.time() - t0, 2)
            n = len(annotated.regions)
            print(f"  p{i}: {n} regions ({elapsed}s)", file=sys.stderr)
            _emit(on_progress, {
                "type": "detect_page_done", "page": i,
                "filename": path.name, "regions": n, "elapsed": elapsed,
            })
            done += 1
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            print(f"  p{i}: detection error — {e}", file=sys.stderr)
            _emit(on_progress, {"type": "detect_page_error", "page": i, "error": str(e), "elapsed": elapsed})

    _emit(on_progress, {"type": "detect_done", "done": done, "total": len(pages)})
    print(f"[detection] done — {done}/{len(pages)} pages", file=sys.stderr)
    return done


# ── Phase 2: Analysis ─────────────────────────────────────────────────────────

def run_analysis(
    pages_folder: Path,
    output_folder: Path,
    model: str,
    comic_format: str,
    api_base: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
    source_language: str = "auto",
    translate: bool = False,
    target_language: str | None = None,
    ui_language: str = "English",
    global_context: str = "",
    # If True, skip re-running detection — use saved detections instead
    use_saved_detections: bool = True,
    # Only used when use_saved_detections=False (fresh detection)
    detector_backend: str = "auto",
    detector_threshold: float = 0.4,
) -> ContextObject:
    """
    Run VLM analysis on all pages. By default uses saved/refined detections.
    Returns a ContextObject with all page analyses.
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    pages = collect_pages(pages_folder)
    ctx = ContextObject()
    analyses: list[PageAnalysis] = []
    current_chunk: list[PageAnalysis] = []
    errors = 0

    log = PipelineLogger(total=len(pages), model=model, comic_format=comic_format)
    log.run_start()
    _emit(on_progress, {"type": "start", "total": len(pages)})
    print(f"\n[analysis] starting — {len(pages)} pages, use_saved_detections={use_saved_detections}", file=sys.stderr)

    for i, path in enumerate(pages, 1):
        prev = ctx.build_context(RECENT_PAGES) if analyses else None
        _emit(on_progress, {"type": "page_start", "page": i, "total": len(pages), "filename": path.name})
        log.page_start(i, path.name)
        t0 = time.time()

        try:
            def on_token(t: str) -> None:
                log.token(t)
                _emit(on_progress, {"type": "token", "page": i, "token": t})

            def on_detect_done(ev: dict) -> None:
                _emit(on_progress, ev)

            # If using saved detections, pass None for output_dir so analyzer
            # uses annotate_from_detections instead of re-running the detector
            effective_output_dir = None if use_saved_detections else output_folder

            a = analyze_page(
                image_path=path,
                page_number=i,
                previous_context=prev,
                model=model,
                comic_format=comic_format,
                api_base=api_base,
                on_token=on_token,
                source_language=source_language,
                translate=translate,
                target_language=target_language,
                ui_language=ui_language,
                global_context=global_context,
                output_dir=effective_output_dir,
                detector_backend=detector_backend,
                detector_threshold=detector_threshold,
                on_detect_done=on_detect_done,
                # Pass saved detections dir so analyzer can load them
                saved_detections_dir=output_folder if use_saved_detections else None,
            )
            elapsed = time.time() - t0
            ctx.update(a)
            analyses.append(a)
            current_chunk.append(a)

            log.page_done(i, len(a.dialogues), len(a.characters_seen), a.scene.mood, elapsed)
            _emit(on_progress, {
                "type": "page_done", "page": i,
                "dialogues": len(a.dialogues),
                "characters": len(a.characters_seen),
                "mood": a.scene.mood,
                "summary": a.page_summary[:120],
            })

            if len(current_chunk) >= CHUNK_SIZE:
                ctx.chunk_summaries.append(ctx.compress_chunk(current_chunk))
                current_chunk = []

        except Exception as e:
            elapsed = time.time() - t0
            errors += 1
            log.page_error(i, str(e), elapsed)
            _emit(on_progress, {"type": "page_error", "page": i, "error": str(e)})

    if current_chunk:
        ctx.chunk_summaries.append(ctx.compress_chunk(current_chunk))

    _save_analyses(analyses, output_folder, pages, source_language)

    log.run_done(len(analyses), errors)
    _emit(on_progress, {"type": "done", "processed": len(analyses), "total": len(pages)})

    if errors == len(pages) and not analyses:
        raise RuntimeError(f"all {len(pages)} pages failed — check model and provider config")

    return ctx


# ── Combined (backwards compat) ───────────────────────────────────────────────

def run_pipeline(
    pages_folder: Path,
    output_folder: Path,
    model: str,
    comic_format: str,
    api_base: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
    source_language: str = "auto",
    translate: bool = False,
    target_language: str | None = None,
    ui_language: str = "English",
    global_context: str = "",
    detector_backend: str = "auto",
    detector_threshold: float = 0.4,
) -> ContextObject:
    """
    Phase 1 + Phase 2 combined. Emits detection events then analysis events.
    Backwards compatible with existing callers.
    """
    # Phase 1
    run_detection(
        pages_folder=pages_folder,
        output_folder=output_folder,
        detector_backend=detector_backend,
        detector_threshold=detector_threshold,
        on_progress=on_progress,
    )

    # Phase 2 — use the detections we just saved
    return run_analysis(
        pages_folder=pages_folder,
        output_folder=output_folder,
        model=model,
        comic_format=comic_format,
        api_base=api_base,
        on_progress=on_progress,
        source_language=source_language,
        translate=translate,
        target_language=target_language,
        ui_language=ui_language,
        global_context=global_context,
        use_saved_detections=True,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _save_analyses(
    analyses: list[PageAnalysis],
    output_folder: Path,
    pages: list[Path],
    source_language: str,
) -> None:
    """Persist analyses to page_analyses.json with model dimensions."""
    from core.analyzer import MAX_ANALYSIS_SIDE
    from PIL import Image as _PIL

    def _model_dims(path: Path) -> tuple[int, int]:
        try:
            with _PIL.open(path) as im:
                orig_w, orig_h = im.size
            max_dim = max(orig_w, orig_h)
            if max_dim > MAX_ANALYSIS_SIDE:
                scale = MAX_ANALYSIS_SIDE / max_dim
                return max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
            return orig_w, orig_h
        except Exception:
            return 0, 0

    page_map = {i + 1: p for i, p in enumerate(pages)}

    def _with_img_size(a: PageAnalysis) -> dict:
        d = a.model_dump()
        if a.page_number in page_map:
            mw, mh = _model_dims(page_map[a.page_number])
            if mw and mh:
                d["analysis_image_w"] = mw
                d["analysis_image_h"] = mh
        d["source_language"] = source_language
        return d

    dicts = [_with_img_size(a) for a in analyses if a.page_number in page_map]
    (output_folder / "page_analyses.json").write_text(
        json.dumps(dicts, indent=2, ensure_ascii=False)
    )


def _emit(fn: Callable | None, ev: dict) -> None:
    if fn:
        try:
            fn(ev)
        except Exception:
            pass