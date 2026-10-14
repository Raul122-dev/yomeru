"""
Stage 3a: OCR — read text from detected regions.

Uses two engines depending on source language:
  - manga_ocr : Japanese manga text (more accurate for vertical JP text)
  - easyocr   : All other languages (80+ supported)
"""
from __future__ import annotations
import sys
from functools import lru_cache
from PIL import Image


@lru_cache(maxsize=4)
def _get_easyocr(lang_code: tuple):
    """Lazy-load EasyOCR reader (cached per language set)."""
    import easyocr
    print(f"  [ocr] loading EasyOCR for {lang_code}…", file=sys.stderr)
    from yomeru.core.paths import MODELS_DIR
    store = MODELS_DIR / "easyocr"
    store.mkdir(parents=True, exist_ok=True)
    return easyocr.Reader(
        list(lang_code), gpu=_has_gpu(),
        model_storage_directory=str(store), user_network_directory=str(store / "user_network"),
    )


def ocr_easyocr(image: Image.Image, lang_codes: tuple = ("en",)) -> str:
    """Run EasyOCR on an image crop."""
    try:
        reader = _get_easyocr(lang_codes)
        import numpy as np
        results = reader.readtext(np.array(image), detail=0, paragraph=True)
        return " ".join(str(r) for r in results).strip()
    except Exception as e:
        print(f"  [ocr] easyocr error: {e}", file=sys.stderr)
        return ""


_manga_ocr_instance = None

def _get_manga_ocr():
    global _manga_ocr_instance
    if _manga_ocr_instance is None:
        try:
            from manga_ocr import MangaOcr
            print("  [ocr] loading MangaOCR…", file=sys.stderr)
            _manga_ocr_instance = MangaOcr()
        except ImportError:
            print("  [ocr] manga-ocr not installed, falling back to easyocr", file=sys.stderr)
    return _manga_ocr_instance


def ocr_manga(image: Image.Image) -> str:
    """Run MangaOCR on an image crop (Japanese manga specialized)."""
    try:
        ocr = _get_manga_ocr()
        if ocr is None:
            return ocr_easyocr(image, ("ja",))
        return ocr(image) or ""
    except Exception as e:
        print(f"  [ocr] manga-ocr error: {e}", file=sys.stderr)
        return ""




def ocr_region(
    image: Image.Image,
    crop: tuple[int, int, int, int],
    source_language: str = "auto",
) -> str:
    """OCR a specific region of the page image."""
    x1, y1, x2, y2 = crop
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)
    if x2 <= x1 or y2 <= y1:
        return ""

    # ensure minimum region size for OCR
    if (x2 - x1) < 10 or (y2 - y1) < 8:
        return ""

    pad = 6
    crop_img = image.crop((
        max(0, x1 - pad), max(0, y1 - pad),
        min(image.width, x2 + pad), min(image.height, y2 + pad),
    ))

    from yomeru.core.languages import profile
    p = profile(source_language)
    if p.ocr_engine == "manga_ocr":
        return ocr_manga(crop_img)
    return ocr_easyocr(crop_img, p.ocr_codes)


def _has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def ocr_lines(image: Image.Image, lang_codes: tuple = ("en",)) -> list[tuple[tuple[int, int, int, int], str]]:
    """Page-wide OCR with boxes: [(x1, y1, x2, y2), text]. Stacked lines of one
    label ("SFX:" over "Skid") are also returned merged, so a dialogue split
    over two lines can be found as a whole."""
    import numpy as np
    try:
        raw = _get_easyocr(lang_codes).readtext(np.array(image), detail=1, paragraph=False)
    except Exception as e:  # pragma: no cover - OCR missing/broken
        print(f"  [ocr] easyocr error: {e}", file=sys.stderr)
        return []
    boxes = []
    for quad, text, _conf in raw:
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        boxes.append(((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), str(text)))
    merged = []
    for (a, ta) in boxes:
        for (b, tb) in boxes:
            h = max(1, a[3] - a[1])
            stacked = 0 <= b[1] - a[3] <= 0.6 * h and min(a[2], b[2]) - max(a[0], b[0]) > 0
            if stacked:
                merged.append(((min(a[0], b[0]), a[1], max(a[2], b[2]), b[3]), f"{ta} {tb}"))
    return boxes + merged
