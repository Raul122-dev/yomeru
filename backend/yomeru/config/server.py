"""Process-level settings (env vars) and re-exports of data paths.

Pipeline/user settings live in config/settings.py.
"""
from __future__ import annotations

import os

from yomeru.config.paths import (  # noqa: F401  (re-exported)
    CONFIG_FILE, DATA_DIR, MODELS_DIR, RUNS_DIR, STATIC_DIR, ensure_dirs,
)

PORT = int(os.environ.get("PORT", 7788))
HOST = os.environ.get("HOST", "127.0.0.1")
