"""
Optimized image delivery.

Pages and outputs are stored at full resolution (the pipeline needs exact
pixels), but the UI almost never shows them that big. Every image endpoint
goes through `serve_image`, which can return a resized WebP variant:

    ?w=<px>   → width snapped to WIDTHS, WebP, cached on disk
    (no w)    → the original file

Variants live in <run>/cache/img/ and are keyed by the source file's mtime and
size, so a re-render or re-inpaint produces new variants automatically and
stale ones are never served. Responses carry an ETag, so the browser
revalidates with a cheap 304 instead of downloading again — this replaces the
old "no-store" on render outputs.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response

# Allowed widths: bounds the cache and makes variants shareable across views.
# 32 = blur placeholder (≈1 KB), 160–320 = strips/grids, 640–1024 = side-by-side
# panels, 1600–2400 = lightbox / editors on big screens.
WIDTHS = (32, 160, 320, 640, 1024, 1600, 2400)


_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def snap_width(w: int) -> int:
    for allowed in WIDTHS:
        if w <= allowed:
            return allowed
    return WIDTHS[-1]


def _cache_dir(src: Path) -> Path:
    # <run>/pages/x.jpg, <run>/output/typeset/debug/x.jpg … → <run>/cache/img
    for parent in src.parents:
        if (parent / "meta.json").exists():
            return parent / "cache" / "img"
    return src.parent / ".cache"


def variant(src: Path, w: int) -> Path:
    """Path of a cached WebP of `src` at width `w` (never upscaled)."""
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_mtime_ns}|{st.st_size}|{w}".encode()).hexdigest()[:16]
    out = _cache_dir(src) / f"{src.stem}.{w}.{key}.webp"
    if out.exists():
        return out
    with _guard:   # one encoder per variant; concurrent requests wait and reuse it
        lock = _locks.setdefault(str(out), threading.Lock())
    with lock:
        if out.exists():
            return out
        return _encode(src, out, w)


def _encode(src: Path, out: Path, w: int) -> Path:
    from PIL import Image
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        if im.width > w:
            im = im.resize((w, max(1, round(im.height * w / im.width))), Image.Resampling.LANCZOS)
        tmp = out.with_suffix(f".{os.getpid()}-{threading.get_ident()}.tmp")
        im.save(tmp, "WEBP", quality=50 if w <= 32 else 82, method=4)
        tmp.replace(out)  # atomic: concurrent requests never read a half file
    # Drop older variants of the same source+width (source changed)
    for old in out.parent.glob(f"{src.stem}.{w}.*.webp"):
        if old != out:
            old.unlink(missing_ok=True)
    return out


def serve_image(request: Request, src: Path, w: int | None = None) -> Response:
    """FileResponse for `src` or its resized variant, with ETag/304 support."""
    path = variant(src, snap_width(w)) if w else src
    st = path.stat()
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}  # always revalidate, usually 304
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, headers=headers)


def overlay_font(size: int, bold: bool = True):
    """Font for the labels of debug overlays: a shipped font, so they look the
    same on every host (never a distro font path)."""
    from PIL import ImageFont
    from yomeru.core.paths import FONTS_DIR
    name = "ComicNeue-Bold.ttf" if bold else "ComicNeue-Regular.ttf"
    try:
        return ImageFont.truetype(str(FONTS_DIR / name), size)
    except OSError:
        return ImageFont.load_default(size)
