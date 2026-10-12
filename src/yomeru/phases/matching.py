"""
Phase 3: Matching — Map detected regions to analysis dialogues.

Input:  output/page_detections.json + output/page_analyses.json + source images
Output: output/typeset/debug/pXX_render_log.json (with s2_detection + s3_matching data)
"""
from __future__ import annotations

from yomeru.core.labels import BUBBLE, TEXT_BUBBLE, is_text
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
        matcher_backend: str = "hungarian"
        ocr_weight: float = 0.4
        spatial_weight: float = 0.4
        match_min_score: float = 0.05
    """
    from yomeru.lib.matching import build_matcher, MatchResult

    matcher_backend = options.get("matcher_backend", "hungarian")
    ocr_weight = options.get("ocr_weight", 0.4)
    spatial_weight = options.get("spatial_weight", 0.4)
    match_min_score = options.get("match_min_score", 0.05)
    comic_format = options.get("comic_format", "auto")

    from yomeru.core import artifacts

    # Effective inputs: active detections, analyses merged with user edits
    detections = artifacts.load_detections(run)
    analyses = artifacts.load_analyses(run)
    all_pages = artifacts.page_files(run)

    if page_scope:
        analyses = [a for a in analyses if a.get("page_number") in page_scope]

    total = len(analyses)
    on_progress({"type": "phase_progress", "phase": "matching", "total": total, "processed": 0})
    print(f"\n[matching] {total} pages, backend={matcher_backend}", file=sys.stderr)

    debug_dir = artifacts.debug_dir(run, create=True)

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
            used_region_ids: set[int] = set()

            # Two passes: ids that point at a text region claim first; ids that
            # point at a bubble container then take the text region inside it
            # (typesetting into the container drew over that region's own
            # dialogue) — unless a direct claim already owns it, in which case
            # the container itself is kept, as before.
            def claim(i: int, rid_int: int) -> None:
                used_region_ids.add(rid_int)
                matches[i] = MatchResult(
                    dialogue_index=i, region=_region_from_det(page_dets[rid_int], img_w, img_h),
                    spatial_score=1.0, text_score=1.0, total_score=1.0,
                )

            via_container: list[tuple[int, int]] = []
            for i, dlg in enumerate(dialogues):
                if dlg.get("skip"):
                    continue
                rid = dlg.get("region_id")
                if rid is None or int(rid) not in page_dets:
                    unresolved.append(i)
                elif not is_text(page_dets[int(rid)].get("label")):
                    via_container.append((i, int(rid)))
                elif int(rid) in used_region_ids:
                    unresolved.append(i)  # same region claimed twice
                else:
                    claim(i, int(rid))
            for i, container in via_container:
                inner = _text_region_of(container, page_dets)
                target = inner if inner is not None and inner not in used_region_ids else container
                if target in used_region_ids:
                    unresolved.append(i)
                else:
                    claim(i, target)
            unresolved.sort()

            print(f"    [matching] after Step 1: {len(matches)} matches, {len(unresolved)} unresolved", file=sys.stderr)
            if unresolved:
                print(f"    [matching] unresolved dialogues: {unresolved}", file=sys.stderr)

            # ── Step 3: Fallback Hungarian for unresolved ────────────────────
            if unresolved:
                # Only regions no dialogue has claimed yet (by detection id).
                # The old filter compared id() of freshly built objects and never
                # excluded anything, so a region could be assigned twice.
                claimed_bboxes = {(m.region.x1, m.region.y1, m.region.x2, m.region.y2) for m in matches.values()}
                candidates = [
                    r for r in (
                        _region_from_det(det, img_w, img_h)
                        for det_id, det in page_dets.items()
                        if is_text(det.get("label")) and det_id not in used_region_ids
                    )
                    if (r.x1, r.y1, r.x2, r.y2) not in claimed_bboxes
                ]

                fallback_dlgs = [dialogues[i] for i in unresolved]
                fallback_hints = [
                    _to_pixel_bbox(dialogues[i].get("bbox", [0, 0, 0, 0]), img_w, img_h, analysis_w, analysis_h)
                    for i in unresolved
                ]

                fb_matches = matcher.match(
                    image=img, dialogues=fallback_dlgs, regions=candidates,
                    hint_bboxes=fallback_hints, source_language=source_lang,
                    ocr_weight=ocr_weight, spatial_weight=spatial_weight,
                    min_score=match_min_score,
                )
                for local_i, fb_match in fb_matches.items():
                    orig_i = unresolved[local_i]
                    fb_match.dialogue_index = orig_i
                    matches[orig_i] = fb_match

            # ── Step 3b: Reading Order fallback for still-unresolved ──────────
            #    If Hungarian couldn't assign some dialogues (scores too low),
            #    use reading order as last resort (industry standard approach).
            still_unresolved = [
                i for i in range(len(dialogues))
                if i not in matches and not dialogues[i].get("skip")
            ]
            if still_unresolved:
                from yomeru.lib.matching.reading_order import _sort_reading_order

                # Use ALL text regions and do a full reading-order match for unresolved
                all_text_regions = [
                    _region_from_det(det, img_w, img_h)
                    for det in page_dets.values()
                    if is_text(det.get("label"))
                ]

                if all_text_regions:
                    rtl = _right_to_left(comic_format, source_lang)
                    sorted_indices = _sort_reading_order(all_text_regions, right_to_left=rtl)

                    # For each unresolved dialogue, find the next unclaimed region in reading order
                    claimed_bboxes = {(m.region.x1, m.region.y1, m.region.x2, m.region.y2) for m in matches.values()}
                    available_in_order = [
                        idx for idx in sorted_indices
                        if (all_text_regions[idx].x1, all_text_regions[idx].y1,
                            all_text_regions[idx].x2, all_text_regions[idx].y2) not in claimed_bboxes
                    ]

                    from yomeru.lib.matching import MatchResult
                    # Reading order is only a tie-breaker: a dialogue whose own bbox
                    # says it is elsewhere must not grab the next free region (it
                    # used to: an SFX landed ~360px away and its region got erased).
                    # Without a usable bbox → left unmatched for the editor.
                    n_assign = 0
                    for dlg_idx in still_unresolved:
                        hint = _to_pixel_bbox(dialogues[dlg_idx].get("bbox") or [0, 0, 0, 0],
                                              img_w, img_h, analysis_w, analysis_h)
                        pick = next((k for k in available_in_order
                                     if _near(all_text_regions[k], hint, img_w, img_h)), None)
                        if pick is None:
                            continue
                        available_in_order.remove(pick)
                        region = all_text_regions[pick]
                        n_assign += 1
                        matches[dlg_idx] = MatchResult(
                            dialogue_index=dlg_idx,
                            region=region,
                            spatial_score=0.0,
                            text_score=0.0,
                            total_score=0.5,
                            ocr_text="",
                        )
                    if n_assign > 0:
                        print(f"    [reading-order fallback] assigned {n_assign} unresolved", file=sys.stderr)

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

            # Text regions no dialogue landed in. Bubble containers are never
            # "orphans": they hold a text_bubble, not text of their own (they
            # used to be counted — p1 reported 14 "empty bubbles" with none).
            orphaned = [
                r for r in page_dets.values()
                if r["id"] not in claimed_ids and is_text(r.get("label"))
            ]

            # ── Step 5: Rescue orphaned text_bubble regions (Capa 3) ─────────
            orphaned_text = [r for r in orphaned if is_text(r.get("label"))]
            if orphaned_text:
                rescued = _rescue_orphaned_text_regions(
                    orphaned_text, matches, dialogues, img, source_lang,
                    matcher, ocr_weight, spatial_weight, match_min_score,
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
            _save_match_log(run, matches, dialogues, page_dets, orphaned, page_num, img_w, img_h)
            _save_debug_image(img, matches, dialogues, page_dets, orphaned, debug_dir, page_num)

            elapsed = round(time.time() - t0, 2)
            direct = sum(1 for m in matches.values() if m.total_score == 1.0)
            rescued_count = len(rescued) if orphaned_text else 0
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _text_region_of(rid: int, page_dets: dict[int, dict]) -> int | None:
    """`rid` itself if it is a text region; for a bubble container, the text
    region whose centre lies inside it (largest overlap); None if it has none."""
    det = page_dets[rid]
    if is_text(det.get("label")):
        return rid
    best, best_area = None, 0
    for tid, t in page_dets.items():
        if not is_text(t.get("label")):
            continue
        cx, cy = (t["x1"] + t["x2"]) / 2, (t["y1"] + t["y2"]) / 2
        if not (det["x1"] <= cx <= det["x2"] and det["y1"] <= cy <= det["y2"]):
            continue
        ix = max(0, min(det["x2"], t["x2"]) - max(det["x1"], t["x1"]))
        iy = max(0, min(det["y2"], t["y2"]) - max(det["y1"], t["y1"]))
        if ix * iy > best_area:
            best, best_area = tid, ix * iy
    return best


def _right_to_left(comic_format: str, source_lang: str) -> bool:
    """Reading direction: the format decides (manga RTL; manhwa/manhua/comic
    LTR); only 'auto' falls back to the source language."""
    fmt = (comic_format or "auto").lower()
    if fmt != "auto":
        return fmt == "manga"
    return source_lang.lower() in ("japanese", "chinese (traditional)")


def _near(region, hint, img_w: int, img_h: int) -> bool:
    """Region overlaps the VLM bbox, or its centre is within 8% of the page
    diagonal of the bbox. Degenerate/missing hints never match."""
    hx1, hy1, hx2, hy2 = hint
    if (hx2 - hx1) * (hy2 - hy1) <= 100:
        return False
    if region.overlap_score(hint) > 0:
        return True
    cx, cy = region.center
    dx = max(hx1 - cx, 0, cx - hx2)
    dy = max(hy1 - cy, 0, cy - hy2)
    return (dx * dx + dy * dy) ** 0.5 <= 0.08 * (img_w * img_w + img_h * img_h) ** 0.5


def _region_from_det(det: dict, img_w: int, img_h: int):
    """Build a TextRegion from a saved detection dict."""
    from yomeru.lib.detection import TextRegion
    return TextRegion(
        x1=max(0, min(img_w, int(det["x1"]))),
        y1=max(0, min(img_h, int(det["y1"]))),
        x2=max(0, min(img_w, int(det["x2"]))),
        y2=max(0, min(img_h, int(det["y2"]))),
        label=det.get("label", BUBBLE),
        score=float(det.get("score", 1.0)),
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
            label=orphan.get("label", TEXT_BUBBLE),
            score=float(orphan.get("score", 1.0)),
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
                    total_score=best_text_score * 0.8,
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
