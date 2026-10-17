"""
Fonts routes — the lettering fonts the renderer can use.

Shipped fonts live in the package (assets/fonts, read-only); fonts the user
adds go to <data>/fonts and can be removed again. Which font draws each
lettering style is chosen in the pipeline settings (rendering.fonts).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File as FastAPIFile, HTTPException, UploadFile

from yomeru.config.languages import FONT_STYLES, SCRIPT_FONTS
from yomeru.config.paths import FONTS_DIR, USER_FONTS_DIR

router = APIRouter(prefix="/fonts", tags=["fonts"])

SUPPORTED_FORMATS = {".ttf", ".otf", ".ttc"}


def _clear_font_cache():
    from yomeru.stages.rendering.pil import _font_cache
    _font_cache.clear()


def _fonts(folder: Path, source: str) -> list[dict]:
    if not folder.is_dir():
        return []
    return [{"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "source": source}
            for f in sorted(folder.iterdir()) if f.suffix.lower() in SUPPORTED_FORMATS]


@router.get("")
def list_fonts():
    """Every usable font (the user's and the shipped ones), the lettering
    styles and the default font of each style per script."""
    return {"fonts": _fonts(USER_FONTS_DIR, "user") + _fonts(FONTS_DIR, "shipped"),
            "styles": list(FONT_STYLES), "defaults": SCRIPT_FONTS}


@router.post("/upload")
async def upload_font(file: UploadFile = FastAPIFile(...)):
    if not file.filename:
        raise HTTPException(400, "no filename")
    name = Path(file.filename).name
    if Path(name).suffix.lower() not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"unsupported font format '{Path(name).suffix}' — use .ttf, .otf or .ttc")
    if (FONTS_DIR / name).exists():
        raise HTTPException(409, f"'{name}' is a shipped font — rename your file")
    content = await file.read()
    from PIL import ImageFont
    import io
    try:
        ImageFont.truetype(io.BytesIO(content), 20)
    except OSError:
        raise HTTPException(400, f"'{name}' is not a readable font") from None
    USER_FONTS_DIR.mkdir(parents=True, exist_ok=True)
    (USER_FONTS_DIR / name).write_bytes(content)
    _clear_font_cache()
    return {"name": name, "size_kb": round(len(content) / 1024, 1), "source": "user"}


@router.delete("/{filename}")
def delete_font(filename: str):
    """Remove a font the user added (shipped fonts cannot be removed)."""
    dest = USER_FONTS_DIR / Path(filename).name
    if not dest.is_file():
        raise HTTPException(404, "font not found among your fonts")
    dest.unlink()
    _clear_font_cache()
    return {"deleted": dest.name}
