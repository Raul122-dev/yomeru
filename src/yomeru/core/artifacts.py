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
# Intermediates are lossless (PNG): the page used to go through JPEG twice
# (inpainted q88, then render q90) before the final copy.
S4_INPAINTED = "s4_inpainted.png"
S4_MASK_DEBUG = "s4_mask_debug.jpg"
SCANLINE_PREVIEW = "scanline_preview.jpg"
SCANLINE_PRODUCTION = "scanline_production.png"
_LEGACY_JPG = {S4_INPAINTED: "s4_inpainted.jpg"}  # runs made before the PNG switch
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


def existing_page_artifact(run: "Run", page: int, name: str) -> Path:
    """Like page_artifact, falling back to the legacy JPEG name of old runs."""
    p = page_artifact(run, page, name)
    if not p.exists() and name in _LEGACY_JPG:
        legacy = page_artifact(run, page, _LEGACY_JPG[name])
        if legacy.exists():
            return legacy
    return p


def tmp_path(path: Path) -> Path:
    """Per-writer temp name next to `path`: two threads saving the same file
    must not share it (a shared name raced → FileNotFoundError on replace)."""
    import os
    import threading
    return path.with_name(f"{path.stem}.{os.getpid()}-{threading.get_ident()}.tmp{path.suffix}")


def save_lossless(img, path: Path) -> None:
    """Atomic lossless save of an intermediate (fast PNG)."""
    tmp = tmp_path(path)
    img.convert("RGB").save(str(tmp), format="PNG", compress_level=1)
    tmp.replace(path)


# ── Effective inputs (user edits resolved) ────────────────────────────────────

def load_detections(run: "Run") -> dict[int, dict[int, dict]]:
    """Active detections as {page: {region_id: region}}."""
    f = run.active_detections_file()
    if not f.exists():
        return {}
    return {e["page_number"]: {r["id"]: r for r in e["regions"]} for e in json.loads(f.read_text())}


TRANSLATIONS = "translations.json"
REGION_ORIGINS = "region_origins.json"   # regions not from the detector: {page: {id: origin}}


def load_region_origins(run: "Run") -> dict[int, dict[int, str]]:
    f = run.output_dir() / REGION_ORIGINS
    if not f.exists():
        return {}
    return {int(p): {int(r): o for r, o in d.items()} for p, d in json.loads(f.read_text()).items()}


def add_region_origins(run: "Run", page: int, origins: dict[int, str]) -> None:
    data = {str(p): {str(r): o for r, o in d.items()} for p, d in load_region_origins(run).items()}
    data.setdefault(str(page), {}).update({str(r): o for r, o in origins.items()})
    f = run.output_dir() / REGION_ORIGINS
    tmp = tmp_path(f)
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(f)


def load_translations(run: "Run") -> dict:
    """Separate-translation output: {model, target_language, style, review,
    lines: {"p{page}.d{index}": text}}; {} when the run translated inline."""
    f = run.output_dir() / TRANSLATIONS
    return json.loads(f.read_text()) if f.exists() else {}


def load_analyses(run: "Run") -> list[dict]:
    """Active analyses with the final text of each line: the user's edits
    (edits.json) > the separate translation step > the reading's own
    `text_translated`."""
    f = run.active_analyses_file()
    if not f.exists():
        return []
    raw = json.loads(f.read_text())
    lines = load_translations(run).get("lines") or {}
    if lines:
        for a in raw:
            for i, d in enumerate(a.get("dialogues", [])):
                t = lines.get(f"p{a.get('page_number')}.d{i}")
                if t:
                    d["text_translated"] = t
    from yomeru.core.annotations import AnnotationStore
    return AnnotationStore(run.output_dir()).merged_analyses(raw)


def page_analysis(analyses: list[dict], page: int) -> dict:
    return next((a for a in analyses if a.get("page_number") == page), {})


def skipped_dialogues(analysis: dict, overrides: dict[int, dict] | None = None) -> set[int]:
    """Dialogues not to typeset (nor erase): the render editor's explicit
    skip True/False wins over the VLM's suggestion."""
    overrides = overrides or {}
    out = set()
    for i, d in enumerate(analysis.get("dialogues", [])):
        o = overrides.get(i, {})
        if (o["skip"] if "skip" in o else d.get("skip")):
            out.add(i)
    return out


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
