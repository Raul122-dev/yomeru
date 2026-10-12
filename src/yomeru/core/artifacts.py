"""
Run artifacts — the single owner of the run's file layout.

Every phase, the render engine and the API read and write a run's files
through here instead of building `output/typeset/debug/pNN_*` paths by hand.
It also resolves the user's edits once, so phases (and future backends) see
"effective" inputs:

    active detections  = page_detections_refined.json if present, else original
    effective analyses = active analyses file + edits.json (per page)
    effective matches  = s3 matches + pNN_matches_refined.json (manual wins)

Layout (unchanged — old runs keep working):

    <run>/pages/NNN_<name>.<ext>
    <run>/output/page_detections[_refined].json
    <run>/output/page_analyses[_refined].json, edits.json, context.json
    <run>/output/typeset/<page name>                      final page
    <run>/output/typeset/debug/pNN_<artifact>             per-page artifacts
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yomeru.core.runs import Run


# Per-page artifact names in typeset/debug/ (pNN_<name>)
RENDER_LOG = "render_log.json"
MATCHES_REFINED = "matches_refined.json"
MASK_REFINED = "mask_refined.png"
MASK_CURRENT = "mask_current.png"
RENDER_OVERRIDES = "render_overrides.json"
S3_MATCHING = "s3_matching.jpg"
S4_INPAINTED = "s4_inpainted.jpg"
S4_MASK_DEBUG = "s4_mask_debug.jpg"
SCANLINE_PREVIEW = "scanline_preview.jpg"
SCANLINE_PRODUCTION = "scanline_production.jpg"
ALGO_ONLY = "algo_only.jpg"

_log_locks: dict[str, threading.Lock] = {}
_log_locks_guard = threading.Lock()


def _log_lock(path: Path) -> threading.Lock:
    with _log_locks_guard:
        return _log_locks.setdefault(str(path), threading.Lock())


def page_files(run: "Run") -> list[tuple[int, Path]]:
    """Source pages as (1-based page number, path), in reading order."""
    from yomeru.core.paths import list_page_files
    return list(enumerate(list_page_files(run.pages_dir()), 1))


def typeset_dir(run: "Run", create: bool = False) -> Path:
    d = run.output_dir() / "typeset"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def debug_dir(run: "Run", create: bool = False) -> Path:
    d = run.output_dir() / "typeset" / "debug"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def page_artifact(run: "Run", page: int, name: str) -> Path:
    """Path of a per-page artifact: typeset/debug/pNN_<name>."""
    return debug_dir(run) / f"p{page:02d}_{name}"


# ── Effective inputs (user edits resolved) ────────────────────────────────────

def load_detections(run: "Run") -> dict[int, dict[int, dict]]:
    """Active detections as {page: {region_id: region}}."""
    f = run.active_detections_file()
    if not f.exists():
        return {}
    return {e["page_number"]: {r["id"]: r for r in e["regions"]} for e in json.loads(f.read_text())}


def load_analyses(run: "Run") -> list[dict]:
    """Active analyses merged with the user's edits.json."""
    f = run.active_analyses_file()
    if not f.exists():
        return []
    from yomeru.core.annotations import AnnotationStore
    return AnnotationStore(run.output_dir()).merged_analyses(json.loads(f.read_text()))


def page_analysis(analyses: list[dict], page: int) -> dict:
    return next((a for a in analyses if a.get("page_number") == page), {})


def skipped_dialogues(analysis: dict) -> set[int]:
    return {i for i, d in enumerate(analysis.get("dialogues", [])) if d.get("skip")}


def load_render_log(run: "Run", page: int) -> dict | None:
    p = page_artifact(run, page, RENDER_LOG)
    return json.loads(p.read_text()) if p.exists() else None


def effective_matches(run: "Run", page: int, log: dict) -> list[dict]:
    from yomeru.core.matches import effective_matches as _eff
    return _eff(log, debug_dir(run), page)


def load_render_overrides(run: "Run", page: int) -> dict[int, dict]:
    """Render editor overrides as {dialogue_index: override}; malformed → {}."""
    p = page_artifact(run, page, RENDER_OVERRIDES)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, list):
        return {}
    return {o["dialogue_index"]: o for o in raw if isinstance(o, dict) and "dialogue_index" in o}


# ── Writes ────────────────────────────────────────────────────────────────────

def write_render_log(run: "Run", page: int, log: dict) -> None:
    """Replace the whole render log (matching owns its creation)."""
    p = page_artifact(run, page, RENDER_LOG)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock(p):
        p.write_text(json.dumps(log, indent=2, ensure_ascii=False))


def update_render_log(run: "Run", page: int, section: str, value: Any) -> None:
    """Set one section (s4_inpainting, s5_rendering…) under a per-file lock, so
    concurrent writers (phase thread + preview endpoint) never lose a section."""
    p = page_artifact(run, page, RENDER_LOG)
    with _log_lock(p):
        log = json.loads(p.read_text()) if p.exists() else {}
        log[section] = value
        p.write_text(json.dumps(log, indent=2, ensure_ascii=False))
