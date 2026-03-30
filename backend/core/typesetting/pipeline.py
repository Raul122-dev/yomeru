"""
Typesetting pipeline — 5 stages:

S1  VLM analysis          already done (page_analyses.json)
S2  Text detection        detector.build_detector().detect(image)
S3  OCR + matching        matcher.match_dialogues_to_regions()
S4  Inpainting            inpainter.inpaint(image, mask)
S5  Text rendering        renderer.render_text_in_bubble()

Each page produces:
  - typeset/{filename}          final result
  - typeset/debug/{page}_s2.jpg all detected regions
  - typeset/debug/{page}_s3.jpg matched regions with dialogue numbers
  - typeset/debug/{page}_s4.jpg clean image after inpainting
"""
from __future__ import annotations
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .detector import TextRegion, build_detector
from .stages.matching import build_matcher, MatchResult
from .stages.inpainting import build_inpainter, build_text_mask, lama_available
from .inpainter import inpaint, build_text_mask
from .stages.rendering import build_renderer, RenderResult


@dataclass
class TypesetOptions:
    use_translation: bool = True
    skip_sfx: bool = True
    skip_narration: bool = False
    padding: int = 12
    min_font_size: int = 9
    max_font_size: int = 30
    # stage backends — select implementation per stage
    detector_backend: str = "auto"       # "auto" | "ogkalu" | "ctd"
    detector_threshold: float = 0.5
    matcher_backend: str = "hungarian"   # "hungarian" (only option currently)
    inpainter_backend: str = "auto"      # "auto" | "lama" | "opencv"
    renderer_backend: str = "pil"        # "pil" (only option currently)
    # matching weights (must sum to ~1.0)
    ocr_weight: float = 0.4
    spatial_weight: float = 0.4
    position_weight: float = 0.2
    match_min_score: float = 0.05
    save_debug: bool = True



def region_from_detection(det: dict, img_w: int, img_h: int) -> "TextRegion":
    """Build a TextRegion from a saved detection dict."""
    import numpy as np
    x1 = max(0, min(img_w, int(det["x1"])))
    y1 = max(0, min(img_h, int(det["y1"])))
    x2 = max(0, min(img_w, int(det["x2"])))
    y2 = max(0, min(img_h, int(det["y2"])))
    return TextRegion(
        x1=x1, y1=y1, x2=x2, y2=y2,
        label=det.get("label", "bubble"),
        score=float(det.get("score", 1.0)),
        mask=None,
    )

def typeset_page(
    image_path: Path,
    analysis: dict,
    options: TypesetOptions | None = None,
    output_path: Path | None = None,
    output_dir: Path | None = None,   # run output dir — passed explicitly to avoid path inference
) -> dict:
    opts = options or TypesetOptions()
    if output_path is None:
        output_path = image_path.parent / f"{image_path.stem}_typeset{image_path.suffix}"

    debug_dir = output_path.parent / "debug"
    if opts.save_debug:
        debug_dir.mkdir(parents=True, exist_ok=True)

    image = Image.open(image_path).convert("RGB")
    img_w, img_h = image.size
    analysis_w = int(analysis.get("analysis_image_w", 0))
    analysis_h = int(analysis.get("analysis_image_h", 0))
    page_num = analysis.get("page_number", "?")
    source_lang = analysis.get("source_language", "auto") or "auto"

    # filter dialogues we'll process
    raw_dialogues = analysis.get("dialogues", [])
    dialogues = [
        d for d in raw_dialogues
        if not (opts.skip_sfx and d.get("bubble_type") == "sfx")
        and not (opts.skip_narration and d.get("bubble_type") == "narration")
    ]

    # ── S2: detect all text regions ─────────────────────────────────────────
    # Only run fresh detection if we don't have saved detections (legacy fallback)
    # In region_id mode, saved_detections IS the source of truth — no need to re-detect
    regions: list = []  # populated below only if needed for fallback

    # ── S3: match dialogues to regions ──────────────────────────────────────
    # Primary: region_id lookup (detection-first flow, precise)
    # Fallback: Hungarian OCR matching for dialogues without region_id

    from core.annotator import load_detections
    # output_dir is passed explicitly; fallback: runs/{id}/output/ is parent/../../output
    _det_dir = output_dir if output_dir is not None else (image_path.parent.parent / "output")
    saved_detections = load_detections(_det_dir, page_num)
    direct_mode = bool(saved_detections)
    if direct_mode:
        print(f"  [match] using {len(saved_detections)} saved detections (region_id mode)", file=sys.stderr)
    else:
        print(f"  [match] no saved detections — falling back to fresh detection + hungarian", file=sys.stderr)

    hint_bboxes = [
        _to_pixel_bbox(d.get("bbox", [0,0,0,0]), img_w, img_h, analysis_w, analysis_h)
        for d in dialogues
    ]

    matches: dict[int, MatchResult] = {}
    unresolved_indices: list[int] = []

    for i, dlg in enumerate(dialogues):
        rid = dlg.get("region_id")
        if rid and int(rid) in saved_detections:
            det = saved_detections[int(rid)]
            region = region_from_detection(det, img_w, img_h)
            matches[i] = MatchResult(
                dialogue_index=i, region=region,
                spatial_score=1.0, text_score=1.0,
                position_score=1.0, total_score=1.0,
                ocr_text="",
            )
            print(f"  [match] dlg {i} → region_id {rid} (direct)", file=sys.stderr)
        else:
            unresolved_indices.append(i)

    # fallback for any dialogues without region_id
    if unresolved_indices:
        if not regions:
            # run fresh detection now — only if actually needed
            detector = build_detector(opts.detector_backend)
            regions = detector.detect(image)
        fallback_dlgs   = [dialogues[i] for i in unresolved_indices]
        fallback_hints  = [hint_bboxes[i] for i in unresolved_indices]
        # exclude already-matched regions from candidates
        used_regions = {id(m.region) for m in matches.values()}
        candidate_regions = [r for r in regions if id(r) not in used_regions] or regions

        _matcher = build_matcher(opts.matcher_backend)
        fallback = _matcher.match(
            image=image,
            dialogues=fallback_dlgs,
            regions=candidate_regions,
            hint_bboxes=fallback_hints,
            source_language=source_lang,
            ocr_weight=opts.ocr_weight,
            spatial_weight=opts.spatial_weight,
            position_weight=opts.position_weight,
            min_score=opts.match_min_score,
        )
        for local_i, fb_match in fallback.items():
            orig_i = unresolved_indices[local_i]
            fb_match.dialogue_index = orig_i
            matches[orig_i] = fb_match

    direct   = sum(1 for i, m in matches.items() if m.total_score == 1.0)
    fallback_count = len(matches) - direct

    # ── orphaned regions: detected but claimed by no dialogue ────────────────
    # These are bubbles the VLM missed during analysis.
    # The detector is the ground truth for coverage.
    claimed_region_ids = {
        int(dialogues[i].get("region_id", 0))
        for i in matches
        if dialogues[i].get("region_id") is not None
    }
    orphaned_regions: list[dict] = [
        r for r in saved_detections.values()
        if r["id"] not in claimed_region_ids
        and r["label"] in ("bubble", "text_bubble", "text_free")
    ] if saved_detections else []

    if orphaned_regions:
        print(
            f"  [match] WARNING: {len(orphaned_regions)} orphaned regions "
            f"(detected but not claimed by any dialogue) — VLM may have missed bubbles: "
            f"{[r['id'] for r in orphaned_regions]}",
            file=sys.stderr,
        )

    print(
        f"  p{page_num}: {len(saved_detections) if saved_detections else len(regions)} detected, "
        f"{len(matches)}/{len(dialogues)} matched "
        f"({direct} direct, {fallback_count} fallback, "
        f"{len(orphaned_regions)} orphaned)",
        file=sys.stderr,
    )

    # ── debug S2+S3 ──────────────────────────────────────────────────────────
    if opts.save_debug:
        # S2: show saved detections if available, else fresh regions
        debug_regions = [region_from_detection(d, img_w, img_h) for d in saved_detections.values()] if saved_detections else regions
        _save_debug_s2(image, debug_regions, debug_dir, page_num)
        _save_debug_s3(image, debug_regions, matches, hint_bboxes, debug_dir, page_num)

    # ── S4: inpaint matched regions ──────────────────────────────────────────
    inpainted = image.copy()
    combined_mask = np.zeros((img_h, img_w), dtype=np.uint8)

    for i, match in matches.items():
        text_mask = build_text_mask(inpainted, match.region.bbox, match.region.mask)
        combined_mask = np.maximum(combined_mask, text_mask)

    mask_pixels  = int(combined_mask.sum() // 255)
    total_pixels = img_w * img_h
    mask_coverage_pct = round(mask_pixels / total_pixels * 100, 2)
    inpainter_used = opts.inpainter_backend

    if combined_mask.sum() > 0:
        # resolve "auto" to actual backend name for the log
        from .stages.inpainting import build_inpainter as _bi, lama_available as _la
        if opts.inpainter_backend == "auto":
            inpainter_used = "lama" if _la() else "opencv"
        inpainted = _bi(opts.inpainter_backend).inpaint(inpainted, combined_mask)

    if opts.save_debug:
        inpainted.save(debug_dir / f"p{page_num:02d}_s4_inpainted.jpg", quality=88)

    # ── S5: render translated text ────────────────────────────────────────────
    result: Image.Image = inpainted.copy()
    render_events: list[dict] = []

    for i, match in matches.items():
        dlg = dialogues[i]
        raw_text = (
            dlg.get("text_translated") if opts.use_translation and dlg.get("text_translated")
            else dlg.get("text", "")
        ) or ""

        if not raw_text.strip():
            render_events.append({
                "dialogue_index": i,
                "region_id": dlg.get("region_id"),
                "text": raw_text,
                "status": "skip",
                "skip_reason": "empty_text",
            })
            continue

        rendered_img, rr = build_renderer(opts.renderer_backend).render(
            image=result,
            bbox=match.region.bbox,
            text=raw_text,
            tone=dlg.get("tone", "neutral"),
            bubble_type=dlg.get("bubble_type", "speech"),
            font_style=dlg.get("font_style"),
            source_language=source_lang,
            padding=opts.padding,
            min_font_size=opts.min_font_size,
            max_font_size=opts.max_font_size,
        )
        result = rendered_img
        ev = rr.to_dict()
        ev["dialogue_index"] = i
        ev["region_id"] = dlg.get("region_id")
        ev["tone"] = dlg.get("tone", "neutral")
        ev["bubble_type"] = dlg.get("bubble_type", "speech")
        render_events.append(ev)

    # ── debug S5: final image + render log ────────────────────────────────────
    ok = sum(1 for e in render_events if e.get("status") == "ok")
    skipped = sum(1 for e in render_events if e.get("status") == "skip")
    print(f"  [render] p{page_num}: {ok} rendered, {skipped} skipped", file=sys.stderr)

    # OCR orphaned regions so the log shows what text was missed
    _orphaned_with_ocr: list[dict] = []
    if opts.save_debug and orphaned_regions:
        try:
            from .stages.matching.ocr import ocr_region as _ocr_fn
            for _r in orphaned_regions:
                _reg = region_from_detection(_r, img_w, img_h)
                try:
                    _ocr = _ocr_fn(image, _reg.bbox, source_lang)
                except Exception:
                    _ocr = None
                _orphaned_with_ocr.append({
                    "region_id": _r["id"],
                    "label": _r["label"],
                    "bbox": [_r["x1"], _r["y1"], _r["x2"], _r["y2"]],
                    "size": [_r["x2"]-_r["x1"], _r["y2"]-_r["y1"]],
                    "score": round(_r["score"], 3),
                    "ocr_text": _ocr or None,
                    "issue": "VLM missed this bubble during analysis",
                })
        except Exception as _e:
            print(f"  [match] orphan OCR error: {_e}", file=sys.stderr)

    if opts.save_debug:
        result.save(debug_dir / f"p{page_num:02d}_s5_final.jpg", quality=88)
        import json as _json

        # S3 match data — actual values per dialogue
        match_events = []
        for i, m in matches.items():
            dlg = dialogues[i]
            match_events.append({
                "dialogue_index": i,
                "region_id": dlg.get("region_id"),
                "match_type": "direct" if m.total_score == 1.0 else "fallback",
                "region": {
                    "x1": m.region.x1, "y1": m.region.y1,
                    "x2": m.region.x2, "y2": m.region.y2,
                    "label": m.region.label, "score": round(m.region.score, 3),
                },
                "scores": {
                    "spatial": round(m.spatial_score, 3),
                    "text":    round(m.text_score, 3),
                    "position": round(m.position_score, 3),
                    "total":   round(m.total_score, 3),
                },
                "ocr_text": m.ocr_text or None,
                "dialogue_text": dlg.get("text", "")[:60],
            })

        unmatched_dlgs = [
            {"dialogue_index": i, "text": dialogues[i].get("text", "")[:60]}
            for i in range(len(dialogues)) if i not in matches
        ]

        (debug_dir / f"p{page_num:02d}_render_log.json").write_text(
            _json.dumps({
                "page_number": page_num,
                "image_size": {"w": img_w, "h": img_h},
                # S2 detections — actual values
                "s2_detection": {
                    "regions_found": len(saved_detections) if saved_detections else len(regions),
                    "source": "saved" if saved_detections else "fresh",
                    "regions": [
                        {
                            "id": r["id"], "label": r["label"],
                            "score": r["score"],
                            "bbox": [r["x1"], r["y1"], r["x2"], r["y2"]],
                            "size": [r["x2"]-r["x1"], r["y2"]-r["y1"]],
                        }
                        for r in saved_detections.values()
                    ] if saved_detections else [],
                },
                # S3 matching — actual values
                "s3_matching": {
                    "total_dialogues": len(dialogues),
                    "matched": len(matches),
                    "unmatched_dialogues": len(dialogues) - len(matches),
                    "direct": sum(1 for m in matches.values() if m.total_score == 1.0),
                    "fallback": sum(1 for m in matches.values() if m.total_score < 1.0),
                    "orphaned_regions": len(orphaned_regions),
                    "matches": match_events,
                    "unmatched": unmatched_dlgs,
                    "orphaned": _orphaned_with_ocr,
                },
                # S4 inpainting — actual values
                "s4_inpainting": {
                    "backend": inpainter_used,
                    "mask_pixels": mask_pixels,
                    "total_pixels": total_pixels,
                    "coverage_pct": mask_coverage_pct,
                    "skipped": mask_pixels == 0,
                },
                # S5 rendering — actual values
                "s5_rendering": {
                    "ok": ok,
                    "skipped": skipped,
                    "renders": render_events,
                },
            }, indent=2, ensure_ascii=False)
        )

    result.save(output_path, quality=95)

    return {
        "output": str(output_path),
        "regions_detected": len(saved_detections) if saved_detections else len(regions),
        "matched": len(matches),
        "unmatched": len(dialogues) - len(matches),
        "renders_ok": ok,
        "renders_skipped": skipped,
        "debug_dir": str(debug_dir) if opts.save_debug else None,
    }


# ── debug visualizations ──────────────────────────────────────────────────────

def _norm_bbox(b: tuple | list) -> tuple[int, int, int, int]:
    """Ensure x1<=x2, y1<=y2."""
    x1, y1, x2, y2 = b
    return (min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2))


def _save_debug_s2(
    image: Image.Image,
    regions: list[TextRegion],
    debug_dir: Path,
    page_num,
) -> None:
    """S2: show all detected regions."""
    overlay = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(overlay)

    colors = {
        "bubble":  (100, 180, 255, 60),
        "text":    (255, 200, 50, 60),
        "sfx":     (255, 80, 80, 60),
        "caption": (180, 255, 100, 60),
    }

    for r in regions:
        color = colors.get(r.label, (200, 200, 200, 50))
        border = tuple(min(255, c + 100) for c in color[:3]) + (200,)  # type: ignore
        draw.rectangle(_norm_bbox([r.x1, r.y1, r.x2, r.y2]), fill=color, outline=border, width=2)
        draw.text((r.x1 + 3, r.y1 + 2), f"{r.label} {r.score:.2f}", fill=(0, 0, 0, 220))

    Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(
        debug_dir / f"p{page_num:02d}_s2_detection.jpg", quality=88
    )


def _save_debug_s3(
    image: Image.Image,
    regions: list[TextRegion],
    matches: dict[int, MatchResult],
    hints: list[tuple[int, int, int, int]],
    debug_dir: Path,
    page_num,
) -> None:
    """S3: show matched regions + VLM hints."""
    overlay = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(overlay)

    matched_ids = {id(m.region) for m in matches.values()}

    # unmatched detected regions: gray
    for r in regions:
        if id(r) not in matched_ids:
            draw.rectangle(_norm_bbox([r.x1, r.y1, r.x2, r.y2]), outline=(150, 150, 150, 150), width=1)

    # matched: green fill + dialogue number
    for dlg_i, match in matches.items():
        r = match.region
        draw.rectangle(_norm_bbox([r.x1, r.y1, r.x2, r.y2]), fill=(0, 220, 100, 60), outline=(0, 180, 80, 200), width=2)
        draw.text((r.x1 + 4, r.y1 + 3), str(dlg_i + 1), fill=(200, 0, 0, 255))

    # VLM hints: dashed orange border
    for i, hint in enumerate(hints):
        draw.rectangle(_norm_bbox(hint), outline=(255, 140, 0, 180), width=2)
        draw.text((hint[0] + 3, hint[1] + 3), f"hint {i+1}", fill=(255, 140, 0, 220))

    Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(
        debug_dir / f"p{page_num:02d}_s3_matching.jpg", quality=88
    )


# ── coordinate helpers ────────────────────────────────────────────────────────

def _to_pixel_bbox(
    bbox: list,
    img_w: int, img_h: int,
    analysis_w: int, analysis_h: int,
) -> tuple[int, int, int, int]:
    if not bbox or len(bbox) < 4:
        return (0, 0, img_w, img_h)
    x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    if all(v <= 2.0 for v in [x1, y1, x2, y2]):
        return (int(x1*img_w), int(y1*img_h), int(x2*img_w), int(y2*img_h))
    if analysis_w > 0 and analysis_h > 0:
        sx, sy = img_w / analysis_w, img_h / analysis_h
        return (max(0,int(x1*sx)), max(0,int(y1*sy)), min(img_w,int(x2*sx)), min(img_h,int(y2*sy)))
    return (max(0,min(img_w,int(x1))), max(0,min(img_h,int(y1))), max(0,min(img_w,int(x2))), max(0,min(img_h,int(y2))))


# ── run-level orchestration ───────────────────────────────────────────────────

def typeset_run(
    pages_dir: Path,
    output_dir: Path,
    analyses_file: Path,
    options: TypesetOptions | None = None,
    on_progress: Callable[[dict], None] | None = None,
    source_language: str = "auto",   # passed from run meta
) -> list[Path]:
    opts = options or TypesetOptions()
    analyses: list[dict] = json.loads(analyses_file.read_text())

    supported = {".jpg", ".jpeg", ".png", ".webp"}
    page_files = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in supported)
    page_map = {i + 1: p for i, p in enumerate(page_files)}

    typeset_dir = output_dir / "typeset"
    typeset_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    _emit(on_progress, {"type": "typeset_start", "total": len(analyses)})

    for analysis in sorted(analyses, key=lambda a: a.get("page_number", 0)):
        # inject run-level source_language if not already in analysis
        if "source_language" not in analysis:
            analysis["source_language"] = source_language
        page_num = analysis.get("page_number", 0)
        page_path = page_map.get(page_num)
        if not page_path:
            continue

        _emit(on_progress, {"type": "typeset_page_start", "page": page_num, "filename": page_path.name})

        try:
            out_path = typeset_dir / page_path.name
            r = typeset_page(page_path, analysis, opts, out_path, output_dir=output_dir)
            results.append(out_path)
            _emit(on_progress, {
                "type": "typeset_page_done", "page": page_num,
                "regions_detected": r["regions_detected"],
                "matched": r["matched"], "unmatched": r["unmatched"],
            })
        except Exception as e:
            print(f"  typeset error p{page_num}: {e}", file=sys.stderr)
            _emit(on_progress, {"type": "typeset_page_error", "page": page_num, "error": str(e)})

    _emit(on_progress, {"type": "typeset_done", "processed": len(results), "total": len(analyses)})
    return results


def _emit(fn, ev):
    if fn:
        try: fn(ev)
        except: pass


# ── Per-stage typeset runners ─────────────────────────────────────────────────

def run_matching_stage(
    pages_dir: Path,
    output_dir: Path,
    analyses_file: Path,
    options: "TypesetOptions | None" = None,
    on_progress: "Callable[[dict], None] | None" = None,
    source_language: str = "auto",
) -> int:
    """
    Run only S3 (matching) for all pages.
    Saves match data to render_log.json per page.
    Returns number of pages processed.
    """
    import json as _json
    from PIL import Image as _PIL
    from core.annotator import load_detections

    opts = options or TypesetOptions()
    analyses: list[dict] = _json.loads(analyses_file.read_text())
    supported = {".jpg", ".jpeg", ".png", ".webp"}
    page_files = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in supported)
    page_map = {i + 1: p for i, p in enumerate(page_files)}

    typeset_dir = output_dir / "typeset"
    typeset_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = typeset_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    _emit(on_progress, {"type": "typeset_start", "total": len(analyses), "stage": "matching"})
    done = 0

    for analysis in sorted(analyses, key=lambda a: a.get("page_number", 0)):
        if "source_language" not in analysis:
            analysis["source_language"] = source_language
        page_num = analysis.get("page_number", 0)
        page_path = page_map.get(page_num)
        if not page_path:
            continue
        _emit(on_progress, {"type": "typeset_page_start", "page": page_num, "filename": page_path.name})
        try:
            image = _PIL.open(page_path).convert("RGB")
            img_w, img_h = image.size
            saved_detections = load_detections(output_dir, page_num)

            dialogues = analysis.get("dialogues", [])
            source_lang = analysis.get("source_language", source_language)
            matches, unresolved_indices, hint_bboxes, debug_regions = _build_matches(
                dialogues, saved_detections, img_w, img_h
            )
            if unresolved_indices:
                from .stages.detection import build_detector, TextRegion
                from .stages.matching import build_matcher
                candidate_regions = [
                    region_from_detection(r, img_w, img_h)
                    for r in saved_detections.values()
                ]
                fallback_dlgs  = [dialogues[i] for i in unresolved_indices]
                fallback_hints = [hint_bboxes[i] for i in unresolved_indices]
                used = {id(m.region) for m in matches.values()}
                candidates = [r for r in candidate_regions if id(r) not in used] or candidate_regions
                fb = build_matcher(opts.matcher_backend).match(
                    image=image, dialogues=fallback_dlgs, regions=candidates,
                    hint_bboxes=fallback_hints, source_language=source_lang,
                    ocr_weight=opts.ocr_weight, spatial_weight=opts.spatial_weight,
                    position_weight=opts.position_weight, min_score=opts.match_min_score,
                )
                for local_i, fb_match in fb.items():
                    orig_i = unresolved_indices[local_i]
                    fb_match.dialogue_index = orig_i
                    matches[orig_i] = fb_match

            _save_matching_log(matches, dialogues, saved_detections, debug_dir, page_num, img_w, img_h)

            # Save S2 + S3 debug images so they appear in the UI
            if opts.save_debug:
                from core.annotator import annotate_from_detections as _ann
                tr_regions = [region_from_detection(r, img_w, img_h) for r in saved_detections.values()]
                # S2: annotated image with numbered boxes (what VLM received)
                ann_result = _ann(image, list(saved_detections.values()))
                ann_result.annotated_image.save(
                    str(debug_dir / f"p{page_num:02d}_s2_detection.jpg"), quality=88
                )
                # S3: matching visualization
                hint_bboxes_debug: list = []
                _save_debug_s3(image, tr_regions, matches, hint_bboxes_debug, debug_dir, page_num)

            done += 1
            _emit(on_progress, {"type": "typeset_page_done", "page": page_num,
                                "matched": len(matches), "stage": "matching"})
        except Exception as e:
            import traceback as _tb
            print(f"  [matching] p{page_num}: {e}\n{_tb.format_exc()}", file=sys.stderr)
            _emit(on_progress, {"type": "typeset_page_error", "page": page_num, "error": str(e)})

    _emit(on_progress, {"type": "typeset_done", "processed": done, "total": len(analyses), "stage": "matching"})
    return done


def run_inpainting_stage(
    pages_dir: Path,
    output_dir: Path,
    options: "TypesetOptions | None" = None,
    on_progress: "Callable[[dict], None] | None" = None,
) -> int:
    """
    Run only S4 (inpainting) for all pages.
    Reads match data from render_log.json, saves s4_inpainted.jpg.
    """
    import json as _json
    from PIL import Image as _PIL

    opts = options or TypesetOptions()
    supported = {".jpg", ".jpeg", ".png", ".webp"}
    page_files = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in supported)

    typeset_dir = output_dir / "typeset"
    debug_dir   = typeset_dir / "debug"
    if not debug_dir.exists():
        raise RuntimeError("Run matching stage first")

    _emit(on_progress, {"type": "typeset_start", "total": len(page_files), "stage": "inpainting"})
    done = 0

    for i, page_path in enumerate(page_files, 1):
        _emit(on_progress, {"type": "typeset_page_start", "page": i, "filename": page_path.name})
        try:
            import numpy as np
            log_path = debug_dir / f"p{i:02d}_render_log.json"
            if not log_path.exists():
                _emit(on_progress, {"type": "typeset_page_error", "page": i, "error": "no match log — run matching first"})
                continue

            image = _PIL.open(page_path).convert("RGB")
            img_w, img_h = image.size

            # Check for refined mask
            refined_mask_f = debug_dir / f"p{i:02d}_mask_refined.png"
            if refined_mask_f.exists():
                from PIL import Image as _PIL2
                mask_img = _PIL2.open(refined_mask_f).convert("L").resize(image.size)
                combined_mask = np.array(mask_img)
            else:
                log = _json.loads(log_path.read_text())
                combined_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                from .stages.inpainting import build_text_mask
                for m in log.get("s3_matching", {}).get("matches", []):
                    r = m["region"]
                    tm = build_text_mask(image, (r["x1"], r["y1"], r["x2"], r["y2"]))
                    combined_mask = np.maximum(combined_mask, tm)

            mask_pixels = int(combined_mask.sum() // 255)
            if combined_mask.sum() > 0:
                from .stages.inpainting import build_inpainter
                inpainted = build_inpainter(opts.inpainter_backend).inpaint(image, combined_mask)
            else:
                inpainted = image.copy()

            inpainted.save(str(debug_dir / f"p{i:02d}_s4_inpainted.jpg"), quality=88)

            # Update log
            if log_path.exists():
                log = _json.loads(log_path.read_text())
                log["s4_inpainting"] = {
                    "backend": opts.inpainter_backend,
                    "mask_pixels": mask_pixels,
                    "total_pixels": img_w * img_h,
                    "coverage_pct": round(mask_pixels / (img_w * img_h) * 100, 2),
                    "skipped": mask_pixels == 0,
                }
                log_path.write_text(_json.dumps(log, indent=2, ensure_ascii=False))

            done += 1
            _emit(on_progress, {"type": "typeset_page_done", "page": i, "stage": "inpainting",
                                "mask_pixels": mask_pixels})
        except Exception as e:
            import traceback as _tb
            print(f"  [inpainting] p{i}: {e}\n{_tb.format_exc()}", file=sys.stderr)
            _emit(on_progress, {"type": "typeset_page_error", "page": i, "error": str(e)})

    _emit(on_progress, {"type": "typeset_done", "processed": done, "total": len(page_files), "stage": "inpainting"})
    return done


def run_rendering_stage(
    pages_dir: Path,
    output_dir: Path,
    analyses_file: Path,
    options: "TypesetOptions | None" = None,
    on_progress: "Callable[[dict], None] | None" = None,
    source_language: str = "auto",
) -> int:
    """
    Run only S5 (rendering) for all pages.
    Reads matches + inpainted images from debug dir, writes final typeset output.
    """
    import json as _json
    from PIL import Image as _PIL

    opts = options or TypesetOptions()
    analyses: list[dict] = _json.loads(analyses_file.read_text())
    supported = {".jpg", ".jpeg", ".png", ".webp"}
    page_files = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in supported)
    page_map = {i + 1: p for i, p in enumerate(page_files)}

    typeset_dir = output_dir / "typeset"
    debug_dir   = typeset_dir / "debug"
    typeset_dir.mkdir(parents=True, exist_ok=True)

    _emit(on_progress, {"type": "typeset_start", "total": len(analyses), "stage": "rendering"})
    done = 0

    for analysis in sorted(analyses, key=lambda a: a.get("page_number", 0)):
        if "source_language" not in analysis:
            analysis["source_language"] = source_language
        page_num = analysis.get("page_number", 0)
        page_path = page_map.get(page_num)
        if not page_path:
            continue
        _emit(on_progress, {"type": "typeset_page_start", "page": page_num, "filename": page_path.name})
        try:
            inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
            if not inpainted_path.exists():
                _emit(on_progress, {"type": "typeset_page_error", "page": page_num, "error": "no inpainted image — run inpainting first"})
                continue

            inpainted = _PIL.open(inpainted_path).convert("RGB")
            log_path  = debug_dir / f"p{page_num:02d}_render_log.json"
            if not log_path.exists():
                _emit(on_progress, {"type": "typeset_page_error", "page": page_num, "error": "no match log — run matching first"})
                continue

            log = _json.loads(log_path.read_text())
            matches_data = log.get("s3_matching", {}).get("matches", [])
            dialogues    = analysis.get("dialogues", [])
            source_lang  = analysis.get("source_language", source_language)

            # Load render overrides if exist
            overrides_f = debug_dir / f"p{page_num:02d}_render_overrides.json"
            overrides   = {o["dialogue_index"]: o for o in (_json.loads(overrides_f.read_text()) if overrides_f.exists() else [])}

            from .stages.rendering import build_renderer
            renderer     = build_renderer(opts.renderer_backend)
            result       = inpainted.copy()
            render_events: list[dict] = []
            ok = skipped = 0

            for m in matches_data:
                dlg_i = m["dialogue_index"]
                ovr   = overrides.get(dlg_i, {})
                if ovr.get("skip"):
                    render_events.append({"dialogue_index": dlg_i, "status": "skip", "skip_reason": "override"})
                    skipped += 1
                    continue

                dlg  = dialogues[dlg_i] if dlg_i < len(dialogues) else {}
                text = ovr.get("text_translated") or dlg.get("text_translated") or dlg.get("text", "")
                if not text:
                    continue
                if opts.skip_sfx and dlg.get("bubble_type") == "sfx":
                    skipped += 1; continue
                if opts.skip_narration and dlg.get("bubble_type") == "narration":
                    skipped += 1; continue

                r    = m["region"]
                bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
                rendered, rr = renderer.render(
                    image=result, bbox=bbox, text=text,
                    tone=ovr.get("tone") or dlg.get("tone", "neutral"),
                    bubble_type=dlg.get("bubble_type", "speech"),
                    font_style=ovr.get("font_style") or dlg.get("font_style"),
                    source_language=source_lang,
                    padding=opts.padding, min_font_size=opts.min_font_size,
                    max_font_size=ovr.get("font_size_override") or opts.max_font_size,
                )
                if rr.status == "ok":
                    result = rendered
                    ok += 1
                else:
                    skipped += 1
                render_events.append({"dialogue_index": dlg_i, "region_id": m.get("region_id"),
                                      "text": text, "status": rr.status, "skip_reason": rr.skip_reason,
                                      "font_size": rr.font_size, "font_style": rr.font_style,
                                      "lines": rr.lines, "tone": dlg.get("tone"), "bbox": list(bbox)})

            out_path = typeset_dir / page_path.name
            result.save(str(out_path), quality=95)
            result.save(str(debug_dir / f"p{page_num:02d}_s5_final.jpg"), quality=88)

            # Update log
            log["s5_rendering"] = {"ok": ok, "skipped": skipped, "renders": render_events}
            log_path.write_text(_json.dumps(log, indent=2, ensure_ascii=False))

            done += 1
            _emit(on_progress, {"type": "typeset_page_done", "page": page_num, "stage": "rendering",
                                "renders_ok": ok, "renders_skipped": skipped})
        except Exception as e:
            import traceback as _tb
            print(f"  [rendering] p{page_num}: {e}\n{_tb.format_exc()}", file=sys.stderr)
            _emit(on_progress, {"type": "typeset_page_error", "page": page_num, "error": str(e)})

    _emit(on_progress, {"type": "typeset_done", "processed": done, "total": len(analyses), "stage": "rendering"})
    return done


def _build_matches(dialogues, saved_detections, img_w, img_h):
    """Extract direct matches from dialogues, return (matches, unresolved, hints, debug_regions)."""
    from .stages.matching import MatchResult
    matches = {}
    unresolved_indices = []
    hint_bboxes = []
    for i, dlg in enumerate(dialogues):
        rid = dlg.get("region_id")
        if rid is not None and int(rid) in saved_detections:
            region = region_from_detection(saved_detections[int(rid)], img_w, img_h)
            matches[i] = MatchResult(dialogue_index=i, region=region,
                                     spatial_score=1.0, text_score=1.0,
                                     position_score=1.0, total_score=1.0)
        else:
            unresolved_indices.append(i)
            bx = dlg.get("bbox")
            hint_bboxes.append(tuple(bx) if bx and len(bx) == 4 else None)
    debug_regions = list(saved_detections.values())
    return matches, unresolved_indices, hint_bboxes, debug_regions


def _save_matching_log(matches, dialogues, saved_detections, debug_dir, page_num, img_w, img_h):
    """Save matching results to render_log.json, creating or updating the file."""
    import json as _json
    log_path = debug_dir / f"p{page_num:02d}_render_log.json"
    if log_path.exists():
        log = _json.loads(log_path.read_text())
    else:
        log = {"page_number": page_num, "image_size": {"w": img_w, "h": img_h},
               "s2_detection": {"regions_found": len(saved_detections), "source": "saved",
                                "regions": [{"id": r["id"], "label": r["label"], "score": r["score"],
                                             "bbox": [r["x1"],r["y1"],r["x2"],r["y2"]],
                                             "size": [r["x2"]-r["x1"],r["y2"]-r["y1"]]}
                                            for r in saved_detections.values()]}}
    match_events = []
    for i, m in matches.items():
        dlg = dialogues[i]
        match_events.append({
            "dialogue_index": i, "region_id": dlg.get("region_id"),
            "match_type": "direct" if m.total_score == 1.0 else "fallback",
            "region": {"x1": m.region.x1, "y1": m.region.y1, "x2": m.region.x2, "y2": m.region.y2,
                       "label": m.region.label, "score": round(m.region.score, 3)},
            "scores": {"spatial": round(m.spatial_score, 3), "text": round(m.text_score, 3),
                       "position": round(m.position_score, 3), "total": round(m.total_score, 3)},
            "ocr_text": getattr(m, "ocr_text", None),
            "dialogue_text": dlg.get("text", "")[:60],
        })
    direct = sum(1 for m in matches.values() if m.total_score == 1.0)
    log["s3_matching"] = {
        "total_dialogues": len(dialogues), "matched": len(matches),
        "unmatched_dialogues": len(dialogues) - len(matches),
        "direct": direct, "fallback": len(matches) - direct, "orphaned_regions": 0,
        "matches": match_events, "unmatched": [], "orphaned": [],
    }
    log_path.write_text(_json.dumps(log, indent=2, ensure_ascii=False))