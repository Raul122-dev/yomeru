"""
Outputs routes — Read-only access to run output files.

Provides access to:
  - Debug images (masks, inpainted pages, detection overlays)
  - Render logs (per-page JSON with matching + rendering details)
  - Final typeset pages
  - Typeset status
"""
from __future__ import annotations


from fastapi import APIRouter, HTTPException, Request

from yomeru.core.images import serve_image

from yomeru.core import artifacts
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
    typeset_dir = artifacts.typeset_dir(run)
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
    typeset_dir = artifacts.typeset_dir(run)
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
        if format == "cbz":   # library metadata read by comic readers/servers
            zf.writestr("ComicInfo.xml", comic_info(run, len(pages)))
    buf.seek(0)
    name = re.sub(r"[^\w.-]+", "_", run.meta().get("name") or run_id).strip("_") or run_id
    return StreamingResponse(
        buf,
        media_type="application/vnd.comicbook+zip" if format == "cbz" else "application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'},
    )


# ── Review flags ───────────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/review")
def typeset_review(run_id: str):
    """What deserves a human look, per page: text drawn past its box at the
    minimum size (overflow), regions the detector missed and OCR found
    (located), repeated sounds split from one reading entry (split_sfx)."""
    run = _get_run(run_id)
    origins = artifacts.load_region_origins(run)
    out: dict[int, list[dict]] = {}
    from yomeru.core.paths import list_page_files
    for page in range(1, len(list_page_files(run.pages_dir())) + 1):
        items = []
        log = artifacts.load_render_log(run, page) or {}
        drawn = {e.get("region_id"): e for e in (log.get("s5_rendering") or {}).get("renders", [])}
        for e in drawn.values():
            if e.get("overflow"):
                items.append({"region_id": e.get("region_id"), "kind": "overflow", "text": e.get("text", "")})
        for rid, kind in origins.get(page, {}).items():
            items.append({"region_id": rid, "kind": kind, "text": (drawn.get(rid) or {}).get("text", "")})
        if items:
            out[page] = items
    return out


# ── Debug images ───────────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/debug")
def list_debug_images(run_id: str):
    """List all debug image files for a run."""
    run = _get_run(run_id)
    debug_dir = artifacts.debug_dir(run)
    if not debug_dir.exists():
        return {"images": []}
    images = sorted(
        p.name for p in debug_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTS
    )
    return {"images": images}


@router.get("/{run_id}/typeset/debug/{filename}")
def get_debug_image(run_id: str, filename: str, request: Request, w: int | None = None):
    """Serve a debug image file (?w= for a resized WebP)."""
    run = _get_run(run_id)
    try:
        path = safe_child(artifacts.debug_dir(run), filename)
    except ValueError:
        raise HTTPException(400, "invalid filename")
    if not path.is_file() and path.suffix == ".png":
        legacy = path.with_suffix(".jpg")  # runs made before intermediates went PNG
        if legacy.is_file():
            path = legacy
    if not path.is_file():
        raise HTTPException(404, "debug image not found")
    return serve_image(request, path, w)


# ── Render logs ────────────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/render-log/{page_num}")
def get_render_log(run_id: str, page_num: int):
    """Return the render log for a specific page (matching + rendering details)."""
    from fastapi.responses import JSONResponse
    run = _get_run(run_id)
    data = artifacts.load_render_log(run, page_num)
    if data is None:
        return JSONResponse(
            {"page_number": page_num, "renders": [], "matched": 0, "unmatched": 0},
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
    return JSONResponse(data, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


# ── Final typeset pages ────────────────────────────────────────────────────────

@router.get("/{run_id}/typeset/pages/{filename}")
def get_typeset_page(run_id: str, filename: str, request: Request, w: int | None = None):
    """Serve a final typeset page image (?w= for a resized WebP)."""
    run = _get_run(run_id)
    try:
        path = safe_child(artifacts.typeset_dir(run), filename)
    except ValueError:
        raise HTTPException(400, "invalid filename")
    if not path.is_file():
        raise HTTPException(404, "typeset image not found")
    return serve_image(request, path, w)


def comic_info(run, page_count: int) -> str:
    """ComicInfo.xml (Anansi Project schema 2.0) for the exported .cbz:
    series/number, language, reading direction, page list, summary and
    characters from the reading, credits."""
    from xml.sax.saxutils import escape
    from yomeru.core.languages import profile
    from yomeru.core.settings import run_settings
    meta = run.meta()
    st = run_settings(meta)
    names = meta.get("character_names") or {}
    analyses = artifacts.load_analyses(run)
    summary = " ".join(a.get("page_summary", "") for a in analyses if a.get("page_summary")).strip()
    chars: list[str] = []
    for a in analyses:
        for c in a.get("characters_seen", []):
            n = names.get(c.get("id", "")) or c.get("id", "")
            if n and n not in chars and n != "unknown":
                chars.append(n)
    iso = profile(st.language.target).iso
    manga = "YesAndRightToLeft" if st.language.comic_format == "manga" else "No"
    model = meta.get("model") or ""
    fields = [
        ("Title", meta.get("name") or ""),
        ("Series", meta.get("series") or meta.get("name") or ""),
        ("Number", meta.get("chapter") or ""),
        ("Summary", summary),
        ("Notes", f"Translated with yomeru{f' ({model})' if model else ''}; "
                  f"{st.language.source} → {st.language.target}."),
        ("Translator", "yomeru"),
        ("LanguageISO", iso),
        ("Manga", manga),
        ("Characters", ", ".join(chars)),
        ("PageCount", str(page_count)),
    ]
    body = "\n".join(f"  <{k}>{escape(v)}</{k}>" for k, v in fields if v)
    pages = "\n".join(f'    <Page Image="{i}"{" Type=\"FrontCover\"" if i == 0 else ""} />'
                      for i in range(page_count))
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<ComicInfo xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            f"{body}\n  <Pages>\n{pages}\n  </Pages>\n</ComicInfo>\n")
