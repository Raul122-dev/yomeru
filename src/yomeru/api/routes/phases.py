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

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel

from yomeru.core.runs import Run
from yomeru.phases import PHASE_ORDER, PHASE_DEPS, PhaseName
from yomeru.phases.runner import run_phase, run_all, check_dependencies, PhaseError
from yomeru.api.ws import ws_handler, make_emitter

router = APIRouter(prefix="/phases", tags=["phases"])


class PhaseStartRequest(BaseModel):
    options: dict[str, Any] = {}
    page_scope: list[int] | None = None


class StartAllRequest(BaseModel):
    options: dict[str, Any] = {}
    start_from: str | None = None


# ── Phase execution ────────────────────────────────────────────────────────────

@router.post("/{run_id}/{phase}/start")
def start_phase(run_id: str, phase: str, body: PhaseStartRequest | None = None):
    """Start a specific phase for a run."""
    run = _get_run(run_id)
    _validate_phase(phase)

    req = body or PhaseStartRequest()

    # Build options from run meta + request overrides
    options = _build_phase_options(run, phase, req.options)

    # Launch in background thread
    def worker():
        emit = make_emitter(run_id)
        run_phase(run, phase, options=options, on_progress=emit, page_scope=req.page_scope)

    try:
        # Pre-check dependencies before launching
        errors = check_dependencies(run, phase)
        if errors:
            raise HTTPException(400, detail="; ".join(errors))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return {"status": "started", "phase": phase, "run_id": run_id}

    except PhaseError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/{run_id}/{phase}/retry")
def retry_phase(run_id: str, phase: str, body: PhaseStartRequest | None = None):
    """Retry failed pages for a phase."""
    run = _get_run(run_id)
    _validate_phase(phase)

    # Determine which pages failed
    meta = run.meta()
    phase_status = meta.get("phase_status", {}).get(phase)
    if phase_status not in ("partial", "failed", "done"):
        raise HTTPException(400, detail=f"Phase '{phase}' hasn't been run yet")

    req = body or PhaseStartRequest()
    options = _build_phase_options(run, phase, req.options)

    # For retry, we pass page_scope of failed pages
    # The phase module handles retry logic internally
    def worker():
        emit = make_emitter(run_id)
        run_phase(run, phase, options=options, on_progress=emit, page_scope=req.page_scope)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return {"status": "started", "phase": phase, "run_id": run_id, "mode": "retry"}


class ReanalysisRequest(BaseModel):
    page_number: int
    corrections: dict[str, str] = {}  # dialogue_index -> correction text


@router.post("/{run_id}/analysis/reanalyze")
def reanalyze_with_corrections(run_id: str, body: ReanalysisRequest):
    """Re-run analysis for a single page with per-dialogue corrections."""
    run = _get_run(run_id)

    options = _build_phase_options(run, "analysis", {})
    # Inject corrections into page context
    correction_lines = []
    for idx_str, correction in body.corrections.items():
        correction_lines.append(f"- Dialogue #{idx_str}: {correction}")

    if correction_lines:
        page_context = (
            "## Corrections from reviewer\n"
            "The previous analysis had errors. Apply these corrections:\n"
            + "\n".join(correction_lines)
            + "\n\nKeep all other data accurate. Fix ONLY what's mentioned above."
        )
        options["page_context"] = page_context

    def worker():
        emit = make_emitter(run_id)
        run_phase(
            run, "analysis",
            options=options,
            on_progress=emit,
            page_scope=[body.page_number],
        )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return {"status": "started", "phase": "analysis", "run_id": run_id, "mode": "reanalysis", "page": body.page_number}


@router.post("/{run_id}/matching/algorithm-only/{page_num}")
def run_algorithm_only_matching(run_id: str, page_num: int):
    """
    Run ONLY the Hungarian algorithm matching for a specific page (no VLM).
    Returns detailed scoring breakdown for comparison purposes.
    """
    from PIL import Image
    from yomeru.lib.matching import build_matcher
    from yomeru.lib.detection import TextRegion
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
    page_files = sorted(pages_dir.glob("*.jpg")) + sorted(pages_dir.glob("*.png"))
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
def get_mask_debug(run_id: str, page_num: int):
    """
    Generate mask debug overlay for a page (always regenerates).
    Shows the auto-generated masks colored per region over the original image.
    """
    import json
    from PIL import Image
    from fastapi.responses import FileResponse
    from yomeru.lib.inpainting import build_text_mask

    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"

    log_path = debug_dir / f"p{page_num:02d}_render_log.json"
    if not log_path.exists():
        raise HTTPException(404, f"No render log for page {page_num}")

    pages_dir = run.pages_dir()
    all_pages = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
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

    return FileResponse(out_path)


@router.get("/{run_id}/rendering/scanline-preview/{page_num}")
def get_scanline_preview(run_id: str, page_num: int, force: int = 0):
    """
    Generate a preview of rendering using the scanline approach.
    Renders text using bubble contour detection + scanline layout.
    Returns the debug image (with green contours).
    Cached: only regenerates if force=1, files don't exist, or inputs are newer.
    """
    import json
    from PIL import Image, ImageDraw
    from fastapi.responses import FileResponse

    _NO_CACHE_HEADERS = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}
    
    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"
    out_path = debug_dir / f"p{page_num:02d}_scanline_preview.jpg"
    prod_path = debug_dir / f"p{page_num:02d}_scanline_production.jpg"

    # Invalidate cache if inputs are newer than cached output
    if not force and out_path.exists() and prod_path.exists():
        cache_mtime = out_path.stat().st_mtime
        # Check if any input file is newer than the cached output
        inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
        log_path = debug_dir / f"p{page_num:02d}_render_log.json"
        refined_matches_path = debug_dir / f"p{page_num:02d}_matches_refined.json"
        overrides_path = debug_dir / f"p{page_num:02d}_render_overrides.json"
        analyses_file = run.active_analyses_file()

        input_files = [inpainted_path, log_path, refined_matches_path, overrides_path, analyses_file]
        stale = any(f.exists() and f.stat().st_mtime > cache_mtime for f in input_files)
        if not stale:
            return FileResponse(out_path, headers=_NO_CACHE_HEADERS)

    from yomeru.core.typesetting.stages.rendering.pil import (
        _get_font, _tone_to_style, _draw_text_with_outline,
    )
    from yomeru.core.typesetting.stages.rendering.text_layout import (
        measure_line_height, measure_width, LANG_MAP, extract_embedded_breaks,
    )
    from yomeru.core.typesetting.stages.rendering.color_detect import (
        detect_background_color, detect_text_color, is_colored_text, compute_outline_color,
    )
    from yomeru.core.typesetting.stages.rendering.scanline import (
        extract_bubble_contour, scanline_layout,
    )

    output = run.output_dir()

    # Load inpainted image (for rendering text onto)
    inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
    if not inpainted_path.exists():
        raise HTTPException(404, "No inpainted image for this page")

    img = Image.open(inpainted_path).convert("RGB")

    # Load ORIGINAL page image (for bubble contour detection — has visible borders)
    pages_dir = run.pages_dir()
    all_pages = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if page_num < 1 or page_num > len(all_pages):
        raise HTTPException(404, f"Page {page_num} not found")
    original_img = Image.open(all_pages[page_num - 1]).convert("RGB")

    # Load matching data
    log_path = debug_dir / f"p{page_num:02d}_render_log.json"
    if not log_path.exists():
        raise HTTPException(404, "No render log for this page")
    log = json.loads(log_path.read_text())

    # Prefer refined matches if available
    refined_matches_path = debug_dir / f"p{page_num:02d}_matches_refined.json"
    if refined_matches_path.exists():
        try:
            from yomeru.phases.rendering import _build_matches_from_refined
            refined = json.loads(refined_matches_path.read_text())
            matches = _build_matches_from_refined(refined, log.get("s3_matching", {}))
        except (json.JSONDecodeError, KeyError):
            matches = log.get("s3_matching", {}).get("matches", [])
    else:
        matches = log.get("s3_matching", {}).get("matches", [])

    # Load analyses for dialogue text (merged with user edits)
    analyses_file = run.active_analyses_file()
    if analyses_file.exists():
        from yomeru.core.annotations import AnnotationStore
        original_analyses = json.loads(analyses_file.read_text())
        store = AnnotationStore(run.output_dir())
        analyses = store.merged_analyses(original_analyses)
    else:
        analyses = []
    page_analysis = next((a for a in analyses if a.get("page_number") == page_num), {})
    dialogues = page_analysis.get("dialogues", [])

    # Load render overrides if they exist
    overrides_path = debug_dir / f"p{page_num:02d}_render_overrides.json"
    overrides: dict[int, dict] = {}
    if overrides_path.exists():
        try:
            raw_overrides = json.loads(overrides_path.read_text())
            if isinstance(raw_overrides, list):
                overrides = {
                    o["dialogue_index"]: o
                    for o in raw_overrides
                    if isinstance(o, dict) and "dialogue_index" in o
                }
        except (json.JSONDecodeError, KeyError):
            pass

    # Load detections for bubble bboxes (use active/refined)
    dets_file = run.active_detections_file()
    detections = json.loads(dets_file.read_text()) if dets_file.exists() else []
    page_det = next((d for d in detections if d.get("page_number") == page_num), {})
    bubble_regions = [
        (r["x1"], r["y1"], r["x2"], r["y2"])
        for r in page_det.get("regions", []) if r.get("label") in ("bubble", "text_bubble")
    ]

    source_lang = page_analysis.get("source_language", "auto")
    lang_code = LANG_MAP.get(source_lang, "en_US")

    # Pre-compute contours for all bubbles (expensive, cache once)
    bubble_contours: dict[tuple[int, int, int, int], object] = {}
    for bb in bubble_regions:
        bubble_contours[bb] = extract_bubble_contour(original_img, bb)

    result_img = img.copy()
    draw = ImageDraw.Draw(result_img)

    # Deduplicate: when multiple dialogues share the same region bbox,
    # keep only the LAST one (typically the actual dialogue, not auxiliary text)
    seen_bboxes: dict[tuple[int, int, int, int], int] = {}
    for idx, m in enumerate(matches):
        r = m["region"]
        bbox_key = (r["x1"], r["y1"], r["x2"], r["y2"])
        seen_bboxes[bbox_key] = idx  # last one wins
    valid_match_indices = set(seen_bboxes.values())

    # ── Pass 1: Compute all layouts ──────────────────────────────────────────
    # Store: list of (positioned_lines, font, size, is_free, text_color, outline_color, bubble_bbox)
    all_layouts: list[tuple] = []

    for match_idx, m in enumerate(matches):
        if match_idx not in valid_match_indices:
            continue

        dlg_i = m.get("dialogue_index", -1)
        if dlg_i < 0 or dlg_i >= len(dialogues):
            continue

        dlg = dialogues[dlg_i]
        ovr = overrides.get(dlg_i, {})

        # Check for skip (override or VLM-suggested)
        if ovr.get("skip") or dlg.get("skip"):
            continue

        text = ovr.get("text_translated") or dlg.get("text_translated") or dlg.get("text", "")
        if not text.strip():
            continue

        r = m["region"]
        text_bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
        label = r.get("label", "text_bubble")

        # Find containing bubble
        tcx = (text_bbox[0] + text_bbox[2]) // 2
        tcy = (text_bbox[1] + text_bbox[3]) // 2
        bubble_bbox = text_bbox  # fallback
        for bx1, by1, bx2, by2 in bubble_regions:
            if bx1 <= tcx <= bx2 and by1 <= tcy <= by2:
                bubble_bbox = (bx1, by1, bx2, by2)
                break

        # Clean text
        clean_text, _ = extract_embedded_breaks(text)
        if not clean_text.strip():
            continue

        # Determine style and font
        tone = ovr.get("tone") or dlg.get("tone", "neutral")
        bubble_type = dlg.get("bubble_type", "speech")
        font_style_ovr = ovr.get("font_style") or dlg.get("font_style")
        style = font_style_ovr if font_style_ovr else _tone_to_style(tone, bubble_type)

        # Color detection on inpainted image
        bg_color = detect_background_color(img, text_bbox)
        lum = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
        text_color = (0, 0, 0) if lum > 128 else (255, 255, 255)
        is_free = label in ("text_free", "sfx")
        outline_color = compute_outline_color(bg_color) if is_free else None

        # Adaptive padding based on bubble size
        bubble_w = bubble_bbox[2] - bubble_bbox[0]
        bubble_h = bubble_bbox[3] - bubble_bbox[1]
        scan_padding = max(5, min(12, int(min(bubble_w, bubble_h) * 0.06)))

        # Max font size proportional to bubble height
        max_size = max(30, min(60, bubble_h // 6))

        # Try scanline layout — find best size that fills the bubble well
        best_layout = None

        for try_size in range(max_size, 9, -3):
            font = _get_font(style, try_size)
            lh = measure_line_height(font, try_size)

            for wf in (0.90, 0.70, 0.55, 0.45):
                positioned = scanline_layout(
                    original_img, bubble_bbox, clean_text, font, try_size,
                    lang_code, padding=scan_padding, width_factor=wf,
                    precomputed_contour=bubble_contours.get(bubble_bbox),
                )
                if not positioned:
                    continue

                text_h = len(positioned) * lh
                v_fill = text_h / max(1, bubble_h - scan_padding * 2)
                if v_fill > 0.95:
                    continue

                if 0.4 <= v_fill <= 0.85:
                    best_layout = (try_size, font, positioned)
                    break
                elif best_layout is None:
                    best_layout = (try_size, font, positioned)

            if best_layout and 0.4 <= (len(best_layout[2]) * measure_line_height(best_layout[1], best_layout[0])) / max(1, bubble_h - scan_padding * 2) <= 0.85:
                break

        # FALLBACK: if scanline failed, use simple bbox centered rendering
        if best_layout is None:
            from yomeru.core.typesetting.stages.rendering.text_layout import wrap_text
            for try_size in range(max_size, 9, -1):
                font = _get_font(style, try_size)
                lh = measure_line_height(font, try_size)
                pad = max(4, scan_padding)
                bw = bubble_w - pad * 2
                bh = bubble_h - pad * 2
                if bw < 10 or bh < 10:
                    continue
                max_lines = max(1, bh // lh)
                lines = wrap_text(clean_text, bw, max_lines, font, lang_code)
                if lines:
                    from yomeru.core.typesetting.stages.rendering.scanline import PositionedLine
                    total_h = len(lines) * lh
                    start_y = bubble_bbox[1] + pad + (bh - total_h) // 2
                    positioned_lines = []
                    for li, line in enumerate(lines):
                        lw = measure_width(line, font)
                        lx = bubble_bbox[0] + pad + (bw - lw) // 2
                        positioned_lines.append(PositionedLine(text=line, x=lx, y=start_y + li * lh, width=bw))
                    best_layout = (try_size, font, positioned_lines)
                    break

        if best_layout:
            all_layouts.append((best_layout, is_free, text_color, outline_color, bubble_bbox))

    # ── Pass 2: Resolve line-level collisions between regions ────────────────
    # For each layout, compute per-line bounding boxes
    layout_line_rects: list[list[tuple[int, int, int, int]]] = []
    for (size, font, positioned), *_ in all_layouts:
        lh = measure_line_height(font, size)
        rects = []
        for pl in positioned:
            lw = measure_width(pl.text, font)
            rects.append((pl.x, pl.y, pl.x + lw, pl.y + lh))
        layout_line_rects.append(rects)

    # Check each pair of layouts for line-level collisions and nudge
    # Minimum readability gap between texts of different regions (in pixels).
    # Texts closer than this will be pushed apart even without actual overlap.
    # Scaled by average font size for consistency across resolutions.
    avg_font_size = sum(layout[0][0] for layout in all_layouts) / max(1, len(all_layouts)) if all_layouts else 20
    MIN_GAP = max(8, int(avg_font_size * 0.6))

    for i in range(len(all_layouts)):
        for j in range(i + 1, len(all_layouts)):
            rects_i = layout_line_rects[i]
            rects_j = layout_line_rects[j]
            if not rects_i or not rects_j:
                continue

            # Quick check: do the overall bounds (expanded by MIN_GAP) overlap?
            bounds_i = (min(r[0] for r in rects_i) - MIN_GAP, min(r[1] for r in rects_i) - MIN_GAP,
                        max(r[2] for r in rects_i) + MIN_GAP, max(r[3] for r in rects_i) + MIN_GAP)
            bounds_j = (min(r[0] for r in rects_j) - MIN_GAP, min(r[1] for r in rects_j) - MIN_GAP,
                        max(r[2] for r in rects_j) + MIN_GAP, max(r[3] for r in rects_j) + MIN_GAP)

            if bounds_i[2] <= bounds_j[0] or bounds_j[2] <= bounds_i[0]:
                continue
            if bounds_i[3] <= bounds_j[1] or bounds_j[3] <= bounds_i[1]:
                continue

            # Find lines that collide OR are too close (within MIN_GAP)
            for li_idx, ri in enumerate(rects_i):
                for lj_idx, rj in enumerate(rects_j):
                    # Expand rects by MIN_GAP for proximity detection
                    # Check if they're within MIN_GAP of each other
                    gap_x = max(0, max(ri[0], rj[0]) - min(ri[2], rj[2]))  # horizontal gap
                    gap_y = max(0, max(ri[1], rj[1]) - min(ri[3], rj[3]))  # vertical gap

                    # Lines must be vertically adjacent (y ranges overlap or nearly overlap)
                    if gap_y > MIN_GAP:
                        continue
                    # Lines must be horizontally close
                    if gap_x > MIN_GAP:
                        continue

                    # Compute how much they overlap or how close they are
                    overlap_x = min(ri[2], rj[2]) - max(ri[0], rj[0])  # negative = gap
                    overlap_y = min(ri[3], rj[3]) - max(ri[1], rj[1])  # negative = gap

                    # Needed separation: if overlapping, need to push by overlap + gap
                    # If just too close, need to push by (MIN_GAP - current_gap)
                    needed_x = (overlap_x + MIN_GAP) if overlap_x > 0 else (MIN_GAP - gap_x)
                    needed_y = (overlap_y + MIN_GAP) if overlap_y > 0 else (MIN_GAP - gap_y)

                    if needed_x <= 0 and needed_y <= 0:
                        continue

                    (_, _, pos_i), *_ = all_layouts[i]
                    (_, _, pos_j), *_ = all_layouts[j]
                    bbox_i = all_layouts[i][4]  # bubble_bbox
                    bbox_j = all_layouts[j][4]

                    # Compute margins in all directions for both layouts
                    margin_top_i = rects_i[0][1] - bbox_i[1] if rects_i else 0
                    margin_bot_i = bbox_i[3] - rects_i[-1][3] if rects_i else 0
                    margin_left_i = min(r[0] for r in rects_i) - bbox_i[0] if rects_i else 0
                    margin_right_i = bbox_i[2] - max(r[2] for r in rects_i) if rects_i else 0

                    margin_top_j = rects_j[0][1] - bbox_j[1] if rects_j else 0
                    margin_bot_j = bbox_j[3] - rects_j[-1][3] if rects_j else 0
                    margin_left_j = min(r[0] for r in rects_j) - bbox_j[0] if rects_j else 0
                    margin_right_j = bbox_j[2] - max(r[2] for r in rects_j) if rects_j else 0

                    # Decide: horizontal or vertical nudge based on which requires less movement
                    if needed_x <= needed_y:
                        # Horizontal nudge is smaller — shift left/right
                        nudge_amount = needed_x

                        # Determine relative positions
                        center_x_i = (ri[0] + ri[2]) // 2
                        center_x_j = (rj[0] + rj[2]) // 2

                        # Decide who moves: check if nudge fits within the bubble.
                        # The region that can absorb the shift WITHOUT exiting its bubble wins.
                        if center_x_i < center_x_j:
                            # i is left, j is right
                            # Option A: push i left (needs margin_left_i >= nudge)
                            # Option B: push j right (needs margin_right_j >= nudge)
                            can_i_left = margin_left_i >= nudge_amount
                            can_j_right = margin_right_j >= nudge_amount

                            if can_i_left and (not can_j_right or margin_left_i >= margin_right_j):
                                shift = -nudge_amount
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x + shift,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                            elif can_j_right:
                                shift = nudge_amount
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x + shift,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                            else:
                                # Neither fully fits — split: move each by half
                                half = nudge_amount // 2 + 1
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x - half,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x + half,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                        else:
                            # j is left, i is right
                            can_j_left = margin_left_j >= nudge_amount
                            can_i_right = margin_right_i >= nudge_amount

                            if can_j_left and (not can_i_right or margin_left_j >= margin_right_i):
                                shift = -nudge_amount
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x + shift,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                            elif can_i_right:
                                shift = nudge_amount
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x + shift,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                            else:
                                half = nudge_amount // 2 + 1
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x - half,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x + half,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                    else:
                        # Vertical nudge is smaller — shift up/down
                        nudge_amount = needed_y // 2 + 2

                        center_y_i = (ri[1] + ri[3]) // 2
                        center_y_j = (rj[1] + rj[3]) // 2

                        total_margin_v_i = margin_top_i + margin_bot_i
                        total_margin_v_j = margin_top_j + margin_bot_j

                        if total_margin_v_i >= total_margin_v_j:
                            # Shift layout i's lines near the collision
                            shift = -nudge_amount if center_y_i < center_y_j else nudge_amount
                            if shift < 0:
                                for k in range(li_idx + 1):
                                    pos_i[k] = type(pos_i[k])(text=pos_i[k].text, x=pos_i[k].x, y=pos_i[k].y + shift, width=pos_i[k].width)
                            else:
                                for k in range(li_idx, len(pos_i)):
                                    pos_i[k] = type(pos_i[k])(text=pos_i[k].text, x=pos_i[k].x, y=pos_i[k].y + shift, width=pos_i[k].width)
                        else:
                            shift = -nudge_amount if center_y_j < center_y_i else nudge_amount
                            if shift < 0:
                                for k in range(lj_idx + 1):
                                    pos_j[k] = type(pos_j[k])(text=pos_j[k].text, x=pos_j[k].x, y=pos_j[k].y + shift, width=pos_j[k].width)
                            else:
                                for k in range(lj_idx, len(pos_j)):
                                    pos_j[k] = type(pos_j[k])(text=pos_j[k].text, x=pos_j[k].x, y=pos_j[k].y + shift, width=pos_j[k].width)

                    # Update rects after nudge
                    (size_i, font_i, _), *_ = all_layouts[i]
                    lh_i = measure_line_height(font_i, size_i)
                    layout_line_rects[i] = [(p.x, p.y, p.x + measure_width(p.text, font_i), p.y + lh_i) for p in pos_i]

                    (size_j, font_j, _), *_ = all_layouts[j]
                    lh_j = measure_line_height(font_j, size_j)
                    layout_line_rects[j] = [(p.x, p.y, p.x + measure_width(p.text, font_j), p.y + lh_j) for p in pos_j]
                    break  # Re-check after nudge
                else:
                    continue
                break  # Move to next pair after resolving

    # ── Pass 3: Render all layouts ───────────────────────────────────────────
    for layout_idx, ((size, font, positioned), is_free, text_color, outline_color, bubble_bbox) in enumerate(all_layouts):
        outline_w = max(1, size // 12) if is_free else 0
        for pl in positioned:
            if is_free and outline_color:
                _draw_text_with_outline(draw, (pl.x, pl.y), pl.text, font, text_color, outline_color, outline_w)
            else:
                draw.text((pl.x, pl.y), pl.text, font=font, fill=text_color)

        # Draw contour outline for debug (thin green)
        contour = bubble_contours.get(bubble_bbox)
        if contour is not None:
            pts = contour.reshape(-1, 2).tolist()
            if len(pts) > 2:
                draw.polygon([tuple(p) for p in pts], outline=(0, 200, 0))

    # Save debug version (with contours)
    out_path = debug_dir / f"p{page_num:02d}_scanline_preview.jpg"
    result_img.save(str(out_path), quality=90)

    # Save production version (without contours) — reuse resolved layouts
    prod_img = img.copy()
    prod_draw = ImageDraw.Draw(prod_img)

    for (size, font, positioned), is_free, text_color, outline_color, _bbox in all_layouts:
        outline_w = max(1, size // 12) if is_free else 0
        for pl in positioned:
            if is_free and outline_color:
                _draw_text_with_outline(prod_draw, (pl.x, pl.y), pl.text, font, text_color, outline_color, outline_w)
            else:
                prod_draw.text((pl.x, pl.y), pl.text, font=font, fill=text_color)

    prod_path = debug_dir / f"p{page_num:02d}_scanline_production.jpg"
    prod_img.save(str(prod_path), quality=90)

    return FileResponse(out_path, headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"})


@router.get("/{run_id}/rendering/scanline-production/{page_num}")
def get_scanline_production(run_id: str, page_num: int, force: int = 0):
    """Serve the production (no contour lines) scanline render."""
    from fastapi.responses import FileResponse

    _NO_CACHE_HEADERS = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}

    run = _get_run(run_id)
    debug_dir = run.output_dir() / "typeset" / "debug"
    prod_path = debug_dir / f"p{page_num:02d}_scanline_production.jpg"

    if not force and prod_path.exists():
        # Invalidate if inputs are newer
        cache_mtime = prod_path.stat().st_mtime
        inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
        log_path = debug_dir / f"p{page_num:02d}_render_log.json"
        refined_matches_path = debug_dir / f"p{page_num:02d}_matches_refined.json"
        overrides_path = debug_dir / f"p{page_num:02d}_render_overrides.json"
        analyses_file = run.active_analyses_file()
        input_files = [inpainted_path, log_path, refined_matches_path, overrides_path, analyses_file]
        stale = any(f.exists() and f.stat().st_mtime > cache_mtime for f in input_files)
        if not stale:
            return FileResponse(prod_path, headers=_NO_CACHE_HEADERS)

    # Generate both by calling preview
    get_scanline_preview(run_id, page_num, force=1)
    if not prod_path.exists():
        raise HTTPException(404, "Production render not available")
    return FileResponse(prod_path, headers=_NO_CACHE_HEADERS)


@router.post("/{run_id}/start-all")
def start_all_phases(run_id: str, body: StartAllRequest | None = None):
    """Run all phases sequentially."""
    run = _get_run(run_id)
    req = body or StartAllRequest()

    start_from = req.start_from
    if start_from:
        _validate_phase(start_from)

    options = _build_all_options(run, req.options)

    def worker():
        emit = make_emitter(run_id)
        run_all(run, options=options, on_progress=emit, start_from=start_from)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return {"status": "started", "run_id": run_id, "mode": "all"}


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

    return {"run_id": run_id, "phases": phases}


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


def _build_phase_options(run: Run, phase: str, overrides: dict) -> dict:
    """Build phase options from run meta + request overrides."""
    meta = run.meta()
    options = {}

    if phase == "detection":
        options["backend"] = meta.get("detector_backend", "auto")
        options["threshold"] = meta.get("detector_threshold", 0.4)

    elif phase == "analysis":
        from yomeru.core.config import build_litellm_model
        provider = meta.get("provider", "")
        model = meta.get("model", "")
        if provider and model:
            litellm_model, api_base = build_litellm_model(provider, model)
            options["model"] = litellm_model
            options["api_base"] = api_base
        options["comic_format"] = meta.get("comic_format", "auto")
        options["source_language"] = meta.get("source_language", "auto")
        options["target_language"] = meta.get("target_language", "Spanish")
        options["ui_language"] = meta.get("ui_language", "English")
        options["global_context"] = meta.get("global_context", "")

    elif phase == "matching":
        pass  # uses defaults

    elif phase == "inpainting":
        options["inpainter_backend"] = meta.get("inpainter_backend", "auto")

    elif phase == "rendering":
        options["source_language"] = meta.get("source_language", "auto")
        options["use_translation"] = True

    # Apply overrides
    options.update(overrides)
    return options


def _build_all_options(run: Run, overrides: dict) -> dict:
    """Build options dict keyed by phase name for run-all."""
    meta = run.meta()
    options = {}

    # Detection options
    options["detection"] = {
        "backend": meta.get("detector_backend", "auto"),
        "threshold": meta.get("detector_threshold", 0.4),
    }

    # Analysis options
    from yomeru.core.config import build_litellm_model
    provider = meta.get("provider", "")
    model = meta.get("model", "")
    analysis_opts = {
        "comic_format": meta.get("comic_format", "auto"),
        "source_language": meta.get("source_language", "auto"),
        "target_language": meta.get("target_language", "Spanish"),
        "ui_language": meta.get("ui_language", "English"),
        "global_context": meta.get("global_context", ""),
    }
    if provider and model:
        litellm_model, api_base = build_litellm_model(provider, model)
        analysis_opts["model"] = litellm_model
        analysis_opts["api_base"] = api_base
    options["analysis"] = analysis_opts

    # Inpainting
    options["inpainting"] = {"inpainter_backend": meta.get("inpainter_backend", "auto")}

    # Rendering
    options["rendering"] = {
        "source_language": meta.get("source_language", "auto"),
        "use_translation": True,
    }

    # Apply overrides (can override per-phase or globally)
    for key, val in overrides.items():
        if key in PHASE_ORDER and isinstance(val, dict):
            options.setdefault(key, {}).update(val)

    return options
