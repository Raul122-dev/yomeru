"""
Phase 2: Analysis — VLM-based page analysis for dialogue, characters, and narrative context.

Input:  Source images + output/page_detections.json
Output: output/page_analyses.json + output/context.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from yomeru.core import artifacts
from yomeru.core.runs import Run
from yomeru.phases import PageResult, PhaseResult, ProgressCallback, null_progress

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}
CHUNK_SIZE = 5
RECENT_PAGES = 2


def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """
    Run VLM analysis on pages.

    Options (from the run's settings snapshot, see core/settings.py):
        backend: analysis backend name (yomeru/plugins/analysis.py)
        backend_options: dict validated by that backend's options model
        model: ModelRef dict    (connection_id + model)
    """
    from yomeru.core.contracts import AnalysisRequest
    from yomeru.core.models import ContextObject, PageAnalysis
    from contextlib import nullcontext
    from yomeru.core.gpu import gpu_lock
    from yomeru.plugins import get_backend
    from PIL import Image
    from yomeru.core.logger import PipelineLogger

    meta = run.meta()
    spec, backend = get_backend("analysis", options.get("backend", "vlm"), options.get("backend_options"))
    from yomeru.core.settings import ModelRef
    model = ModelRef.model_validate(options.get("model") or {})
    comic_format = options.get("comic_format", meta.get("comic_format", "auto"))
    source_language = options.get("source_language", meta.get("source_language", "auto"))
    target_language = options.get("target_language", meta.get("target_language", "Spanish"))
    ui_language = options.get("ui_language", meta.get("ui_language", "English"))
    global_context = options.get("global_context", meta.get("global_context", ""))
    page_context = options.get("page_context", "")
    translation = options.get("translation") or {}
    separate = bool(translation.get("enabled"))

    output_dir = run.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    detections = artifacts.load_detections(run)  # active (refined if edited)
    all_pages = artifacts.page_files(run)
    pages = all_pages if not page_scope else [(i, p) for i, p in all_pages if i in page_scope]

    total = len(pages)
    log = PipelineLogger(total=total, model=model.model, comic_format=comic_format)
    log.run_start()
    on_progress({"type": "phase_progress", "phase": "analysis", "total": total, "processed": 0})
    print(f"\n[analysis] {total} pages, backend={spec.name}, model={model.connection_id}/{model.model}", file=sys.stderr)

    ctx = ContextObject()
    analyses: list[PageAnalysis] = []
    current_chunk: list[PageAnalysis] = []
    results: list[PageResult] = []

    # If retrying, load existing analyses to rebuild context
    if page_scope:
        existing = _load_existing_analyses(output_dir)
        for a in existing:
            if a.page_number not in page_scope:
                ctx.update(a)
                analyses.append(a)

    for idx, (page_num, page_path) in enumerate(pages):
        prev_context = ctx.build_context(RECENT_PAGES) if analyses else None
        on_progress({
            "type": "page_start", "phase": "analysis",
            "page": page_num, "filename": page_path.name,
        })
        log.page_start(page_num, page_path.name)
        t0 = time.time()

        try:
            def on_token(t: str) -> None:
                log.token(t)
                on_progress({"type": "token", "page": page_num, "token": t})

            # A local model shares the GPU with detection/OCR/LaMa
            with (gpu_lock() if spec.needs_gpu else nullcontext()):
                a = backend.analyze_page(AnalysisRequest(
                    image=Image.open(page_path).convert("RGB"),
                    page_number=page_num,
                    regions=list(detections.get(page_num, {}).values()),
                    previous_context=prev_context,
                    comic_format=comic_format,
                    source_language=source_language,
                    target_language=target_language,
                    ui_language=ui_language,
                    global_context=global_context,
                    page_context=page_context,
                    read_only=separate,
                ), model=model, on_token=on_token)

            elapsed = time.time() - t0
            ctx.update(a)
            analyses.append(a)
            current_chunk.append(a)

            log.page_done(page_num, len(a.dialogues), len(a.characters_seen), a.scene.mood, elapsed)
            on_progress({
                "type": "page_done", "phase": "analysis",
                "page": page_num,
                "dialogues": len(a.dialogues),
                "characters": len(a.characters_seen),
                "mood": a.scene.mood,
                "summary": a.page_summary[:120],
            })
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=True))

            if len(current_chunk) >= CHUNK_SIZE:
                ctx.chunk_summaries.append(ctx.compress_chunk(current_chunk))
                current_chunk = []

        except Exception as e:
            elapsed = time.time() - t0
            log.page_error(page_num, str(e), elapsed)
            on_progress({"type": "page_error", "phase": "analysis", "page": page_num, "error": str(e)})
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error=str(e)))

    if current_chunk:
        ctx.chunk_summaries.append(ctx.compress_chunk(current_chunk))
    if hasattr(backend, "release"):
        backend.release()  # a local model frees the GPU for the next phases

    # Save results (merge with existing when using page_scope)
    # Only the pages analysed in THIS run are new; `analyses` also carries the
    # untouched pages loaded above to rebuild context.
    fresh = [a for a in analyses if not page_scope or a.page_number in page_scope]
    _save_analyses(fresh, output_dir, all_pages, source_language, is_scoped=bool(page_scope))
    _save_context(ctx, output_dir)

    if separate and any(r.success for r in results):
        try:
            translate_run(run, translation, source_language, target_language, global_context, on_progress)
        except Exception as e:
            print(f"[analysis] translation failed: {e}", file=sys.stderr)
            return PhaseResult(phase="analysis", status="failed", total_pages=total,
                               processed_pages=sum(r.success for r in results), failed_pages=[],
                               page_results=results, error=f"Reading done, translation failed: {e}")

    done = sum(1 for r in results if r.success)
    failed = [r.page_num for r in results if not r.success]
    status = "done" if not failed else ("partial" if done > 0 else "failed")

    log.run_done(done, len(failed))
    print(f"[analysis] done — {done}/{total} pages", file=sys.stderr)
    run.update(processed_pages=done)

    if done == 0 and total > 0:
        return PhaseResult(
            phase="analysis", status="failed", total_pages=total,
            processed_pages=0, failed_pages=failed, page_results=results,
            error="All pages failed — check model and provider config",
        )

    return PhaseResult(
        phase="analysis", status=status, total_pages=total,
        processed_pages=done, failed_pages=failed, page_results=results,
    )


def get_status(run: Run) -> dict:
    """Check analysis phase status and outputs."""
    analyses_file = run.active_analyses_file()
    if not analyses_file.exists():
        return {"status": "pending", "pages_analyzed": 0}
    data = json.loads(analyses_file.read_text())
    return {
        "status": run.get_phase_status("analysis"),
        "pages_analyzed": len(data),
    }


def _load_existing_analyses(output_dir: Path):
    """Load existing analyses for context rebuilding during retry."""
    from yomeru.core.models import PageAnalysis
    analyses_file = output_dir / "page_analyses.json"
    if not analyses_file.exists():
        return []
    try:
        data = json.loads(analyses_file.read_text())
        return [PageAnalysis(**entry) for entry in data]
    except Exception:
        return []


def _save_analyses(
    analyses: list,
    output_dir: Path,
    all_pages: list[tuple[int, Path]],
    source_language: str,
    is_scoped: bool = False,
) -> None:
    """Save analyses to page_analyses.json with image dimensions.
    
    When is_scoped=True (re-analysis of specific pages), merges new results
    into the existing file instead of overwriting.
    """
    from yomeru.core.analyzer import MAX_ANALYSIS_SIDE
    from PIL import Image

    page_map = {i: p for i, p in all_pages}

    def _model_dims(path: Path) -> tuple[int, int]:
        try:
            with Image.open(path) as im:
                orig_w, orig_h = im.size
            max_dim = max(orig_w, orig_h)
            if max_dim > MAX_ANALYSIS_SIDE:
                scale = MAX_ANALYSIS_SIDE / max_dim
                return max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
            return orig_w, orig_h
        except Exception:
            return 0, 0

    new_entries = []
    for a in sorted(analyses, key=lambda x: x.page_number):
        d = a.model_dump()
        if a.page_number in page_map:
            mw, mh = _model_dims(page_map[a.page_number])
            if mw and mh:
                d["analysis_image_w"] = mw
                d["analysis_image_h"] = mh
        d["source_language"] = source_language
        new_entries.append(d)

    target = output_dir / "page_analyses.json"

    if is_scoped and target.exists():
        # Merge: replace only the re-analyzed pages, keep everything else
        existing = json.loads(target.read_text())
        new_page_nums = {e["page_number"] for e in new_entries}
        merged = [e for e in existing if e.get("page_number") not in new_page_nums]
        merged.extend(new_entries)
        merged.sort(key=lambda x: x.get("page_number", 0))
        entries = merged
    else:
        entries = new_entries

    target.write_text(json.dumps(entries, indent=2, ensure_ascii=False))

    # Also clear any user edits for re-analyzed pages (fresh data replaces old edits)
    if is_scoped:
        from yomeru.core.annotations import AnnotationStore
        store = AnnotationStore(output_dir)
        edits = store.get_edits()
        changed = False
        for entry in new_entries:
            pn = str(entry["page_number"])
            if pn in edits:
                del edits[pn]
                changed = True
        if changed:
            (output_dir / "edits.json").write_text(
                json.dumps(edits, indent=2, ensure_ascii=False)
            )

    # A refined analyses file shadows page_analyses.json as a whole: put the
    # fresh results for the re-analysed pages into it so downstream sees them.
    refined_f = output_dir / "page_analyses_refined.json"
    if refined_f.exists():
        fresh_nums = {e["page_number"] for e in new_entries}
        try:
            refined = json.loads(refined_f.read_text())
        except json.JSONDecodeError:
            refined = []
        refined = [e for e in refined if e.get("page_number") not in fresh_nums] + new_entries
        refined.sort(key=lambda x: x.get("page_number", 0))
        refined_f.write_text(json.dumps(refined, indent=2, ensure_ascii=False))


def _save_context(ctx, output_dir: Path) -> None:
    """Save context object for downstream use."""
    (output_dir / "context.json").write_text(
        json.dumps(ctx.model_dump(), indent=2, ensure_ascii=False)
    )


def translate_run(run: Run, translation: dict, source_language: str, target_language: str,
                  global_context: str, on_progress: ProgressCallback = null_progress) -> dict:
    """Second step of Read & translate (separate translation): the whole
    chapter, from the reading's text + context, into output/translations.json.
    Can be re-run alone (another language or model) without reading again."""
    from yomeru.lib.translation import ChapterInput, translate_chapter

    pages = [a for a in artifacts.load_analyses(run)]
    if translation.get("local"):
        from yomeru.core.gpu import gpu_lock
        from yomeru.lib import local_models as lm
        name = translation.get("local_model") or "auto"
        if name == "auto":
            g = lm.gpu_memory()
            name = lm.suggest_model(g and g["free_gb"]).tag
        server = translation.get("local_server") or lm.OLLAMA_URL

        def ask(system: str, user: str, schema: dict) -> str:
            with gpu_lock():
                return lm.chat_text(name, system, user, schema=schema, num_ctx=16384, base_url=server)
        label = f"local/{name}"
    else:
        from yomeru.core.llm import complete_text, resolve_model
        from yomeru.core.settings import ModelRef
        rm = resolve_model(ModelRef.model_validate(translation.get("model") or {}))

        def ask(system: str, user: str, schema: dict) -> str:
            return complete_text(rm, system, user, json_schema=schema)
        label = rm.label

    print(f"[translate] {label}  {source_language} → {target_language}", file=sys.stderr)
    on_progress({"type": "phase_progress", "phase": "analysis", "step": "translate", "label": label})
    res = translate_chapter(
        ChapterInput(source_language=source_language, target_language=target_language,
                     pages=pages, global_context=global_context),
        ask, on_progress=lambda m: on_progress({"type": "step", "phase": "analysis", "step": "translate", "message": m}))
    if translation.get("local"):
        lm.unload(name, server)
    out = {"model": label, "target_language": target_language, "style": res.style,
           "review": res.review, "lines": res.lines}
    (run.output_dir() / artifacts.TRANSLATIONS).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[translate] {len(res.lines)} lines, {len(res.review)} to review", file=sys.stderr)
    return out
