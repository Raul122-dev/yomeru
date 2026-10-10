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

from yomeru.core.paths import safe_child

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


# ── Export ─────────────────────────────────────────────────────────────────────

@router.get("/{run_id}/export")
def export_run(run_id: str, format: str = "cbz"):
    """Download the typeset pages in reading order as .cbz (comic archive) or .zip."""
    import io
    import re
    import zipfile
    from fastapi.responses import StreamingResponse
    from yomeru.core.paths import list_page_files

    if format not in ("cbz", "zip"):
        raise HTTPException(400, "format must be cbz or zip")
    run = _get_run(run_id)
    typeset_dir = run.output_dir() / "typeset"
    pages = [typeset_dir / p.name for p in list_page_files(run.pages_dir())]
    pages = [p for p in pages if p.is_file()]
    if not pages:
        raise HTTPException(404, "no rendered pages yet — run rendering first")

    buf = io.BytesIO()
    # Images are already compressed: store them, the archive is just a container
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i, p in enumerate(pages, 1):
            stem = re.sub(r"^\d{3}_", "", p.stem)
            zf.write(p, f"{i:03d}_{stem}{p.suffix.lower()}")
    buf.seek(0)
    name = re.sub(r"[^\w.-]+", "_", run.meta().get("name") or run_id).strip("_") or run_id
    return StreamingResponse(
        buf,
        media_type="application/vnd.comicbook+zip" if format == "cbz" else "application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'},
    )


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
    try:
        path = safe_child(run.output_dir() / "typeset" / "debug", filename)
    except ValueError:
        raise HTTPException(400, "invalid filename")
    if not path.is_file():
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
    try:
        path = safe_child(run.output_dir() / "typeset", filename)
    except ValueError:
        raise HTTPException(400, "invalid filename")
    if not path.is_file():
        raise HTTPException(404, "typeset image not found")
    return FileResponse(path)
