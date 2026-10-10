"""
Unified phases API — single entry point for all phase operations.

Routes:
  POST /api/phases/{run_id}/{phase}/start   — Start a phase
  POST /api/phases/{run_id}/{phase}/retry   — Retry failed pages
  GET  /api/phases/{run_id}/{phase}/status  — Get phase status
  POST /api/phases/{run_id}/start-all       — Run all phases sequentially
  GET  /api/phases/{run_id}/status          — Get all phases status
  WS   /api/phases/{run_id}/ws             — Progress stream
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket

from yomeru.core.images import serve_image
from pydantic import BaseModel

from yomeru.core.runs import Run
from yomeru.phases import PHASE_ORDER, PHASE_DEPS
from yomeru.core.gpu import gpu_lock
from yomeru.phases.runner import (
    PhaseError, active_job, check_dependencies, request_cancel, run_all, run_phase, start_job,
)
from yomeru.api.ws import ws_handler, make_emitter

router = APIRouter(prefix="/phases", tags=["phases"])


class PhaseStartRequest(BaseModel):
    options: dict[str, Any] = {}
    page_scope: list[int] | None = None


class StartAllRequest(BaseModel):
    options: dict[str, Any] = {}
    start_from: str | None = None


# ── Phase execution ────────────────────────────────────────────────────────────

def _launch(run: Run, label: str, work, first_phase: str | None) -> None:
    """Reserve the run and start `work(emit)`; maps start errors to HTTP codes."""
    emit_base = make_emitter(run.id)
    try:
        start_job(run, label, lambda emit, _cancel: work(emit), on_progress=emit_base,
                  first_phase=first_phase)
    except PhaseError as e:
        raise HTTPException(409 if e.code == "busy" else 400, detail=str(e))


@router.post("/{run_id}/{phase}/start")
def start_phase(run_id: str, phase: str, body: PhaseStartRequest | None = None):
    """Start a phase (optionally only for some pages)."""
    run = _get_run(run_id)
    _validate_phase(phase)
    req = body or PhaseStartRequest()
    options = _build_phase_options(run, phase, req.options)
    _launch(run, phase,
            lambda emit: run_phase(run, phase, options=options, on_progress=emit, page_scope=req.page_scope),
            first_phase=phase)
    return {"status": "started", "phase": phase, "run_id": run_id}


@router.post("/{run_id}/{phase}/retry")
def retry_phase(run_id: str, phase: str, body: PhaseStartRequest | None = None):
    """Re-run a phase that already ran (all pages, or `page_scope`)."""
    run = _get_run(run_id)
    _validate_phase(phase)
    if run.get_phase_status(phase) == "pending":
        raise HTTPException(400, detail=f"Phase '{phase}' hasn't been run yet")
    req = body or PhaseStartRequest()
    options = _build_phase_options(run, phase, req.options)
    _launch(run, phase,
            lambda emit: run_phase(run, phase, options=options, on_progress=emit, page_scope=req.page_scope),
            first_phase=phase)
    return {"status": "started", "phase": phase, "run_id": run_id, "mode": "retry"}


@router.post("/{run_id}/cancel")
def cancel(run_id: str):
    """Stop the running job after the page in progress."""
    _get_run(run_id)
    if not request_cancel(run_id):
        raise HTTPException(409, detail="Nothing is running on this run")
    return {"status": "cancelling", "run_id": run_id}


class ReanalysisRequest(BaseModel):
    page_number: int
    corrections: dict[str, str] = {}  # dialogue_index -> correction text


@router.post("/{run_id}/analysis/reanalyze")
def reanalyze_with_corrections(run_id: str, body: ReanalysisRequest):
    """Re-run analysis for a single page with per-dialogue corrections."""
    run = _get_run(run_id)
    options = _build_phase_options(run, "analysis", {})
    correction_lines = [f"- Dialogue #{i}: {c}" for i, c in body.corrections.items()]
    if correction_lines:
        options["page_context"] = (
            "## Corrections from reviewer\n"
            "The previous analysis had errors. Apply these corrections:\n"
            + "\n".join(correction_lines)
            + "\n\nKeep all other data accurate. Fix ONLY what's mentioned above."
        )
    _launch(run, "analysis",
            lambda emit: run_phase(run, "analysis", options=options, on_progress=emit,
                                   page_scope=[body.page_number]),
            first_phase="analysis")
    return {"status": "started", "phase": "analysis", "run_id": run_id, "mode": "reanalysis",
            "page": body.page_number}


@router.post("/{run_id}/matching/algorithm-only/{page_num}")
def run_algorithm_only_matching(run_id: str, page_num: int):
    """
    Run ONLY the Hungarian algorithm matching for a specific page (no VLM).
    Returns detailed scoring breakdown for comparison purposes.
    """
    from PIL import Image
    from yomeru.lib.matching import build_matcher
    from yomeru.phases.matching import (
        _load_detections, _load_analyses, _region_from_det, _to_pixel_bbox,
    )

    run = _get_run(run_id)
    detections = _load_detections(run)
    analyses = _load_analyses(run)

    if page_num not in detections:
        raise HTTPException(404, f"No detections for page {page_num}")

    page_dets = detections[page_num]
    # Only use text-bearing regions
    text_regions = {k: v for k, v in page_dets.items() if v.get("label") in ("text_bubble", "text_free")}
    if not text_regions:
        return {"page": page_num, "matches": [], "unmatched": [], "regions_used": 0, "dialogues_total": 0}

    # Find analyses for this page
    page_analyses = [a for a in analyses if a.get("page_number") == page_num]
    if not page_analyses:
        raise HTTPException(404, f"No analyses for page {page_num}")

    page_data = page_analyses[0]
    dialogues = [d for d in page_data.get("dialogues", []) if not d.get("skip")]
    if not dialogues:
        return {"page": page_num, "matches": [], "unmatched": [], "regions_used": 0, "dialogues_total": 0}

    # Load image
    pages_dir = run.pages_dir()
    from yomeru.core.paths import list_page_files
    page_files = list_page_files(pages_dir)
    img_path = page_files[page_num - 1] if page_num <= len(page_files) else None
    if not img_path or not img_path.exists():
        raise HTTPException(404, f"Page image not found for page {page_num}")

    img = Image.open(img_path)
    img_w, img_h = img.size

    # Analysis image size (for bbox conversion)
    analysis_w = page_data.get("image_width", img_w)
    analysis_h = page_data.get("image_height", img_h)

    # Build regions list
    regions = [_region_from_det(det, img_w, img_h) for det in text_regions.values()]
    region_ids = list(text_regions.keys())

    # Build hint bboxes from dialogue bbox fields
    hint_bboxes = [
        _to_pixel_bbox(d.get("bbox", [0, 0, 0, 0]), img_w, img_h, analysis_w, analysis_h)
        for d in dialogues
    ]

    # Get run config
    meta = run.meta()
    source_lang = page_data.get("source_language", meta.get("source_language", "auto"))

    # Run Hungarian matcher
    matcher = build_matcher()
    results = matcher.match(
        image=img,
        dialogues=dialogues,
        regions=regions,
        hint_bboxes=hint_bboxes,
        source_language=source_lang,
        ocr_weight=0.4,
        spatial_weight=0.4,
        position_weight=0.2,
        min_score=0.0,  # Show all results, even poor matches
    )

    # Build response with full scoring details
    match_details = []
    for dlg_idx, m in results.items():
        # Find which region_id this matched to
        matched_rid = None
        for idx, r in enumerate(regions):
            if r is m.region:
                matched_rid = region_ids[idx]
                break

        match_details.append({
            "dialogue_index": dlg_idx,
            "dialogue_text": dialogues[dlg_idx].get("text", "")[:80],
            "speaker": dialogues[dlg_idx].get("speaker", ""),
            "region_id": matched_rid,
            "region_label": text_regions[matched_rid]["label"] if matched_rid else None,
            "region_bbox": [m.region.x1, m.region.y1, m.region.x2, m.region.y2],
            "scores": {
                "spatial": round(m.spatial_score, 3),
                "text": round(m.text_score, 3),
                "position": round(m.position_score, 3),
                "total": round(m.total_score, 3),
            },
            "ocr_text": m.ocr_text[:60] if m.ocr_text else None,
            # Compare with VLM assignment
            "vlm_region_id": dialogues[dlg_idx].get("region_id"),
            "agrees_with_vlm": matched_rid == dialogues[dlg_idx].get("region_id"),
        })

    unmatched_indices = [i for i in range(len(dialogues)) if i not in results]
    unmatched_details = [
        {"dialogue_index": i, "dialogue_text": dialogues[i].get("text", "")[:80], "speaker": dialogues[i].get("speaker", "")}
        for i in unmatched_indices
    ]

    # Generate debug image
    from PIL import ImageDraw, ImageFont
    debug_img = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(debug_img, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font

    COLOR_MATCHED = (59, 130, 246, 100)   # blue fill
    BORDER_MATCHED = (59, 130, 246, 220)
    COLOR_UNMATCHED_REG = (239, 68, 68, 60)
    BORDER_UNMATCHED_REG = (239, 68, 68, 150)

    # Draw all text regions as unmatched first
    matched_region_ids = set()
    for dlg_idx, m in results.items():
        for idx, r in enumerate(regions):
            if r is m.region:
                matched_region_ids.add(region_ids[idx])

    for rid, det in text_regions.items():
        x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
        if rid not in matched_region_ids:
            draw.rectangle([x1, y1, x2, y2], fill=COLOR_UNMATCHED_REG, outline=BORDER_UNMATCHED_REG, width=2)
            draw.text((x1 + 3, y1 + 2), f"R{rid} unmatched", fill=(239, 68, 68, 255), font=font_sm)

    # Draw matched regions
    for dlg_idx, m in results.items():
        r = m.region
        draw.rectangle([r.x1, r.y1, r.x2, r.y2], fill=COLOR_MATCHED, outline=BORDER_MATCHED, width=2)
        label = f"D{dlg_idx}→R{match_details[next(i for i, md in enumerate(match_details) if md['dialogue_index'] == dlg_idx)]['region_id']} ({m.total_score:.2f})"
        draw.text((r.x1 + 3, r.y1 + 2), label, fill=(255, 255, 255, 255), font=font)
        text_preview = dialogues[dlg_idx].get("text", "")[:30]
        if text_preview:
            draw.text((r.x1 + 3, r.y2 - 16), text_preview, fill=(200, 200, 200, 220), font=font_sm)

    # Legend
    lx, ly = img_w - 200, 10
    draw.rectangle([lx - 5, ly - 5, img_w - 5, ly + 45], fill=(0, 0, 0, 180))
    draw.rectangle([lx, ly, lx + 12, ly + 12], fill=COLOR_MATCHED, outline=BORDER_MATCHED)
    draw.text((lx + 16, ly - 1), "Algorithm match", fill=(255, 255, 255), font=font_sm)
    draw.rectangle([lx, ly + 18, lx + 12, ly + 30], fill=COLOR_UNMATCHED_REG, outline=BORDER_UNMATCHED_REG)
    draw.text((lx + 16, ly + 17), "Unmatched region", fill=(255, 255, 255), font=font_sm)

    # Save debug image
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_path = debug_dir / f"p{page_num:02d}_algo_only.jpg"
    debug_img.convert("RGB").save(str(debug_path), quality=85)

    return {
        "page": page_num,
        "matches": match_details,
        "unmatched": unmatched_details,
        "regions_used": len(text_regions),
        "dialogues_total": len(dialogues),
        "agreement_rate": round(
            sum(1 for m in match_details if m["agrees_with_vlm"]) / max(1, len(match_details)) * 100, 1
        ),
        "debug_image": f"p{page_num:02d}_algo_only.jpg",
    }


@router.get("/{run_id}/inpainting/mask-debug/{page_num}")
def get_mask_debug(run_id: str, page_num: int, request: Request, w: int | None = None):
    """
    Generate mask debug overlay for a page (always regenerates).
    Shows the auto-generated masks colored per region over the original image.
    """
    import json
    from PIL import Image
    from yomeru.lib.inpainting import build_text_mask

    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"

    log_path = debug_dir / f"p{page_num:02d}_render_log.json"
    if not log_path.exists():
        raise HTTPException(404, f"No render log for page {page_num}")

    pages_dir = run.pages_dir()
    from yomeru.core.paths import list_page_files
    all_pages = list_page_files(pages_dir)
    if page_num < 1 or page_num > len(all_pages):
        raise HTTPException(404, f"Page {page_num} not found")

    img = Image.open(all_pages[page_num - 1]).convert("RGB")
    log = json.loads(log_path.read_text())

    per_region_masks = []
    for m in log.get("s3_matching", {}).get("matches", []):
        r = m["region"]
        bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
        label = r.get("label", "text_bubble")
        text_mask = build_text_mask(img, bbox, region_label=label)
        per_region_masks.append((bbox, label, text_mask))

    from yomeru.phases.inpainting import _save_mask_debug
    out_path = debug_dir / f"p{page_num:02d}_s4_mask_debug.jpg"
    _save_mask_debug(img, per_region_masks, debug_dir, page_num)

    return serve_image(request, out_path, w)


def _ensure_rendered(run: Run, page_num: int, force: bool) -> None:
    from yomeru.lib.rendering.scanline_engine import RenderInputMissing, is_cached, render_page
    if force or not is_cached(run, page_num):
        try:
            with gpu_lock():
                render_page(run, page_num)
        except RenderInputMissing as e:
            raise HTTPException(404, str(e))


@router.get("/{run_id}/rendering/scanline-preview/{page_num}")
def get_scanline_preview(run_id: str, page_num: int, request: Request, force: int = 0, w: int | None = None):
    """Debug render (green bubble contours). Regenerated when inputs change."""
    from yomeru.lib.rendering.scanline_engine import output_paths
    run = _get_run(run_id)
    _ensure_rendered(run, page_num, bool(force))
    return serve_image(request, output_paths(run, page_num)[0], w)


@router.get("/{run_id}/rendering/scanline-production/{page_num}")
def get_scanline_production(run_id: str, page_num: int, request: Request, force: int = 0, w: int | None = None):
    """Final render (no contour lines). Regenerated when inputs change."""
    from yomeru.lib.rendering.scanline_engine import output_paths
    run = _get_run(run_id)
    _ensure_rendered(run, page_num, bool(force))
    return serve_image(request, output_paths(run, page_num)[1], w)


@router.post("/{run_id}/start-all")
def start_all_phases(run_id: str, body: StartAllRequest | None = None):
    """Run all phases sequentially (optionally from `start_from`)."""
    run = _get_run(run_id)
    req = body or StartAllRequest()
    start_from = req.start_from or PHASE_ORDER[0]
    _validate_phase(start_from)
    options = _build_all_options(run, req.options)
    _launch(run, "all", lambda emit: run_all(run, options=options, on_progress=emit, start_from=start_from),
            first_phase=start_from)
    return {"status": "started", "run_id": run_id, "mode": "all", "start_from": start_from}


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/{run_id}/{phase}/status")
def phase_status(run_id: str, phase: str):
    """Get status for a specific phase."""
    run = _get_run(run_id)
    _validate_phase(phase)

    meta = run.meta()
    status = meta.get("phase_status", {}).get(phase, "pending")
    deps_met = not check_dependencies(run, phase)

    return {
        "phase": phase,
        "status": status,
        "dependencies_met": deps_met,
        "dependencies": PHASE_DEPS[phase],
    }


@router.get("/{run_id}/status")
def all_phases_status(run_id: str):
    """Get status for all phases."""
    run = _get_run(run_id)
    meta = run.meta()
    phase_status = meta.get("phase_status", {})

    phases = []
    for p in PHASE_ORDER:
        deps_met = not check_dependencies(run, p)
        phases.append({
            "phase": p,
            "status": phase_status.get(p, "pending"),
            "dependencies_met": deps_met,
            "dependencies": PHASE_DEPS[p],
        })

    return {"run_id": run_id, "phases": phases, "running": active_job(run_id)}


# ── WebSocket ──────────────────────────────────────────────────────────────────

@router.websocket("/{run_id}/ws")
async def phases_ws(websocket: WebSocket, run_id: str):
    """WebSocket for real-time phase progress."""
    await ws_handler(websocket, run_id)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_run(run_id: str) -> Run:
    run = Run.load(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run '{run_id}' not found")
    return run


def _validate_phase(phase: str) -> None:
    if phase not in PHASE_ORDER:
        raise HTTPException(400, detail=f"Invalid phase: '{phase}'. Must be one of {PHASE_ORDER}")


def _phase_options(run: Run, phase: str) -> dict:
    """Options for one phase, from the run's settings snapshot."""
    from yomeru.core.settings import run_settings
    meta = run.meta()
    st = run_settings(meta)
    lang = st.language
    if phase == "detection":
        return {"backend": st.detection.backend, "threshold": st.detection.threshold}
    if phase == "analysis":
        return {
            "model": st.analysis_model.model_dump(),
            "comic_format": lang.comic_format,
            "source_language": lang.source,
            "target_language": lang.target,
            "ui_language": meta.get("ui_language", lang.target),
            "global_context": meta.get("global_context", ""),
        }
    if phase == "matching":
        m = st.matching
        return {"ocr_weight": m.ocr_weight, "spatial_weight": m.spatial_weight,
                "position_weight": m.position_weight, "match_min_score": m.min_score}
    if phase == "inpainting":
        return {"inpainter_backend": st.inpainting.backend}
    if phase == "rendering":
        return {"source_language": lang.source, "target_language": lang.target,
                "use_translation": st.rendering.use_translation}
    return {}


def _build_phase_options(run: Run, phase: str, overrides: dict) -> dict:
    """Build phase options from the run snapshot + request overrides."""
    options = _phase_options(run, phase)
    options.update(overrides)
    return options


def _build_all_options(run: Run, overrides: dict) -> dict:
    """Build options dict keyed by phase name for run-all."""
    options = {p: _phase_options(run, p) for p in PHASE_ORDER}
    for key, val in overrides.items():
        if key in PHASE_ORDER and isinstance(val, dict):
            options.setdefault(key, {}).update(val)
    return options
