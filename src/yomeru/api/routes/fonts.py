"""
Fonts routes — Custom font management for rendering.

Manages fonts stored in assets/fonts/ that are used by the PIL renderer.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile

router = APIRouter(prefix="/fonts", tags=["fonts"])

FONTS_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"
SUPPORTED_FORMATS = {".ttf", ".otf", ".ttc"}


def _ensure_fonts_dir():
    FONTS_DIR.mkdir(parents=True, exist_ok=True)


def _clear_font_cache():
    """Clear the renderer font cache so new fonts are picked up."""
    try:
        from yomeru.core.typesetting.stages.rendering.pil import _font_cache
        _font_cache.clear()
    except Exception:
        pass


@router.get("")
def list_fonts():
    """List all custom fonts installed."""
    _ensure_fonts_dir()
    fonts = [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in sorted(FONTS_DIR.iterdir())
        if f.suffix.lower() in SUPPORTED_FORMATS
    ]
    return {"fonts": fonts}


@router.post("/upload")
async def upload_font(file: UploadFile = FastAPIFile(...)):
    """Upload a font file."""
    if not file.filename:
        raise HTTPException(400, "no filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"unsupported font format '{suffix}' — use .ttf, .otf or .ttc")

    _ensure_fonts_dir()
    dest = FONTS_DIR / Path(file.filename).name
    content = await file.read()
    dest.write_bytes(content)
    _clear_font_cache()
    return {"name": dest.name, "size_kb": round(len(content) / 1024, 1)}


@router.delete("/{filename}")
def delete_font(filename: str):
    """Delete a font."""
    _ensure_fonts_dir()
    dest = FONTS_DIR / filename
    if not dest.exists() or dest.parent != FONTS_DIR:
        raise HTTPException(404, "font not found")
    dest.unlink()
    _clear_font_cache()
    return {"deleted": filename}
