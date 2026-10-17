"""Model weights downloaded on first use into ``MODELS_DIR``.

HuggingFace models (ogkalu detector, manga-ocr) download through the HF cache,
which ``paths`` points at ``MODELS_DIR/huggingface``. Plain checkpoint files
are declared here.
"""
from __future__ import annotations

import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from yomeru.core.paths import MODELS_DIR


@dataclass(frozen=True)
class Weight:
    key: str
    url: str
    relpath: str

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.relpath


WEIGHTS: dict[str, Weight] = {
    "lama": Weight(
        "lama",
        "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt",
        "lama/big-lama.pt",
    ),
}

_locks: dict[str, threading.Lock] = {k: threading.Lock() for k in WEIGHTS}


def ensure_weight(key: str) -> Path:
    """Return the local path of a weight, downloading it the first time."""
    w = WEIGHTS[key]
    with _locks[key]:
        if w.path.is_file():
            return w.path
        w.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = w.path.with_suffix(w.path.suffix + ".part")
        print(f"  [weights] downloading {key} → {w.path}", file=sys.stderr)
        try:
            with urllib.request.urlopen(w.url, timeout=60) as resp, open(tmp, "wb") as out:
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
            tmp.replace(w.path)
        finally:
            tmp.unlink(missing_ok=True)
        print(f"  [weights] {key} ready", file=sys.stderr)
        return w.path
