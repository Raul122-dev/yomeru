from __future__ import annotations
import json
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from yomeru.core.config import config, DATA_DIR
from yomeru.core.runs import Run
from yomeru.phases.runner import run_all
from yomeru.api.ws import make_emitter

router = APIRouter(prefix="/runs", tags=["runs"])


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


@router.get("/{run_id}/context")
def get_context(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    if not run.context_file().exists(): raise HTTPException(404, "context not ready")
    return json.loads(run.context_file().read_text())


# ── create run ────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_run(
    name: Annotated[str, Form()],
    model: Annotated[str, Form()],
    provider: Annotated[str, Form()] = "custom",
    comic_format: Annotated[str, Form()] = "auto",
    source_language: Annotated[str, Form()] = "auto",
    target_language: Annotated[str, Form()] = "Spanish",
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
        target_language=target_language,
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
        import threading
        from yomeru.api.routes.phases import _build_all_options

        options = _build_all_options(run, {})

        def worker():
            emit = make_emitter(run.id)
            run_all(run, options=options, on_progress=emit)

        threading.Thread(target=worker, daemon=True).start()

    return run.meta()


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    run.delete()


# ── annotations / edits ──────────────────────────────────────────────────────

@router.get("/{run_id}/annotations")
def get_annotations(run_id: str):
    from yomeru.core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    store = AnnotationStore(run.output_dir())
    return {"annotations": store.get_annotations(), "summary": store.summary()}


@router.post("/{run_id}/annotations/{page_number}")
def add_annotation(run_id: str, page_number: int, body: dict):
    from yomeru.core.annotations import AnnotationStore
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
    from yomeru.core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    AnnotationStore(run.output_dir()).delete_annotation(page_number, annotation_id)


@router.get("/{run_id}/edits")
def get_edits(run_id: str):
    from yomeru.core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    return AnnotationStore(run.output_dir()).get_edits()


@router.put("/{run_id}/edits/{page_number}")
def save_edit(run_id: str, page_number: int, body: dict):
    from yomeru.core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    AnnotationStore(run.output_dir()).save_edit(page_number, body)
    return {"ok": True}


@router.delete("/{run_id}/edits/{page_number}", status_code=204)
def revert_edit(run_id: str, page_number: int):
    from yomeru.core.annotations import AnnotationStore
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    AnnotationStore(run.output_dir()).revert_edit(page_number)