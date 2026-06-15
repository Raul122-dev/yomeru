"""
Outputs routes — Read-only access to run output files.

Provides access to:
  - Debug images (masks, inpainted pages, detection overlays)
  - Render logs (per-page JSON with matching + rendering details)
  - Final typeset pages
  - Typeset status
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from yomeru.core.runs import Run

router = APIRouter(prefix="/runs", tags=["outputs"])

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _get_run(run_id: str) -> Run:
    run = Run.load(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


# ── Typeset status ─────────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/status")
def typeset_status(run_id: str):
    """Return typeset output status — which pages have been rendered."""
    run = _get_run(run_id)
    typeset_dir = run.output_dir() / "typeset"
    if not typeset_dir.exists():
        return {"status": "not_started", "pages": []}
    pages = sorted(
        p.name for p in typeset_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTS and p.is_file()
    )
    return {"status": "done" if pages else "not_started", "pages": pages}


# ── Debug images ───────────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/debug")
def list_debug_images(run_id: str):
    """List all debug image files for a run."""
    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"
    if not debug_dir.exists():
        return {"images": []}
    images = sorted(
        p.name for p in debug_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTS
    )
    return {"images": images}


@router.get("/{run_id}/typeset/debug/{filename}")
def get_debug_image(run_id: str, filename: str):
    """Serve a debug image file."""
    run = _get_run(run_id)
    path = run.output_dir() / "typeset" / "debug" / filename
    if not path.exists():
        raise HTTPException(404, "debug image not found")
    return FileResponse(path)


# ── Render logs ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/render-log/{page_num}")
def get_render_log(run_id: str, page_num: int):
    """Return the render log for a specific page (matching + rendering details)."""
    from fastapi.responses import JSONResponse
    run = _get_run(run_id)
    log_path = run.output_dir() / "typeset" / "debug" / f"p{page_num:02d}_render_log.json"
    if not log_path.exists():
        return JSONResponse(
            {"page_number": page_num, "renders": [], "matched": 0, "unmatched": 0},
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
    data = json.loads(log_path.read_text())
    return JSONResponse(data, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


# ── Final typeset pages ────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/pages/{filename}")
def get_typeset_page(run_id: str, filename: str):
    """Serve a final typeset page image."""
    run = _get_run(run_id)
    path = run.output_dir() / "typeset" / filename
    if not path.exists():
        raise HTTPException(404, "typeset image not found")
    return FileResponse(path)
