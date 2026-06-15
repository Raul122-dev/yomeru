"""
Editing routes — CRUD for refined artifacts.

Handles saving and reverting user-edited data for each phase's output:
  - Detections (phase 1 output)
  - Analyses (phase 2 output)
  - Matches (phase 3 output)
  - Masks (phase 4 input override)
  - Render overrides (phase 5 input override)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from yomeru.core.runs import Run

router = APIRouter(prefix="/runs", tags=["editing"])


def _get_run(run_id: str) -> Run:
    run = Run.load(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


# ── Detections ─────────────────────────────────────────────────────────────────

@router.get("/{run_id}/detections")
def get_detections(run_id: str):
    """Return all page detections (prefers refined if exists)."""
    run = _get_run(run_id)
    f = run.active_detections_file()
    if not f.exists():
        raise HTTPException(404, "detections not ready")
    return json.loads(f.read_text())


@router.get("/{run_id}/detections/{page_num}")
def get_page_detections(run_id: str, page_num: int):
    """Return detections for a single page (prefers refined)."""
    run = _get_run(run_id)
    f = run.active_detections_file()
    if not f.exists():
        raise HTTPException(404, "detections not ready")
    all_dets = json.loads(f.read_text())
    page = next((d for d in all_dets if d.get("page_number") == page_num), None)
    if not page:
        raise HTTPException(404, f"page {page_num} not found")
    return page


@router.put("/{run_id}/detections/{page_num}")
def save_page_detections(run_id: str, page_num: int, body: dict):
    """Save refined detections for a single page."""
    run = _get_run(run_id)
    from yomeru.core.annotator import save_detections
    regions = body.get("regions", [])
    original_w = body.get("original_w", 0)
    original_h = body.get("original_h", 0)
    save_detections(regions, run.output_dir(), page_num, (original_w, original_h), refined=True)
    return {"ok": True, "regions": len(regions)}


@router.delete("/{run_id}/detections/{page_num}/refined", status_code=204)
def revert_page_detections(run_id: str, page_num: int):
    """Remove refined detections for a page (revert to original)."""
    run = _get_run(run_id)
    refined = run.detections_file(refined=True)
    if refined.exists():
        try:
            all_dets = json.loads(refined.read_text())
            all_dets = [d for d in all_dets if d.get("page_number") != page_num]
            if all_dets:
                refined.write_text(json.dumps(all_dets, indent=2))
            else:
                refined.unlink()
        except Exception as e:
            raise HTTPException(500, f"revert failed: {e}")


# ── Analyses ───────────────────────────────────────────────────────────────────

@router.get("/{run_id}/analyses")
def get_analyses(run_id: str):
    """Return all page analyses with user edits merged on top."""
    run = _get_run(run_id)
    f = run.active_analyses_file()
    if not f.exists():
        raise HTTPException(404, "analyses not ready")
    original = json.loads(f.read_text())
    # Merge user edits (skip toggles, translation edits, etc.)
    from yomeru.core.annotations import AnnotationStore
    store = AnnotationStore(run.output_dir())
    return store.merged_analyses(original)


@router.put("/{run_id}/analyses/{page_num}/refined")
def save_analysis_page(run_id: str, page_num: int, body: dict):
    """Save refined analysis (translations, speaker, tone) for a single page."""
    run = _get_run(run_id)
    refined_f = run.analyses_file(refined=True)

    if refined_f.exists():
        try:
            all_analyses: list[dict] = json.loads(refined_f.read_text())
        except Exception:
            all_analyses = []
    else:
        orig = run.analyses_file(refined=False)
        all_analyses = json.loads(orig.read_text()) if orig.exists() else []

    all_analyses = [a for a in all_analyses if a.get("page_number") != page_num]
    body["page_number"] = page_num
    all_analyses.append(body)
    all_analyses.sort(key=lambda a: a.get("page_number", 0))
    refined_f.write_text(json.dumps(all_analyses, indent=2, ensure_ascii=False))
    return {"ok": True, "page_number": page_num}


@router.delete("/{run_id}/analyses/{page_num}/refined", status_code=204)
def revert_analysis_page(run_id: str, page_num: int):
    """Remove refined analysis for a page (revert to original VLM output)."""
    run = _get_run(run_id)
    refined_f = run.analyses_file(refined=True)
    if refined_f.exists():
        try:
            all_analyses = json.loads(refined_f.read_text())
            all_analyses = [a for a in all_analyses if a.get("page_number") != page_num]
            if all_analyses:
                refined_f.write_text(json.dumps(all_analyses, indent=2, ensure_ascii=False))
            else:
                refined_f.unlink()
        except Exception as e:
            raise HTTPException(500, f"revert failed: {e}")


# ── Matches ────────────────────────────────────────────────────────────────────

class MatchOverride(BaseModel):
    dialogue_index: int
    region_id: int
    match_type: str = "manual"
    dialogue_text: str = ""


class MatchesBody(BaseModel):
    matches: list[MatchOverride] = []


@router.put("/{run_id}/typeset/matches/{page_num}")
def save_page_matches(run_id: str, page_num: int, body: MatchesBody):
    """Persist refined matches for a page."""
    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    matches_file = debug_dir / f"p{page_num:02d}_matches_refined.json"
    matches_file.write_text(json.dumps(
        [m.model_dump() for m in body.matches], indent=2
    ))
    return {"ok": True, "matches": len(body.matches)}


@router.delete("/{run_id}/typeset/matches/{page_num}/refined", status_code=204)
def revert_page_matches(run_id: str, page_num: int):
    """Remove refined matches, reverting to auto matching."""
    run = _get_run(run_id)
    f = run.output_dir() / "typeset" / "debug" / f"p{page_num:02d}_matches_refined.json"
    if f.exists():
        f.unlink()


# ── Masks ──────────────────────────────────────────────────────────────────────

class MaskBody(BaseModel):
    mask_data_url: str  # base64 PNG data URL


@router.put("/{run_id}/typeset/masks/{page_num}")
def save_page_mask(run_id: str, page_num: int, body: MaskBody):
    """Save a refined inpainting mask as PNG."""
    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    data_url = body.mask_data_url
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        img_bytes = base64.b64decode(data_url)
        mask_file = debug_dir / f"p{page_num:02d}_mask_refined.png"
        mask_file.write_bytes(img_bytes)
        return {"ok": True, "path": str(mask_file)}
    except Exception as e:
        raise HTTPException(400, f"failed to decode mask: {e}")


# ── Render Overrides ───────────────────────────────────────────────────────────

class RenderOverrideItem(BaseModel):
    dialogue_index: int
    text_translated: str | None = None
    font_style: str | None = None
    font_size_override: int | None = None
    tone: str | None = None
    skip: bool | None = None


class RenderOverridesBody(BaseModel):
    render_overrides: list[RenderOverrideItem] = []


@router.put("/{run_id}/typeset/renders/{page_num}")
def save_render_overrides(run_id: str, page_num: int, body: RenderOverridesBody):
    """Persist render overrides for a page (consumed by rendering phase)."""
    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    overrides_file = debug_dir / f"p{page_num:02d}_render_overrides.json"
    overrides_file.write_text(json.dumps(
        [o.model_dump(exclude_none=True) for o in body.render_overrides], indent=2
    ))
    return {"ok": True}
