"""
Unified phases API — single entry point for all phase operations.

Routes:
  POST /api/phases/{run_id}/{phase}/start   — Start a phase (all pages or `page_scope`)
  POST /api/phases/{run_id}/start-all       — Run all phases sequentially
  GET  /api/phases/{run_id}/status          — Status of every phase + the running job
  WS   /api/phases/{run_id}/ws             — Progress stream
"""
from __future__ import annotations

import json
import threading

from yomeru.config.labels import is_text
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket

from yomeru.runs import artifacts
from yomeru.infra.images import serve_image
from pydantic import BaseModel

from yomeru.runs.run import Run
from yomeru.pipeline.phases import PHASE_ORDER, PHASE_DEPS
from yomeru.pipeline.runner import (
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
    from yomeru.stages.matching import build_matcher
    from yomeru.runs import artifacts
    from yomeru.stages.matching.phase import _region_from_det, _to_pixel_bbox

    run = _get_run(run_id)
    detections = artifacts.load_detections(run)
    analyses = artifacts.load_analyses(run)

    if page_num not in detections:
        raise HTTPException(404, f"No detections for page {page_num}")

    page_dets = detections[page_num]
    # Only use text-bearing regions
    text_regions = {k: v for k, v in page_dets.items() if is_text(v.get("label"))}
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
    img_path = dict(artifacts.page_files(run)).get(page_num)
    if not img_path or not img_path.exists():
        raise HTTPException(404, f"Page image not found for page {page_num}")

    img = Image.open(img_path)
    img_w, img_h = img.size

    # Size of the image the model saw (dialogue bboxes are in that space).
    # Was reading `image_width`, a key analysis never writes → wrong scaling.
    analysis_w = int(page_data.get("analysis_image_w") or img_w)
    analysis_h = int(page_data.get("analysis_image_h") or img_h)

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

    # Run Hungarian matcher with the run's own weights
    from yomeru.config.settings import run_settings
    mo = run_settings(run.meta()).matching.options
    matcher = build_matcher()
    results = matcher.match(
        image=img,
        dialogues=dialogues,
        regions=regions,
        hint_bboxes=hint_bboxes,
        source_language=source_lang,
        ocr_weight=float(mo.get("ocr_weight", 0.4)),
        spatial_weight=float(mo.get("spatial_weight", 0.4)),
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
    from PIL import ImageDraw
    from yomeru.infra.images import overlay_font
    debug_img = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(debug_img, "RGBA")
    font, font_sm = overlay_font(14), overlay_font(11, bold=False)

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

    artifacts.debug_dir(run, create=True)
    debug_path = artifacts.page_artifact(run, page_num, artifacts.ALGO_ONLY)
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
    """Per-region mask overlay written by the inpainting phase.

    It used to be regenerated on every request from the raw automatic matches,
    ignoring refined matches, skips and mask edits — so it could disagree with
    what was actually inpainted. Now it is the phase's own artifact.
    """
    from yomeru.runs import artifacts
    run = _get_run(run_id)
    path = artifacts.page_artifact(run, page_num, artifacts.S4_MASK_DEBUG)
    if not path.exists():
        raise HTTPException(404, f"No inpainting masks for page {page_num} — run inpainting first")
    return serve_image(request, path, w)


_render_locks: dict[tuple[str, int], threading.Lock] = {}
_render_locks_guard = threading.Lock()


def _ensure_rendered(run: Run, page_num: int, force: bool) -> None:
    """Re-render a stale page once: the strip thumbnail, blur placeholder,
    preview and production requests for the same page arrive together; the
    first renders, the rest wait and reuse it (they used to render in
    parallel, thrash the CPU and race on the temp file → 500s)."""
    from yomeru.stages.rendering.scanline_engine import RenderInputMissing, is_cached, render_page
    if not force and is_cached(run, page_num):
        return
    with _render_locks_guard:
        lock = _render_locks.setdefault((run.id, page_num), threading.Lock())
    with lock:
        if not force and is_cached(run, page_num):
            return
        try:
            render_page(run, page_num)  # takes the GPU lock only if its backend needs it
        except RenderInputMissing as e:
            raise HTTPException(404, str(e))


class RerenderRequest(BaseModel):
    dialogues: list[int] | None = None   # None = every dialogue the image-edit model drew or tried


@router.post("/{run_id}/rendering/rerender/{page_num}")
def rerender_with_image_edit(run_id: str, page_num: int, body: RerenderRequest | None = None):
    """Ask the image-edit model again (new seed, so the cache is bypassed) for
    some dialogues of a page — listed ones are also marked to be drawn by it —
    then re-render that page."""
    from yomeru.config.settings import run_settings
    run = _get_run(run_id)
    if page_num not in dict(artifacts.page_files(run)):
        raise HTTPException(404, detail=f"Page {page_num} not found")
    if run_settings(run.meta()).rendering.backend != "image_edit":
        raise HTTPException(400, detail="This run is not rendered with an image-edit model")
    if run.get_phase_status("rendering") == "pending":
        raise HTTPException(400, detail="Phase 'rendering' hasn't been run yet")
    req = body or RerenderRequest()
    overrides = artifacts.load_render_overrides(run, page_num)
    if req.dialogues is None:
        log = artifacts.load_render_log(run, page_num) or {}
        targets = [e["dialogue_index"] for e in (log.get("s5_rendering") or {}).get("renders", [])
                   if e.get("engine") == "ai" or e.get("fallback")]
    else:
        targets = req.dialogues
    if not targets:
        raise HTTPException(400, detail="No dialogue of this page was drawn by an image-edit model")
    for i in targets:
        o = overrides.setdefault(i, {"dialogue_index": i})
        o["seed"] = int(o.get("seed") or 0) + 1
        if req.dialogues is not None:
            o["engine"] = "ai"
    artifacts.debug_dir(run, create=True)
    f = artifacts.page_artifact(run, page_num, artifacts.RENDER_OVERRIDES)
    tmp = artifacts.tmp_path(f)
    tmp.write_text(json.dumps(list(overrides.values()), indent=2))
    tmp.replace(f)
    options = _build_phase_options(run, "rendering", {})
    _launch(run, "rendering",
            lambda emit: run_phase(run, "rendering", options=options, on_progress=emit, page_scope=[page_num]),
            first_phase="rendering")
    return {"status": "started", "phase": "rendering", "run_id": run_id, "page": page_num, "dialogues": targets}


@router.get("/{run_id}/rendering/scanline-preview/{page_num}")
def get_scanline_preview(run_id: str, page_num: int, request: Request, force: int = 0, w: int | None = None):
    """Debug render (green bubble contours). Regenerated when inputs change."""
    from yomeru.stages.rendering.scanline_engine import output_paths
    run = _get_run(run_id)
    _ensure_rendered(run, page_num, bool(force))
    return serve_image(request, output_paths(run, page_num)[0], w)


@router.get("/{run_id}/rendering/scanline-production/{page_num}")
def get_scanline_production(run_id: str, page_num: int, request: Request, force: int = 0, w: int | None = None):
    """Final render (no contour lines). Regenerated when inputs change."""
    from yomeru.stages.rendering.scanline_engine import output_paths
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


def _translation_settings(run: Run) -> dict:
    """The model that translates for this run: the separate translator when
    the switch is on, else the reading model used as a text model."""
    from yomeru.config.settings import run_settings
    st = run_settings(run.meta())
    sep = st.analysis.separate_translation
    if sep.enabled:
        if not (sep.local or st.translation_model.is_set()):
            raise HTTPException(400, "no translation model configured")
        return {**sep.model_dump(), "model": st.translation_model.model_dump()}
    if st.analysis.backend == "local":
        o = st.analysis.options
        return {"local": True, "local_model": o.get("model") or "auto",
                "local_server": o.get("server") or "http://127.0.0.1:11434"}
    return {"local": False, "model": st.analysis_model.model_dump()}


def _translation_state(run: Run) -> dict:
    """Glossary + review flags + mode, whatever produced the translation."""
    tr = artifacts.load_translations(run)
    ctx = json.loads(run.context_file().read_text()) if run.context_file().exists() else {}
    if tr.get("style", {}).get("glossary") is not None:
        glossary = tr["style"]["glossary"]
    else:   # all-in-one: the glossary the pages carried forward
        glossary = [{"source": k, "target": v} for k, v in (ctx.get("glossary") or {}).items()]
    return {"glossary": glossary, "review": tr.get("review") or {}, "model": tr.get("model"),
            "retranslated_lines": len(tr.get("lines") or {}), "style": tr.get("style") or {}}


@router.get("/{run_id}/translation")
def get_translation(run_id: str):
    run = _get_run(run_id)
    if not run.analyses_file().exists():
        raise HTTPException(404, "read the pages first")
    st = _translation_state(run)
    st.pop("style", None)
    return st


class TranslateRequest(BaseModel):
    scope: str = "all"                         # all | affected
    glossary: list[dict] | None = None         # new glossary (scope=affected)


@router.post("/{run_id}/translate")
def retranslate(run_id: str, body: TranslateRequest | None = None):
    """Re-translate without reading again. scope=all: the whole chapter
    (new style guide). scope=affected + glossary: save the glossary and
    re-translate only the lines it touches, with it as context."""
    from yomeru.stages.analysis.translation import affected_keys, collect_lines, glossary_of
    from yomeru.stages.analysis.phase import translate_run
    run = _get_run(run_id)
    if not run.analyses_file().exists():
        raise HTTPException(400, "read the pages first")
    req = body or TranslateRequest()
    translation = _translation_settings(run)
    opts = _phase_options(run, "analysis")
    keys = style = None
    if req.scope == "affected":
        if req.glossary is None:
            raise HTTPException(400, "glossary required")
        glossary = [{"source": str(g.get("source", "")).strip(), "target": str(g.get("target", "")).strip()}
                    for g in req.glossary if str(g.get("source", "")).strip() and str(g.get("target", "")).strip()]
        state = _translation_state(run)
        old = {g["source"]: g["target"] for g in state["glossary"]}
        style = {**state["style"], "glossary": glossary}
        analyses = artifacts.load_analyses(run)
        current = {f"p{a['page_number']}.d{i}": d.get("text_translated") or ""
                   for a in analyses for i, d in enumerate(a.get("dialogues", []))}
        keys = affected_keys(collect_lines(analyses), current, old, glossary_of(style))
        _save_glossary(run, style)
        if not keys:
            return {"status": "saved", "affected": 0}
    elif req.scope != "all":
        raise HTTPException(400, "scope must be all or affected")

    def job(emit):
        translate_run(run, translation, opts["source_language"], opts["target_language"],
                      opts["global_context"], emit, keys=keys, style=style)
        run.mark_downstream_stale("analysis")
    _launch(run, "analysis", job, first_phase="analysis")
    return {"status": "started", "phase": "analysis", "step": "translate", "run_id": run_id,
            "affected": len(keys) if keys is not None else None}


def _save_glossary(run: Run, style: dict) -> None:
    tr = artifacts.load_translations(run)
    tr["style"] = style
    tr.setdefault("lines", {})
    f = run.output_dir() / artifacts.TRANSLATIONS
    tmp = artifacts.tmp_path(f)
    tmp.write_text(json.dumps(tr, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _phase_options(run: Run, phase: str) -> dict:
    """Options for one phase, from the run's settings snapshot."""
    from yomeru.config.settings import run_settings
    meta = run.meta()
    st = run_settings(meta)
    lang = st.language
    if phase == "detection":
        return {"backend": st.detection.backend, "backend_options": st.detection.options,
                "threshold": st.detection.threshold}
    if phase == "analysis":
        return {
            "backend": st.analysis.backend, "backend_options": st.analysis.options,
            "model": st.analysis_model.model_dump(),
            "translation": {**st.analysis.separate_translation.model_dump(),
                            "model": st.translation_model.model_dump()},
            "comic_format": lang.comic_format,
            "source_language": lang.source,
            "target_language": lang.target,
            "global_context": meta.get("global_context", ""),
        }
    if phase == "matching":
        return {"backend": st.matching.backend, "backend_options": st.matching.options,
                "comic_format": lang.comic_format}
    if phase == "inpainting":
        return {"backend": st.inpainting.backend, "backend_options": st.inpainting.options}
    if phase == "rendering":
        return {"backend": st.rendering.backend, "backend_options": st.rendering.options,
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
