"""Resolve the effective dialogue→region matches of a page.

Used by inpainting, rendering and the scanline preview so all three agree.
"""
from __future__ import annotations

from yomeru.core.labels import TEXT_BUBBLE
import json
from pathlib import Path


def _as_xyxy(region: dict | None) -> dict | None:
    if not region:
        return None
    if "x1" in region:
        return region
    bbox = region.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    return {
        "x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3],
        "label": region.get("label", TEXT_BUBBLE), "score": region.get("score", 1.0),
    }


def build_matches_from_refined(refined: list[dict], log: dict) -> list[dict]:
    """Merge manual overrides with auto matches (manual wins).

    `log` is the whole render log. Region geometry is looked up in
    s2_detection.regions (every detected region, orphans included), then in
    s3_matching.orphaned, then in the auto matches.
    """
    s3 = log.get("s3_matching", {})
    original = {m["dialogue_index"]: m for m in s3.get("matches", [])}

    regions_by_id: dict = {}
    for r in log.get("s2_detection", {}).get("regions", []):
        regions_by_id[r.get("id")] = r
    for r in s3.get("orphaned", []):
        regions_by_id.setdefault(r.get("region_id"), r)
    for m in s3.get("matches", []):
        if m.get("region_id") is not None:
            regions_by_id.setdefault(m["region_id"], m.get("region", {}))

    result: list[dict] = []
    overridden: set = set()
    for ov in refined:
        dlg_i = ov.get("dialogue_index")
        if dlg_i is None:
            continue
        overridden.add(dlg_i)
        region_id = ov.get("region_id")
        region = _as_xyxy(regions_by_id.get(region_id)) if region_id is not None else None
        if region is None and dlg_i in original:
            region = original[dlg_i].get("region")
        if region and "x1" in region:
            result.append({
                "dialogue_index": dlg_i,
                "region_id": region_id,
                "match_type": ov.get("match_type", "manual"),
                "region": region,
                "scores": {"spatial": 1.0, "text": 1.0, "position": 1.0, "total": 1.0},
                "dialogue_text": ov.get("dialogue_text", ""),
            })

    result.extend(m for i, m in original.items() if i not in overridden)
    return result


def effective_matches(log: dict, debug_dir: Path, page_num: int) -> list[dict]:
    """Auto matches of the page, with the user's refined overrides applied."""
    auto = log.get("s3_matching", {}).get("matches", [])
    refined_path = debug_dir / f"p{page_num:02d}_matches_refined.json"
    if not refined_path.exists():
        return auto
    try:
        return build_matches_from_refined(json.loads(refined_path.read_text()), log)
    except (json.JSONDecodeError, KeyError, TypeError):
        return auto
