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
    return easyocr.Reader(list(lang_code), gpu=_has_gpu())


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


_LANG_MAP: dict[str, tuple] = {
    "Japanese":               ("ja",),
    "Korean":                 ("ko",),
    "Chinese (Simplified)":   ("ch_sim",),
    "Chinese (Traditional)":  ("ch_tra",),
    "English":                ("en",),
    "Spanish":                ("es", "en"),
    "Portuguese":             ("pt", "en"),
    "French":                 ("fr", "en"),
    "German":                 ("de", "en"),
    "Italian":                ("it", "en"),
    # auto: try the most common comic languages
    "auto":                   ("en", "es", "pt"),
}


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

    if source_language == "Japanese":
        return ocr_manga(crop_img)

    # for source text that's in a non-ASCII script (Korean, Chinese),
    # use the appropriate OCR engine even if the VLM text extracted is translated
    lang_codes = _LANG_MAP.get(source_language, _LANG_MAP["auto"])
    return ocr_easyocr(crop_img, lang_codes)


def _has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False