"""
Matching technique `cascade`: which detected region each dialogue goes into.

  1. direct     — the VLM's region_id (a bubble container resolves to the text
                  region inside it); a region is claimed once
  2. hungarian  — unresolved dialogues vs unclaimed text regions (spatial + OCR)
  3. reading    — still unresolved: next free region in reading order, only if
     order        near the dialogue's own bbox
  4. orphans    — text regions no dialogue landed in
  5. rescue     — OCR orphans: merged into an existing dialogue (reported) or
                  matched to an unmatched one by text

Pure function of a MatchRequest (no run, no files): see plugins/matching.py.
"""
from __future__ import annotations

import sys

from yomeru.core.labels import BUBBLE, TEXT_BUBBLE, is_text
from yomeru.core.contracts import MatchRequest, PageMatch


def match_page(req: MatchRequest, matcher, ocr_weight: float, spatial_weight: float,
               match_min_score: float) -> PageMatch:
    from yomeru.lib.matching import MatchResult

    img = req.image
    img_w, img_h = img.size
    page_dets = req.detections
    dialogues = req.dialogues
    source_lang = req.source_language
    comic_format = req.comic_format
    analysis_w, analysis_h = req.analysis_w, req.analysis_h

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


    return PageMatch(matches=matches, orphaned=orphaned, rescued=len(rescued) if orphaned_text else 0)


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
    img,
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


