"""
Phase 3: Matching — Map detected regions to analysis dialogues.

Input:  output/page_detections.json + output/page_analyses.json + source images
Output: output/typeset/debug/pXX_render_log.json (with s2_detection + s3_matching data)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

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
        matcher_backend: str = "hungarian"
        ocr_weight: float = 0.4
        spatial_weight: float = 0.4
        position_weight: float = 0.2
        match_min_score: float = 0.05
    """
    from yomeru.lib.detection import TextRegion
    from yomeru.lib.matching import build_matcher, MatchResult

    meta = run.meta()
    matcher_backend = options.get("matcher_backend", "hungarian")
    ocr_weight = options.get("ocr_weight", 0.4)
    spatial_weight = options.get("spatial_weight", 0.4)
    position_weight = options.get("position_weight", 0.2)
    match_min_score = options.get("match_min_score", 0.05)

    output_dir = run.output_dir()
    pages_dir = run.pages_dir()

    # Load detections and analyses
    detections = _load_detections(run)
    analyses = _load_analyses(run)
    all_pages = _collect_pages(pages_dir)

    if page_scope:
        analyses = [a for a in analyses if a.get("page_number") in page_scope]

    total = len(analyses)
    on_progress({"type": "phase_progress", "phase": "matching", "total": total, "processed": 0})
    print(f"\n[matching] {total} pages, backend={matcher_backend}", file=sys.stderr)

    # Prepare output dirs
    typeset_dir = output_dir / "typeset"
    debug_dir = typeset_dir / "debug"
    typeset_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    page_map = {i: p for i, p in all_pages}
    results: list[PageResult] = []
    matcher = build_matcher(matcher_backend)

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

            # ── Step 1: Direct matching by region_id from VLM ────────────────
            matches: dict[int, MatchResult] = {}
            unresolved: list[int] = []

            for i, dlg in enumerate(dialogues):
                if dlg.get("skip"):
                    continue
                rid = dlg.get("region_id")
                if rid is not None and int(rid) in page_dets:
                    det = page_dets[int(rid)]
                    region = _region_from_det(det, img_w, img_h)
                    matches[i] = MatchResult(
                        dialogue_index=i, region=region,
                        spatial_score=1.0, text_score=1.0,
                        position_score=1.0, total_score=1.0,
                    )
                else:
                    unresolved.append(i)

            # ── Step 2: Validate VLM assignments (Capa 2) ────────────────────
            validation_issues = _validate_vlm_matches(
                matches, dialogues, page_dets, img, img_w, img_h,
                analysis_w, analysis_h, source_lang,
            )
            # Fix issues found by validator
            if validation_issues["reassignments"]:
                for dlg_idx, new_region_id in validation_issues["reassignments"].items():
                    det = page_dets[new_region_id]
                    region = _region_from_det(det, img_w, img_h)
                    matches[dlg_idx] = MatchResult(
                        dialogue_index=dlg_idx, region=region,
                        spatial_score=0.9, text_score=0.9,
                        position_score=0.9, total_score=0.9,
                    )
            if validation_issues["splits"]:
                for split in validation_issues["splits"]:
                    # A split means one dialogue was merged — we can't split the text
                    # but we can mark the orphaned region as needing attention
                    pass

            # ── Step 3: Fallback Hungarian for unresolved ────────────────────
            if unresolved:
                candidate_regions = [
                    _region_from_det(det, img_w, img_h)
                    for det in page_dets.values()
                    if det.get("label") in ("text_bubble", "text_free")
                ]
                used = {id(m.region) for m in matches.values()}
                candidates = [r for r in candidate_regions if id(r) not in used] or candidate_regions

                fallback_dlgs = [dialogues[i] for i in unresolved]
                fallback_hints = [
                    _to_pixel_bbox(dialogues[i].get("bbox", [0, 0, 0, 0]), img_w, img_h, analysis_w, analysis_h)
                    for i in unresolved
                ]

                fb_matches = matcher.match(
                    image=img, dialogues=fallback_dlgs, regions=candidates,
                    hint_bboxes=fallback_hints, source_language=source_lang,
                    ocr_weight=ocr_weight, spatial_weight=spatial_weight,
                    position_weight=position_weight, min_score=match_min_score,
                )
                for local_i, fb_match in fb_matches.items():
                    orig_i = unresolved[local_i]
                    fb_match.dialogue_index = orig_i
                    matches[orig_i] = fb_match

            # ── Step 4: Identify orphaned regions ────────────────────────────
            claimed_ids = {
                int(dialogues[i].get("region_id", 0))
                for i in matches if dialogues[i].get("region_id") is not None
            }
            # Also count fallback-matched regions as claimed
            for m in matches.values():
                for det_id, det in page_dets.items():
                    if (m.region.x1 == det["x1"] and m.region.y1 == det["y1"]
                            and m.region.x2 == det["x2"] and m.region.y2 == det["y2"]):
                        claimed_ids.add(det_id)

            orphaned = [
                r for r in page_dets.values()
                if r["id"] not in claimed_ids and r.get("label") in ("bubble", "text_bubble", "text_free")
            ]

            # ── Step 5: Rescue orphaned text_bubble regions (Capa 3) ─────────
            orphaned_text = [r for r in orphaned if r.get("label") in ("text_bubble", "text_free")]
            if orphaned_text:
                rescued = _rescue_orphaned_text_regions(
                    orphaned_text, matches, dialogues, img, source_lang,
                    matcher, ocr_weight, spatial_weight, position_weight, match_min_score,
                )
                if rescued:
                    # Add rescued matches and remove from orphaned
                    rescued_ids = set()
                    for dlg_idx, match_result in rescued.items():
                        matches[dlg_idx] = match_result
                        for det_id, det in page_dets.items():
                            if (match_result.region.x1 == det["x1"] and match_result.region.y1 == det["y1"]
                                    and match_result.region.x2 == det["x2"] and match_result.region.y2 == det["y2"]):
                                rescued_ids.add(det_id)
                    orphaned = [r for r in orphaned if r["id"] not in rescued_ids]

            # Save matching log + debug image
            _save_match_log(matches, dialogues, page_dets, orphaned, debug_dir, page_num, img_w, img_h)
            _save_debug_image(img, matches, dialogues, page_dets, orphaned, debug_dir, page_num)

            elapsed = round(time.time() - t0, 2)
            direct = sum(1 for m in matches.values() if m.total_score == 1.0)
            validated = len(validation_issues.get("reassignments", {}))
            rescued_count = len(rescued) if orphaned_text else 0
            print(f"  p{page_num}: {len(matches)}/{len(dialogues)} matched "
                  f"({direct} direct, {validated} validated, {rescued_count} rescued, "
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_detections(run: Run) -> dict[int, dict[int, dict]]:
    """Load detections as {page_num: {region_id: region_dict}}."""
    det_file = run.active_detections_file()
    if not det_file.exists():
        return {}
    data = json.loads(det_file.read_text())
    result = {}
    for entry in data:
        page_num = entry["page_number"]
        result[page_num] = {r["id"]: r for r in entry["regions"]}
    return result


def _load_analyses(run: Run) -> list[dict]:
    """Load analyses from the active analyses file, merged with user edits."""
    f = run.active_analyses_file()
    if not f.exists():
        return []
    original = json.loads(f.read_text())
    from yomeru.core.annotations import AnnotationStore
    store = AnnotationStore(run.output_dir())
    return store.merged_analyses(original)


def _collect_pages(folder: Path) -> list[tuple[int, Path]]:
    pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    return [(i, p) for i, p in enumerate(pages, 1)]


def _region_from_det(det: dict, img_w: int, img_h: int):
    """Build a TextRegion from a saved detection dict."""
    from yomeru.lib.detection import TextRegion
    return TextRegion(
        x1=max(0, min(img_w, int(det["x1"]))),
        y1=max(0, min(img_h, int(det["y1"]))),
        x2=max(0, min(img_w, int(det["x2"]))),
        y2=max(0, min(img_h, int(det["y2"]))),
        label=det.get("label", "bubble"),
        score=float(det.get("score", 1.0)),
        mask=None,
    )


def _to_pixel_bbox(bbox, img_w, img_h, analysis_w, analysis_h):
    """Convert bbox from analysis coordinates to pixel coordinates."""
    if not bbox or len(bbox) < 4:
        return (0, 0, img_w, img_h)
    x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    if all(v <= 2.0 for v in [x1, y1, x2, y2]):
        return (int(x1 * img_w), int(y1 * img_h), int(x2 * img_w), int(y2 * img_h))
    if analysis_w > 0 and analysis_h > 0:
        sx, sy = img_w / analysis_w, img_h / analysis_h
        return (max(0, int(x1 * sx)), max(0, int(y1 * sy)), min(img_w, int(x2 * sx)), min(img_h, int(y2 * sy)))
    return (max(0, int(x1)), max(0, int(y1)), min(img_w, int(x2)), min(img_h, int(y2)))


# ── Capa 2: Post-VLM Validator ─────────────────────────────────────────────────

def _validate_vlm_matches(
    matches: dict,
    dialogues: list[dict],
    page_dets: dict[int, dict],
    img: "Image.Image",
    img_w: int, img_h: int,
    analysis_w: int, analysis_h: int,
    source_lang: str,
) -> dict:
    """
    Validate VLM region assignments and detect issues:
    1. Duplicate assignments (two dialogues → same region)
    2. Spatial mismatch (dialogue bbox far from assigned region)
    3. Unclaimed text_bubble regions that should have matches
    4. Potential text merges (one dialogue text suspiciously long for its region)
    
    Returns dict with:
      - reassignments: {dlg_idx: new_region_id} for corrections
      - splits: list of suspected text merges
      - warnings: list of warning strings
    """
    result = {"reassignments": {}, "splits": [], "warnings": []}

    # Check 1: Duplicate region assignments
    region_to_dlg: dict[int, list[int]] = {}
    for dlg_idx, match in matches.items():
        rid = dialogues[dlg_idx].get("region_id")
        if rid is not None:
            region_to_dlg.setdefault(int(rid), []).append(dlg_idx)

    for rid, dlg_indices in region_to_dlg.items():
        if len(dlg_indices) > 1:
            result["warnings"].append(
                f"Region {rid} claimed by multiple dialogues: {dlg_indices}"
            )

    # Check 2: Unclaimed text_bubble/text_free regions
    claimed_region_ids = set()
    for dlg_idx in matches:
        rid = dialogues[dlg_idx].get("region_id")
        if rid is not None:
            claimed_region_ids.add(int(rid))

    unclaimed_text_regions = [
        r for r in page_dets.values()
        if r["id"] not in claimed_region_ids
        and r.get("label") in ("text_bubble", "text_free")
    ]

    # Check 3: For unclaimed text regions, check if any matched dialogue
    # has text that's suspiciously long (potential merge)
    if unclaimed_text_regions:
        for unclaimed in unclaimed_text_regions:
            ur_x1, ur_y1 = unclaimed["x1"], unclaimed["y1"]
            ur_x2, ur_y2 = unclaimed["x2"], unclaimed["y2"]
            ur_area = (ur_x2 - ur_x1) * (ur_y2 - ur_y1)

            # Find the nearest matched dialogue by region proximity
            best_neighbor_idx = None
            best_distance = float("inf")

            for dlg_idx, match in matches.items():
                if match.total_score < 1.0:
                    continue  # only check direct matches
                mr = match.region
                # Check if the unclaimed region is adjacent to this match's region
                gap_x = max(0, max(ur_x1, mr.x1) - min(ur_x2, mr.x2))
                gap_y = max(0, max(ur_y1, mr.y1) - min(ur_y2, mr.y2))
                dist = (gap_x ** 2 + gap_y ** 2) ** 0.5
                if dist < best_distance:
                    best_distance = dist
                    best_neighbor_idx = dlg_idx

            # If the nearest matched dialogue is very close (<30px) to the unclaimed region
            # AND the dialogue text is longer than expected for its region, suspect a merge
            if best_neighbor_idx is not None and best_distance < 30:
                neighbor_dlg = dialogues[best_neighbor_idx]
                neighbor_text = neighbor_dlg.get("text", "")
                neighbor_region = matches[best_neighbor_idx].region
                neighbor_area = (neighbor_region.x2 - neighbor_region.x1) * (neighbor_region.y2 - neighbor_region.y1)

                # Heuristic: if text length per area is much higher than typical
                # (typical is ~1 char per 200-400 px² depending on font size)
                chars_per_area = len(neighbor_text) / max(1, neighbor_area) * 10000
                if chars_per_area > 8:  # suspiciously dense text for the region
                    result["splits"].append({
                        "dialogue_index": best_neighbor_idx,
                        "orphaned_region_id": unclaimed["id"],
                        "reason": f"Text '{neighbor_text[:40]}...' may include text from adjacent region {unclaimed['id']}",
                    })
                    result["warnings"].append(
                        f"Suspected merge: D{best_neighbor_idx} text may include R{unclaimed['id']}"
                    )

    # Check 4: Spatial coherence — dialogue bbox should be near assigned region
    for dlg_idx, match in matches.items():
        if match.total_score < 1.0:
            continue  # only validate direct VLM matches
        dlg = dialogues[dlg_idx]
        bbox = dlg.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        hint = _to_pixel_bbox(bbox, img_w, img_h, analysis_w, analysis_h)
        region = match.region
        overlap = region.overlap_score(hint)
        if overlap < 0.01:
            # bbox is completely outside the assigned region — possible wrong assignment
            # Check if there's a better region candidate
            best_overlap = 0.0
            best_rid = None
            for det_id, det in page_dets.items():
                if det_id == dialogues[dlg_idx].get("region_id"):
                    continue
                if det.get("label") not in ("text_bubble", "text_free"):
                    continue
                candidate = _region_from_det(det, img_w, img_h)
                ov = candidate.overlap_score(hint)
                if ov > best_overlap:
                    best_overlap = ov
                    best_rid = det_id
            if best_rid is not None and best_overlap > 0.2:
                result["reassignments"][dlg_idx] = best_rid
                result["warnings"].append(
                    f"D{dlg_idx}: bbox suggests R{best_rid} (overlap={best_overlap:.2f}) not R{dialogues[dlg_idx].get('region_id')}"
                )

    if result["warnings"]:
        print(f"  [validator] {len(result['warnings'])} issues found:", file=sys.stderr)
        for w in result["warnings"][:5]:
            print(f"    {w}", file=sys.stderr)

    return result


# ── Capa 3: Rescue orphaned text regions ───────────────────────────────────────

def _rescue_orphaned_text_regions(
    orphaned_text: list[dict],
    matches: dict,
    dialogues: list[dict],
    img: "Image.Image",
    source_lang: str,
    matcher,
    ocr_weight: float,
    spatial_weight: float,
    position_weight: float,
    min_score: float,
) -> dict:
    """
    Try to match orphaned text_bubble/text_free regions to dialogues.
    
    Strategy:
    1. OCR each orphaned text region
    2. Check if any EXISTING matched dialogue's text contains the OCR text (merge detection)
    3. If no merge found, try to match against unmatched dialogues using Hungarian
    4. If still no match, check if OCR reads meaningful text → report for user attention
    
    Returns {dlg_idx: MatchResult} for any successful rescues.
    """
    from yomeru.lib.matching.ocr import ocr_region
    from yomeru.lib.matching import MatchResult
    from yomeru.lib.detection import TextRegion

    img_w, img_h = img.size
    rescued: dict = {}

    for orphan in orphaned_text:
        ox1, oy1, ox2, oy2 = orphan["x1"], orphan["y1"], orphan["x2"], orphan["y2"]
        region = TextRegion(
            x1=max(0, min(img_w, ox1)),
            y1=max(0, min(img_h, oy1)),
            x2=max(0, min(img_w, ox2)),
            y2=max(0, min(img_h, oy2)),
            label=orphan.get("label", "text_bubble"),
            score=float(orphan.get("score", 1.0)),
            mask=None,
        )

        # OCR the orphaned region
        ocr_text = ocr_region(img, region.bbox, source_lang)
        if not ocr_text or len(ocr_text.strip()) < 2:
            continue  # No meaningful text detected

        # Strategy A: Check if any matched dialogue contains this text (merge)
        best_match_idx = None
        best_similarity = 0.0

        for dlg_idx, match in matches.items():
            dlg_text = dialogues[dlg_idx].get("text", "")
            if not dlg_text:
                continue
            sim = _text_containment_score(ocr_text, dlg_text)
            if sim > best_similarity:
                best_similarity = sim
                best_match_idx = dlg_idx

        # If OCR text is substantially contained in a matched dialogue → it's a merge
        # We can't split the dialogue, but we note it and assign the region
        if best_similarity > 0.5 and best_match_idx is not None:
            # The orphaned region likely contains part of the merged dialogue's text
            # Assign it as a secondary match (lower score to indicate it's a rescue)
            # Don't reassign — keep as informational for now
            print(f"    [rescue] R{orphan['id']}: OCR='{ocr_text[:30]}' contained in D{best_match_idx} "
                  f"(sim={best_similarity:.2f}) — likely merge", file=sys.stderr)
            continue

        # Strategy B: Check against unmatched dialogues
        unmatched_dlg_indices = [
            i for i in range(len(dialogues))
            if i not in matches and not dialogues[i].get("skip")
        ]

        if unmatched_dlg_indices:
            best_dlg_idx = None
            best_text_score = 0.0
            for dlg_idx in unmatched_dlg_indices:
                dlg_text = dialogues[dlg_idx].get("text", "")
                sim = _text_containment_score(ocr_text, dlg_text)
                if sim > best_text_score:
                    best_text_score = sim
                    best_dlg_idx = dlg_idx

            if best_dlg_idx is not None and best_text_score > 0.3:
                rescued[best_dlg_idx] = MatchResult(
                    dialogue_index=best_dlg_idx, region=region,
                    spatial_score=0.5, text_score=best_text_score,
                    position_score=0.0, total_score=best_text_score * 0.8,
                    ocr_text=ocr_text,
                )
                print(f"    [rescue] R{orphan['id']}: matched to unmatched D{best_dlg_idx} "
                      f"(text_score={best_text_score:.2f})", file=sys.stderr)
                continue

        print(f"    [rescue] R{orphan['id']}: OCR='{ocr_text[:30]}' — no match found, remains orphaned",
              file=sys.stderr)

    return rescued


def _text_containment_score(needle: str, haystack: str) -> float:
    """Score how much of needle's content is contained in haystack.
    Uses character trigram overlap, biased toward containment."""
    import re
    n = re.sub(r"[^\w]", "", needle.lower())
    h = re.sub(r"[^\w]", "", haystack.lower())
    if not n or not h:
        return 0.0
    # Trigram containment: what fraction of needle's trigrams appear in haystack
    def trigrams(s: str) -> set:
        return {s[i:i+3] for i in range(len(s)-2)} if len(s) >= 3 else {s}
    tn = trigrams(n)
    th = trigrams(h)
    if not tn:
        return 0.0
    return len(tn & th) / len(tn)


def _save_match_log(matches, dialogues, page_dets, orphaned, debug_dir, page_num, img_w, img_h):
    """Save matching results to render_log.json."""
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
                "text": round(m.text_score, 3),
                "position": round(m.position_score, 3),
                "total": round(m.total_score, 3),
            },
            "ocr_text": getattr(m, "ocr_text", None),
            "dialogue_text": dlg.get("text", "")[:60],
        })

    direct = sum(1 for m in matches.values() if m.total_score == 1.0)
    unmatched = [
        {"dialogue_index": i, "text": dialogues[i].get("text", "")[:60]}
        for i in range(len(dialogues)) if i not in matches
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

    log_path = debug_dir / f"p{page_num:02d}_render_log.json"
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False))


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
    all_matched_regions = {id(m.region) for m in matches.values()}
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
