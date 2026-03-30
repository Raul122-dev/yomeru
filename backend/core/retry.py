from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Callable

from core.models import ContextObject, PageAnalysis
from core.pipeline import collect_pages, CHUNK_SIZE, RECENT_PAGES, _emit


def retry_failed_pages(
    pages_folder: Path,
    output_folder: Path,
    model: str,
    comic_format: str,
    api_base: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> list[int]:
    """
    Re-run only the pages that failed (missing from page_analyses.json).
    Uses existing successful analyses as context — doesn't redo completed work.

    Returns list of newly processed page numbers.
    """
    from core.analyzer import analyze_page
    from core.logger import PipelineLogger

    analyses_file = output_folder / "page_analyses.json"
    if not analyses_file.exists():
        raise FileNotFoundError("no existing analyses found — run the full pipeline first")

    existing: list[dict] = json.loads(analyses_file.read_text())
    existing_pages = {a["page_number"] for a in existing}

    all_pages = collect_pages(pages_folder)
    failed_pages = [p for i, p in enumerate(all_pages, 1) if i not in existing_pages]

    if not failed_pages:
        _emit(on_progress, {"type": "retry_info", "message": "no failed pages to retry"})
        return []

    _emit(on_progress, {
        "type": "retry_start",
        "failed": [i+1 for i, p in enumerate(all_pages) if p in failed_pages],
        "total": len(failed_pages),
    })

    log = PipelineLogger(total=len(failed_pages), model=model, comic_format=comic_format)
    log.run_start()

    # rebuild context from existing analyses in page order
    sorted_existing = sorted(existing, key=lambda a: a["page_number"])
    ctx = ContextObject()
    chunk: list[PageAnalysis] = []
    for a_dict in sorted_existing:
        try:
            a = PageAnalysis(**a_dict)
            ctx.update(a)
            chunk.append(a)
            if len(chunk) >= CHUNK_SIZE:
                ctx.chunk_summaries.append(ctx.compress_chunk(chunk))
                chunk = []
        except Exception:
            pass
    if chunk:
        ctx.chunk_summaries.append(ctx.compress_chunk(chunk))

    newly_done: list[dict] = []
    for path in failed_pages:
        page_number = all_pages.index(path) + 1
        prev = ctx.build_context(RECENT_PAGES)
        _emit(on_progress, {"type": "page_start", "page": page_number, "filename": path.name, "total": len(all_pages)})
        log.page_start(page_number, path.name)
        t0 = time.time()

        def on_token(t: str) -> None:
            log.token(t)
            _emit(on_progress, {"type": "token", "page": page_number, "token": t})

        try:
            a = analyze_page(path, page_number, prev, model, comic_format, api_base, on_token=on_token)
            elapsed = time.time() - t0
            ctx.update(a)
            newly_done.append(a.model_dump())
            log.page_done(page_number, len(a.dialogues), len(a.characters_seen), a.scene.mood, elapsed)
            _emit(on_progress, {
                "type": "page_done", "page": page_number,
                "dialogues": len(a.dialogues), "characters": len(a.characters_seen),
                "mood": a.scene.mood, "summary": a.page_summary[:120],
            })
        except Exception as e:
            elapsed = time.time() - t0
            log.page_error(page_number, str(e), elapsed)
            _emit(on_progress, {"type": "page_error", "page": page_number, "error": str(e)})

    # merge newly processed pages back into page_analyses.json
    if newly_done:
        all_analyses = existing + newly_done
        all_analyses.sort(key=lambda a: a["page_number"])
        analyses_file.write_text(
            json.dumps(all_analyses, indent=2, ensure_ascii=False)
        )

        # rebuild context.json with full set
        full_ctx = ContextObject()
        full_chunk: list[PageAnalysis] = []
        for a_dict in all_analyses:
            try:
                a = PageAnalysis(**a_dict)
                full_ctx.update(a)
                full_chunk.append(a)
                if len(full_chunk) >= CHUNK_SIZE:
                    full_ctx.chunk_summaries.append(full_ctx.compress_chunk(full_chunk))
                    full_chunk = []
            except Exception:
                pass
        if full_chunk:
            full_ctx.chunk_summaries.append(full_ctx.compress_chunk(full_chunk))
        (output_folder / "context.json").write_text(full_ctx.model_dump_json(indent=2))

    _emit(on_progress, {
        "type": "retry_done",
        "newly_processed": [a["page_number"] for a in newly_done],
        "total": len(failed_pages),
    })
    log.run_done(len(newly_done), len(failed_pages) - len(newly_done))
    return [a["page_number"] for a in newly_done]