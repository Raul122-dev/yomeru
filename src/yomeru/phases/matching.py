"""
Phase 3: Matching — Map detected regions to analysis dialogues.

Input:  output/page_detections.json + output/page_analyses.json + source images
Output: output/typeset/debug/pXX_render_log.json (with s2_detection + s3_matching data)
"""
from __future__ import annotations

import sys
import time

from PIL import Image

from yomeru.core.runs import Run
from yomeru.phases import PageResult, PhaseResult, ProgressCallback, null_progress

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """
    Match detected regions to dialogues for each page.

    Options:
        backend: matching backend name (yomeru/plugins/matching.py)
        backend_options: dict validated by that backend's options model
        comic_format: reading direction for the reading-order fallback
    """
    from yomeru.plugins import get_backend

    comic_format = options.get("comic_format", "auto")
    spec, backend = get_backend("matching", options.get("backend", "cascade"), options.get("backend_options"))

    from yomeru.core import artifacts

    # Effective inputs: active detections, analyses merged with user edits
    detections = artifacts.load_detections(run)
    analyses = artifacts.load_analyses(run)
    all_pages = artifacts.page_files(run)

    if page_scope:
        analyses = [a for a in analyses if a.get("page_number") in page_scope]

    total = len(analyses)
    on_progress({"type": "phase_progress", "phase": "matching", "total": total, "processed": 0})
    print(f"\n[matching] {total} pages, backend={spec.name}", file=sys.stderr)

    debug_dir = artifacts.debug_dir(run, create=True)

    page_map = {i: p for i, p in all_pages}
    results: list[PageResult] = []

    for analysis in sorted(analyses, key=lambda a: a.get("page_number", 0)):
        page_num = analysis.get("page_number", 0)
        page_path = page_map.get(page_num)
        if not page_path:
            continue

        on_progress({"type": "page_start", "phase": "matching", "page": page_num, "filename": page_path.name})
        t0 = time.time()

        try:
            img = Image.open(page_path).convert("RGB")
            img_w, img_h = img.size

            # Get page detections
            page_dets = detections.get(page_num, {})
            dialogues = analysis.get("dialogues", [])
            source_lang = analysis.get("source_language", "auto")
            analysis_w = int(analysis.get("analysis_image_w", 0))
            analysis_h = int(analysis.get("analysis_image_h", 0))

            from yomeru.core.contracts import MatchRequest
            res = backend.match_page(MatchRequest(
                image=img, detections=page_dets, dialogues=dialogues,
                source_language=source_lang, comic_format=comic_format,
                analysis_w=analysis_w, analysis_h=analysis_h,
            ))
            matches, orphaned = res.matches, res.orphaned
            if res.located:
                page_dets = _add_located_regions(run, page_num, res.located, page_dets)

            # Save matching log + debug image
            _save_match_log(run, matches, dialogues, page_dets, orphaned, page_num, img_w, img_h)
            _save_debug_image(img, matches, dialogues, page_dets, orphaned, debug_dir, page_num)

            elapsed = round(time.time() - t0, 2)
            direct = sum(1 for m in matches.values() if m.total_score == 1.0)
            rescued_count = res.rescued
            print(f"  p{page_num}: {len(matches)}/{len(dialogues)} matched "
                  f"({direct} direct, {rescued_count} rescued, "
                  f"{len(orphaned)} orphaned) [{elapsed}s]", file=sys.stderr)

            on_progress({
                "type": "page_done", "phase": "matching", "page": page_num,
                "matched": len(matches), "unmatched": len(dialogues) - len(matches),
                "orphaned": len(orphaned), "elapsed": elapsed,
            })
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=True))

        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            print(f"  p{page_num}: error — {e}", file=sys.stderr)
            on_progress({"type": "page_error", "phase": "matching", "page": page_num, "error": str(e)})
            results.append(PageResult(page_num=page_num, filename=page_path.name, success=False, error=str(e)))

    done = sum(1 for r in results if r.success)
    failed = [r.page_num for r in results if not r.success]
    status = "done" if not failed else ("partial" if done > 0 else "failed")
    print(f"[matching] done — {done}/{total} pages", file=sys.stderr)

    return PhaseResult(
        phase="matching", status=status, total_pages=total,
        processed_pages=done, failed_pages=failed, page_results=results,
    )


# Helpers live with the technique; re-exported for the API and tests.
from yomeru.lib.matching.cascade import (  # noqa: E402,F401
    _near, _region_from_det, _rescue_orphaned_text_regions, _right_to_left,
    _text_containment_score, _text_region_of, _to_pixel_bbox,
)


def _save_match_log(run, matches, dialogues, page_dets, orphaned, page_num, img_w, img_h):
    """Save matching results to render_log.json."""
    # Fallback matches carry the dialogue's (often null) region_id; resolve the
    # real detection id from the matched geometry so the editor shows it.
    def _real_region_id(reg) -> int | None:
        best, best_iou = None, 0.5
        for r in page_dets.values():
            ix = max(0, min(reg.x2, r["x2"]) - max(reg.x1, r["x1"]))
            iy = max(0, min(reg.y2, r["y2"]) - max(reg.y1, r["y1"]))
            inter = ix * iy
            union = (reg.x2 - reg.x1) * (reg.y2 - reg.y1) + (r["x2"] - r["x1"]) * (r["y2"] - r["y1"]) - inter
            iou = inter / union if union > 0 else 0
            if iou > best_iou:
                best, best_iou = r["id"], iou
        return best

    match_events = []
    for i, m in matches.items():
        dlg = dialogues[i]
        real_id = _real_region_id(m.region)
        match_events.append({
            "dialogue_index": i,
            "region_id": real_id if real_id is not None else dlg.get("region_id"),
            "match_type": "direct" if m.total_score == 1.0 else "fallback",
            "region": {
                "x1": m.region.x1, "y1": m.region.y1,
                "x2": m.region.x2, "y2": m.region.y2,
                "label": m.region.label, "score": round(m.region.score, 3),
            },
            "scores": {
                "spatial": round(m.spatial_score, 3),
                "text": round(m.text_score, 3),
                "total": round(m.total_score, 3),
            },
            "ocr_text": getattr(m, "ocr_text", None),
            "dialogue_text": dlg.get("text", "")[:60],
        })

    direct = sum(1 for m in matches.values() if m.total_score == 1.0)
    unmatched = [
        {"dialogue_index": i, "text": dialogues[i].get("text", "")[:60]}
        for i in range(len(dialogues)) if i not in matches and not dialogues[i].get("skip")
    ]

    log = {
        "page_number": page_num,
        "image_size": {"w": img_w, "h": img_h},
        "s2_detection": {
            "regions_found": len(page_dets),
            "source": "saved",
            "regions": [
                {"id": r["id"], "label": r["label"], "score": r["score"],
                 "bbox": [r["x1"], r["y1"], r["x2"], r["y2"]]}
                for r in page_dets.values()
            ],
        },
        "s3_matching": {
            "total_dialogues": len(dialogues),
            "matched": len(matches),
            "unmatched_dialogues": len(dialogues) - len(matches),
            "direct": direct,
            "fallback": len(matches) - direct,
            "orphaned_regions": len(orphaned),
            "matches": match_events,
            "unmatched": unmatched,
            "orphaned": [
                {"region_id": r["id"], "label": r["label"],
                 "bbox": [r["x1"], r["y1"], r["x2"], r["y2"]]}
                for r in orphaned
            ],
        },
    }

    # Re-running matching replaces the whole log: s4/s5 of the old matches are stale
    from yomeru.core import artifacts
    artifacts.write_render_log(run, page_num, log)


def _save_debug_image(img, matches, dialogues, page_dets, orphaned, debug_dir, page_num):
    """Generate a visual debug image showing matching results overlaid on the page."""
    from PIL import ImageDraw, ImageFont

    debug_img = img.copy()
    draw = ImageDraw.Draw(debug_img, "RGBA")

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font

    # Colors
    COLOR_MATCHED_DIRECT = (34, 197, 94, 100)    # green fill
    COLOR_MATCHED_FALLBACK = (251, 191, 36, 100)  # yellow fill
    COLOR_ORPHANED = (239, 68, 68, 80)           # red fill
    BORDER_MATCHED = (34, 197, 94, 220)
    BORDER_FALLBACK = (251, 191, 36, 220)
    BORDER_ORPHANED = (239, 68, 68, 180)

    # Draw orphaned regions first (background)
    for det in orphaned:
        x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
        draw.rectangle([x1, y1, x2, y2], fill=COLOR_ORPHANED, outline=BORDER_ORPHANED, width=2)
        draw.text((x1 + 3, y1 + 2), f"R{det['id']} orphan", fill=(239, 68, 68, 255), font=font_sm)

    # Draw matched regions
    for dlg_idx, match in matches.items():
        dlg = dialogues[dlg_idx]
        r = match.region
        is_direct = match.total_score == 1.0
        fill = COLOR_MATCHED_DIRECT if is_direct else COLOR_MATCHED_FALLBACK
        border = BORDER_MATCHED if is_direct else BORDER_FALLBACK

        draw.rectangle([r.x1, r.y1, r.x2, r.y2], fill=fill, outline=border, width=2)

        # Label with dialogue index and region id
        rid = dlg.get("region_id", "?")
        label = f"D{dlg_idx}→R{rid}" if is_direct else f"D{dlg_idx}→fb({match.total_score:.2f})"
        draw.text((r.x1 + 3, r.y1 + 2), label, fill=(255, 255, 255, 255), font=font)

        # Show truncated dialogue text
        text_preview = dlg.get("text", "")[:30]
        if text_preview:
            draw.text((r.x1 + 3, r.y2 - 16), text_preview, fill=(200, 200, 200, 220), font=font_sm)

    # Draw unmatched regions (detected but not in matches or orphaned)
    orphaned_ids = {det["id"] for det in orphaned}
    for det in page_dets.values():
        if det["id"] not in orphaned_ids:
            # Check if this region is matched
            region_matched = False
            for m in matches.values():
                if (m.region.x1 == det["x1"] and m.region.y1 == det["y1"]
                        and m.region.x2 == det["x2"] and m.region.y2 == det["y2"]):
                    region_matched = True
                    break
            if not region_matched:
                x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
                draw.rectangle([x1, y1, x2, y2], outline=(150, 150, 150, 120), width=1)

    # Save
    # Draw legend
    legend_y = 10
    legend_x = img.width - 220
    draw.rectangle([legend_x - 5, legend_y - 5, img.width - 5, legend_y + 75], fill=(0, 0, 0, 180))
    draw.rectangle([legend_x, legend_y, legend_x + 12, legend_y + 12], fill=COLOR_MATCHED_DIRECT, outline=BORDER_MATCHED)
    draw.text((legend_x + 16, legend_y - 1), "Direct match (VLM)", fill=(255, 255, 255), font=font_sm)
    draw.rectangle([legend_x, legend_y + 18, legend_x + 12, legend_y + 30], fill=COLOR_MATCHED_FALLBACK, outline=BORDER_FALLBACK)
    draw.text((legend_x + 16, legend_y + 17), "Fallback/Rescue match", fill=(255, 255, 255), font=font_sm)
    draw.rectangle([legend_x, legend_y + 36, legend_x + 12, legend_y + 48], fill=COLOR_ORPHANED, outline=BORDER_ORPHANED)
    draw.text((legend_x + 16, legend_y + 35), "Orphaned (no match)", fill=(255, 255, 255), font=font_sm)
    draw.rectangle([legend_x, legend_y + 54, legend_x + 12, legend_y + 66], outline=(150, 150, 150, 120), width=1)
    draw.text((legend_x + 16, legend_y + 53), "Unmatched (ignored)", fill=(180, 180, 180), font=font_sm)

    out_path = debug_dir / f"p{page_num:02d}_s3_matching.jpg"
    debug_img.convert("RGB").save(str(out_path), quality=85)


def _add_located_regions(run, page_num: int, located: list[dict], page_dets: dict) -> dict:
    """Regions the matcher found by OCR (the detector missed them) become real
    detections in the active detections file, so their id joins like any
    other (editors, inpainting, render). Re-running matching does not add
    duplicates: a region overlapping an existing one is not added again."""
    import json
    from yomeru.core import artifacts
    f = run.active_detections_file()
    data = json.loads(f.read_text())
    page = next(p for p in data if p["page_number"] == page_num)

    def same(a, b) -> bool:
        ix = max(0, min(a["x2"], b["x2"]) - max(a["x1"], b["x1"]))
        iy = max(0, min(a["y2"], b["y2"]) - max(a["y1"], b["y1"]))
        return ix * iy > 0.5 * (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    for det in located:
        if not any(same(det, r) for r in page["regions"]):
            page["regions"].append(det)
    tmp = artifacts.tmp_path(f)
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(f)
    return {r["id"]: r for r in page["regions"]}
