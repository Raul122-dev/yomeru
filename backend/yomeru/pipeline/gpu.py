"""One GPU-bound job at a time across all runs.

Detection, OCR, LaMa and the render engine are serialised so two runs (or a
run plus a preview request) never load models / allocate VRAM concurrently.
Re-entrant so a phase holding it can call helpers that also take it.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_lock = threading.RLock()


@contextmanager
def gpu_lock():
    with _lock:
        yield
