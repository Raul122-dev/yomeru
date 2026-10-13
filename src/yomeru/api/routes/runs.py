from __future__ import annotations
import json
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from yomeru.core.images import serve_image

import re

from yomeru.core.settings import resolve_settings
from yomeru.core.paths import IMAGE_EXTS, list_page_files, safe_child
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


@router.get("/{run_id}/pages-cover")
def get_cover(run_id: str, request: Request, w: int = 320):
    """First page, for the runs library."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    files = list_page_files(run.pages_dir())
    if not files: raise HTTPException(404, "no pages")
    return serve_image(request, files[0], w)


@router.get("/{run_id}/pages/{filename}")
def get_page_image(run_id: str, filename: str, request: Request, w: int | None = None):
    """Source page. ?w= returns a resized WebP (see core/images.py)."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    try:
        path = safe_child(run.pages_dir(), filename)
    except ValueError:
        raise HTTPException(400, "invalid filename")
    if not path.is_file(): raise HTTPException(404, "image not found")
    return serve_image(request, path, w)


@router.get("/{run_id}/pages")
def list_pages(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    files = list_page_files(run.pages_dir())
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
    global_context: Annotated[str, Form()] = "",
    preset_id: Annotated[str | None, Form()] = None,
    # JSON object, partial PipelineSettings applied on top of global → preset
    settings: Annotated[str, Form()] = "{}",
    # auto_start=True: run all phases; False: user triggers each phase
    auto_start: Annotated[bool, Form()] = True,
    files: list[UploadFile] = File(...),
):
    if not files: raise HTTPException(400, "no files uploaded")
    try:
        overrides = json.loads(settings or "{}")
        effective = resolve_settings(preset_id or None, overrides)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, f"invalid settings: {e}")
    # API (vlm) is the default and needs a configured provider + model; the
    # local technique is an explicit, experimental opt-in that needs neither.
    if effective.analysis.backend != "local" and not effective.analysis_model.is_set():
        raise HTTPException(400, "no model provider configured — add a connection and pick a vision model "
                                 "in Settings, or choose the experimental local mode")
    sep = effective.analysis.separate_translation
    if sep.enabled and not (sep.local or effective.translation_model.is_set()):
        raise HTTPException(400, "separate translation is on but has no model — pick a translation model "
                                 "(API or local) in Settings, or turn separate translation off")

    run = Run.create(name=name, settings=effective, global_context=global_context,
                     preset_id=preset_id or None)

    # Keep the order the UI sent (the user's drag-sorted order) and never trust
    # the client filename as a path: store as NNN_<basename>.
    saved = 0
    for f in files:
        base = Path(f.filename or "page.jpg").name
        stem, ext = Path(base).stem, Path(base).suffix.lower()
        if ext not in IMAGE_EXTS:
            continue
        stem = re.sub(r"[^\w.-]+", "_", stem).strip("._") or "page"
        stem = re.sub(r"^\d{3}_", "", stem) or "page"  # re-uploaded pages already carry NNN_
        saved += 1
        dest = safe_child(run.pages_dir(), f"{saved:03d}_{stem[:80]}{ext}")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
    if not saved:
        run.delete()
        raise HTTPException(400, "no supported images (jpg, jpeg, png, webp)")

    run.update(total_pages=saved)

    if auto_start:
        from yomeru.api.routes.phases import _build_all_options
        from yomeru.phases.runner import start_job
        options = _build_all_options(run, {})
        start_job(run, "all", lambda emit, _c: run_all(run, options=options, on_progress=emit),
                  on_progress=make_emitter(run.id))

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