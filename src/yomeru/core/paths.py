"""Filesystem layout.

Everything yomeru writes (runs, config, downloaded model weights) lives under
one data directory:

- ``YOMERU_DATA`` if set
- ``<repo>/data`` when running from a source checkout (default for dev)
- ``~/.yomeru`` when installed as a package (no checkout around)
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent


def _find_repo_root() -> Path | None:
    for parent in PACKAGE_DIR.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "yomeru").is_dir():
            return parent
    return None


REPO_ROOT = _find_repo_root()


def _resolve_data_dir() -> Path:
    env = os.environ.get("YOMERU_DATA")
    if env:
        return Path(env).expanduser().resolve()
    if REPO_ROOT is not None:
        return REPO_ROOT / "data"
    return Path.home() / ".yomeru"


DATA_DIR = _resolve_data_dir()
RUNS_DIR = DATA_DIR / "runs"
CONFIG_FILE = DATA_DIR / "config.json"
MODELS_DIR = DATA_DIR / "models"
STATIC_DIR = PACKAGE_DIR / "static"
FONTS_DIR = PACKAGE_DIR / "assets" / "fonts"

# Third-party model caches (HuggingFace, torch hub, EasyOCR) go into MODELS_DIR
# instead of scattering across ~/.cache. Explicit env vars from the user win.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(MODELS_DIR / "torch"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, RUNS_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
