from __future__ import annotations
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from core.config import config, DATA_DIR
from core.runs import Run

router = APIRouter(prefix="/runs", tags=["runs"])

from api.state import queues as _queues


# ── list / get ────────────────────────────────────────────────────────────────

@router.get("")
def list_runs():
    return Run.list_all()


@router.get("/{run_id}")
def get_run(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    return run.meta()


@router.get("/{run_id}/pages/{filename}")
def get_page_image(run_id: str, filename: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    path = run.pages_dir() / filename
    if not path.exists(): raise HTTPException(404, "image not found")
    return FileResponse(path)


@router.get("/{run_id}/pages")
def list_pages(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    supported = {".jpg", ".jpeg", ".png", ".webp"}
    files = sorted(p for p in run.pages_dir().iterdir() if p.suffix.lower() in supported)
    return [{"page": i + 1, "filename": p.name} for i, p in enumerate(files)]


@router.get("/{run_id}/analyses")
def get_analyses(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    f = run.active_analyses_file()
    if not f.exists(): raise HTTPException(404, "analyses not ready")
    return json.loads(f.read_text())


@router.get("/{run_id}/context")
def get_context(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    if not run.context_file().exists(): raise HTTPException(404, "context not ready")
    return json.loads(run.context_file().read_text())


# ── detections ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/detections")
def get_detections(run_id: str):
    """Return all page detections (prefers refined if exists)."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    f = run.active_detections_file()
    if not f.exists(): raise HTTPException(404, "detections not ready")
    return json.loads(f.read_text())


@router.get("/{run_id}/detections/{page_num}")
def get_page_detections(run_id: str, page_num: int):
    """Return detections for a single page (prefers refined)."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    f = run.active_detections_file()
    if not f.exists(): raise HTTPException(404, "detections not ready")
    all_dets = json.loads(f.read_text())
    page = next((d for d in all_dets if d.get("page_number") == page_num), None)
    if not page: raise HTTPException(404, f"page {page_num} not found")
    return page


@router.put("/{run_id}/detections/{page_num}")
def save_page_detections(run_id: str, page_num: int, body: dict):
    """Save refined detections for a single page."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    from core.annotator import save_detections
    regions = body.get("regions", [])
    original_w = body.get("original_w", 0)
    original_h = body.get("original_h", 0)
    save_detections(regions, run.output_dir(), page_num, (original_w, original_h), refined=True)
    return {"ok": True, "regions": len(regions)}


@router.delete("/{run_id}/detections/{page_num}/refined", status_code=204)
def revert_page_detections(run_id: str, page_num: int):
    """Remove refined detections for a page (revert to original)."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    refined = run.detections_file(refined=True)
    if refined.exists():
        try:
            all_dets = json.loads(refined.read_text())
            all_dets = [d for d in all_dets if d.get("page_number") != page_num]
            if all_dets:
                refined.write_text(json.dumps(all_dets, indent=2))
            else:
                refined.unlink()
        except Exception as e:
            raise HTTPException(500, f"revert failed: {e}")


# ── create run ────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_run(
    name: Annotated[str, Form()],
    model: Annotated[str, Form()],
    provider: Annotated[str, Form()] = "custom",
    comic_format: Annotated[str, Form()] = "auto",
    source_language: Annotated[str, Form()] = "auto",
    translate: Annotated[bool, Form()] = False,
    target_language: Annotated[str, Form()] = "",
    global_context: Annotated[str, Form()] = "",
    ui_language: Annotated[str, Form()] = "English",
    detector_backend: Annotated[str, Form()] = "auto",
    detector_threshold: Annotated[float, Form()] = 0.4,
    # auto_start=True: detect+analyze immediately (backwards compat)
    # auto_start=False: create run in pending state, user controls phases
    auto_start: Annotated[bool, Form()] = True,
    files: list[UploadFile] = File(...),
):
    if not files: raise HTTPException(400, "no files uploaded")

    run = Run.create(
        name=name, model=model, comic_format=comic_format, provider=provider,
        source_language=source_language,
        translate=translate,
        target_language=target_language or None,
        global_context=global_context,
        ui_language=ui_language,
        detector_backend=detector_backend,
        detector_threshold=detector_threshold,
    )

    for f in sorted(files, key=lambda x: x.filename or ""):
        dest = run.pages_dir() / (f.filename or "page.jpg")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)

    run.update(total_pages=len(files))

    if auto_start:
        _launch_run_all(run.id)

    return run.meta()


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    run.delete()


# ── phase endpoints ───────────────────────────────────────────────────────────

@router.post("/{run_id}/detect", status_code=202)
async def start_detection(run_id: str):
    """Start detection phase only."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    meta = run.meta()
    if meta.get("detection_status") == "running":
        raise HTTPException(400, "detection already running")
    _launch_phase(run_id, phase="detect")
    return run.meta()


@router.post("/{run_id}/analyze", status_code=202)
async def start_analysis(run_id: str):
    """Start analysis phase only. Requires detection_status=done."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    meta = run.meta()
    if meta.get("analysis_status") == "running":
        raise HTTPException(400, "analysis already running")
    if meta.get("detection_status") != "done":
        raise HTTPException(400, "detection must complete before analysis")
    _launch_phase(run_id, phase="analyze")
    return run.meta()


@router.post("/{run_id}/run-all", status_code=202)
async def run_all(run_id: str):
    """Start detect + analyze in sequence."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    meta = run.meta()
    if meta.get("status") == "running":
        raise HTTPException(400, "run already in progress")
    _launch_run_all(run_id)
    return run.meta()


@router.post("/{run_id}/retry", status_code=202)
async def retry_run(run_id: str):
    """Re-run only pages that failed, using existing analyses as context."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    meta = run.meta()
    if meta["status"] == "running":
        raise HTTPException(400, "run is already in progress")
    _launch_phase(run_id, phase="retry")
    return run.meta()


# ── websocket ─────────────────────────────────────────────────────────────────

@router.websocket("/{run_id}/ws")
async def run_ws(websocket: WebSocket, run_id: str):
    await websocket.accept()
    # Small retry loop to handle race: POST returns 202, client connects WS
    # before the background task has registered its queue
    q = None
    for _ in range(10):  # up to 500ms
        q = _queues.get(run_id)
        if q: break
        await asyncio.sleep(0.05)

    if not q:
        run = Run.load(run_id)
        if run: await websocket.send_json({"type": "state", **run.meta()})
        await websocket.close(); return
    try:
        while True:
            ev = await q.get()
            if ev is None: break
            await websocket.send_json(ev)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


# ── launch helpers ────────────────────────────────────────────────────────────

def _launch_phase(run_id: str, phase: str) -> None:
    """Launch a background task for a single phase."""
    q: asyncio.Queue = asyncio.Queue()
    _queues[run_id] = q

    async def _task():
        loop = asyncio.get_running_loop()
        if phase == "detect":
            await loop.run_in_executor(None, _detect_sync, run_id, q, loop)
        elif phase == "analyze":
            await loop.run_in_executor(None, _analyze_sync, run_id, q, loop)
        elif phase == "retry":
            await loop.run_in_executor(None, _retry_sync, run_id, q, loop)
        await q.put(None)
        _queues.pop(run_id, None)

    asyncio.create_task(_task())


def _launch_run_all(run_id: str) -> None:
    """Launch detect + analyze in sequence."""
    q: asyncio.Queue = asyncio.Queue()
    _queues[run_id] = q

    async def _task():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _run_all_sync, run_id, q, loop)
        await q.put(None)
        _queues.pop(run_id, None)

    asyncio.create_task(_task())


# ── background workers ────────────────────────────────────────────────────────

def _make_emitter(run: Run, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """Create an emit function that sends events via WS queue."""
    def emit(ev: dict):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, ev)
        except Exception as _e:
            print(f"  emit error: {_e}", file=sys.stderr)
        # Update processed_pages on page completion events
        t = ev.get("type", "")
        if t in ("page_done",):
            current = run.meta().get("processed_pages", 0)
            run.update(processed_pages=current + 1)
        elif t == "detect_page_done":
            current = run.meta().get("detected_pages", 0)
            run.update(detected_pages=current + 1)
    return emit


def _detect_sync(run_id: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    from core.pipeline import run_detection

    run = Run.load(run_id)
    if not run: return

    emit = _make_emitter(run, queue, loop)
    run.update(status="running", detection_status="running")

    try:
        done = run_detection(
            pages_folder=run.pages_dir(),
            output_folder=run.output_dir(),
            detector_backend=run.meta().get("detector_backend", "auto"),
            detector_threshold=float(run.meta().get("detector_threshold", 0.4)),
            on_progress=emit,
        )
        if done == 0:
            run.update(detection_status="failed", error="all detection pages failed")
        else:
            run.update(detection_status="done", status="pending")  # analysis not started
    except Exception as e:
        msg = str(e)
        print(f"\n[detect {run_id}] error: {msg}", file=sys.stderr)
        run.update(detection_status="failed", error=msg)
        emit({"type": "error", "message": msg})


def _analyze_sync(run_id: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    from core.config import build_litellm_model
    from core.pipeline import run_analysis

    run = Run.load(run_id)
    if not run: return

    meta = run.meta()
    try:
        litellm_model, api_base = build_litellm_model(meta.get("provider", "custom"), meta.get("model", ""))
    except ValueError as e:
        msg = str(e)
        run.update(analysis_status="failed", error=msg)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": msg})
        return

    emit = _make_emitter(run, queue, loop)
    run.update(status="running", analysis_status="running")

    try:
        ctx = run_analysis(
            pages_folder=run.pages_dir(),
            output_folder=run.output_dir(),
            model=litellm_model,
            comic_format=meta["comic_format"],
            api_base=api_base,
            on_progress=emit,
            source_language=meta.get("source_language", "auto"),
            translate=meta.get("translate", False),
            target_language=meta.get("target_language"),
            ui_language=meta.get("ui_language", "English"),
            global_context=meta.get("global_context", ""),
            use_saved_detections=True,
        )
        processed = ctx.total_pages_processed
        if processed == 0:
            run.update(status="failed", analysis_status="failed",
                       error="all pages failed", finished_at=datetime.utcnow().isoformat())
        else:
            run.update(status="done", analysis_status="done",
                       processed_pages=processed, finished_at=datetime.utcnow().isoformat())
    except Exception as e:
        msg = str(e)
        print(f"\n[analyze {run_id}] error: {msg}", file=sys.stderr)
        run.update(status="failed", analysis_status="failed",
                   error=msg, finished_at=datetime.utcnow().isoformat())
        emit({"type": "error", "message": msg})


def _run_all_sync(run_id: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    """Detection + Analysis in sequence."""
    from core.config import build_litellm_model
    from core.pipeline import run_detection, run_analysis

    run = Run.load(run_id)
    if not run: return

    meta = run.meta()
    try:
        litellm_model, api_base = build_litellm_model(meta.get("provider", "custom"), meta.get("model", ""))
    except ValueError as e:
        msg = str(e)
        print(f"\n[run {run_id}] config error: {msg}", file=sys.stderr)
        run.update(status="failed", error=msg, finished_at=datetime.utcnow().isoformat())
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": msg})
        return

    emit = _make_emitter(run, queue, loop)
    run.update(status="running", detection_status="running")

    # ── Phase 1: Detection ────────────────────────────────────────────────────
    try:
        done = run_detection(
            pages_folder=run.pages_dir(),
            output_folder=run.output_dir(),
            detector_backend=meta.get("detector_backend", "auto"),
            detector_threshold=float(meta.get("detector_threshold", 0.4)),
            on_progress=emit,
        )
        if done == 0:
            run.update(status="failed", detection_status="failed",
                       error="all detection pages failed", finished_at=datetime.utcnow().isoformat())
            return
        run.update(detection_status="done", analysis_status="running")
    except Exception as e:
        msg = str(e)
        print(f"\n[detect {run_id}] error: {msg}", file=sys.stderr)
        run.update(status="failed", detection_status="failed",
                   error=msg, finished_at=datetime.utcnow().isoformat())
        emit({"type": "error", "message": msg})
        return

    # ── Phase 2: Analysis ─────────────────────────────────────────────────────
    try:
        ctx = run_analysis(
            pages_folder=run.pages_dir(),
            output_folder=run.output_dir(),
            model=litellm_model,
            comic_format=meta["comic_format"],
            api_base=api_base,
            on_progress=emit,
            source_language=meta.get("source_language", "auto"),
            translate=meta.get("translate", False),
            target_language=meta.get("target_language"),
            ui_language=meta.get("ui_language", "English"),
            global_context=meta.get("global_context", ""),
            use_saved_detections=True,
        )
        processed = ctx.total_pages_processed
        if processed == 0:
            run.update(status="failed", analysis_status="failed",
                       error="all pages failed — check model and provider settings",
                       finished_at=datetime.utcnow().isoformat())
        else:
            run.update(status="done", analysis_status="done",
                       processed_pages=processed, finished_at=datetime.utcnow().isoformat())
    except Exception as e:
        msg = str(e)
        print(f"\n[run {run_id}] pipeline error: {msg}", file=sys.stderr)
        run.update(status="failed", analysis_status="failed",
                   error=msg, finished_at=datetime.utcnow().isoformat())
        emit({"type": "error", "message": msg})


def _retry_sync(run_id: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    from core.config import build_litellm_model
    from core.retry import retry_failed_pages

    run = Run.load(run_id)
    if not run: return

    meta = run.meta()
    try:
        litellm_model, api_base = build_litellm_model(meta.get("provider", "custom"), meta.get("model", ""))
    except ValueError as e:
        run.update(status="failed", error=str(e))
        return

    run.update(status="running", analysis_status="running")
    emit = _make_emitter(run, queue, loop)

    try:
        newly_done = retry_failed_pages(
            pages_folder=run.pages_dir(),
            output_folder=run.output_dir(),
            model=litellm_model,
            comic_format=meta["comic_format"],
            api_base=api_base,
            on_progress=emit,
        )
        run.update(
            status="done" if newly_done else meta["status"],
            analysis_status="done" if newly_done else meta.get("analysis_status", "done"),
            processed_pages=meta.get("processed_pages", 0) + len(newly_done),
            finished_at=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        run.update(status="failed", analysis_status="failed",
                   error=str(e), finished_at=datetime.utcnow().isoformat())
        emit({"type": "error", "message": str(e)})




@router.put("/{run_id}/analyses/{page_num}/refined")
def save_analysis_page(run_id: str, page_num: int, body: dict):
    """Save refined analysis (translations, speaker, tone) for a single page."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")

    refined_f = run.analyses_file(refined=True)

    if refined_f.exists():
        try:
            all_analyses: list[dict] = json.loads(refined_f.read_text())
        except Exception:
            all_analyses = []
    else:
        # start from original
        orig = run.analyses_file(refined=False)
        all_analyses = json.loads(orig.read_text()) if orig.exists() else []

    # replace or append this page
    all_analyses = [a for a in all_analyses if a.get("page_number") != page_num]
    body["page_number"] = page_num
    all_analyses.append(body)
    all_analyses.sort(key=lambda a: a.get("page_number", 0))
    refined_f.write_text(json.dumps(all_analyses, indent=2, ensure_ascii=False))
    return {"ok": True, "page_number": page_num}


@router.delete("/{run_id}/analyses/{page_num}/refined", status_code=204)
def revert_analysis_page(run_id: str, page_num: int):
    """Remove refined analysis for a page (revert to original VLM output)."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    refined_f = run.analyses_file(refined=True)
    if refined_f.exists():
        try:
            all_analyses = json.loads(refined_f.read_text())
            all_analyses = [a for a in all_analyses if a.get("page_number") != page_num]
            if all_analyses:
                refined_f.write_text(json.dumps(all_analyses, indent=2, ensure_ascii=False))
            else:
                refined_f.unlink()
        except Exception as e:
            raise HTTPException(500, f"revert failed: {e}")

# ── annotations / edits (unchanged) ──────────────────────────────────────────

@router.get("/{run_id}/annotations")
def get_annotations(run_id: str):
    from core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    store = AnnotationStore(run.output_dir())
    return {"annotations": store.get_annotations(), "summary": store.summary()}


@router.post("/{run_id}/annotations/{page_number}")
def add_annotation(run_id: str, page_number: int, body: dict):
    from core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    store = AnnotationStore(run.output_dir())
    return store.add_annotation(
        page_number=page_number,
        field=body.get("field", ""),
        note=body.get("note", ""),
        original_value=body.get("original_value", ""),
    )


@router.delete("/{run_id}/annotations/{page_number}/{annotation_id}", status_code=204)
def delete_annotation(run_id: str, page_number: int, annotation_id: str):
    from core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    AnnotationStore(run.output_dir()).delete_annotation(page_number, annotation_id)


@router.get("/{run_id}/edits")
def get_edits(run_id: str):
    from core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    return AnnotationStore(run.output_dir()).get_edits()


@router.put("/{run_id}/edits/{page_number}")
def save_edit(run_id: str, page_number: int, body: dict):
    from core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    AnnotationStore(run.output_dir()).save_edit(page_number, body)
    return {"ok": True}


@router.delete("/{run_id}/edits/{page_number}", status_code=204)
def revert_edit(run_id: str, page_number: int):
    from core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    AnnotationStore(run.output_dir()).revert_edit(page_number)