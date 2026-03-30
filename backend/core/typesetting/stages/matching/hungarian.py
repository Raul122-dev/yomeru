"""
Hungarian matching backend.

Optimal one-to-one assignment of dialogues to detected regions using
scipy's linear_sum_assignment. Greedy fallback when scipy is unavailable.

Score matrix columns (configurable weights):
  - spatial  : bbox overlap + center proximity
  - text     : OCR trigram similarity (dialogue text vs region OCR)
  - position : 9-zone page position hint from VLM

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PIL import Image
    from ..detection import TextRegion

from . import MatchResult
import re
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..detection import TextRegion
from .ocr import ocr_region


# 9-zone grid: text_position → (col 0-2, row 0-2)
_ZONE_MAP = {
    "top-left":      (0, 0), "top-center":    (1, 0), "top-right":    (2, 0),
    "center-left":   (0, 1), "center":        (1, 1), "center-right": (2, 1),
    "bottom-left":   (0, 2), "bottom-center": (1, 2), "bottom-right": (2, 2),
}


def _zone_score(region: TextRegion, text_position: str | None, img_w: int, img_h: int) -> float:
    if not text_position:
        return 0.0
    zone = _ZONE_MAP.get(text_position.lower().strip())
    if zone is None:
        return 0.0
    exp_cx = (zone[0] + 0.5) / 3.0 * img_w
    exp_cy = (zone[1] + 0.5) / 3.0 * img_h
    rcx, rcy = region.center
    dist = ((rcx - exp_cx) ** 2 + (rcy - exp_cy) ** 2) ** 0.5
    max_dist = (img_w ** 2 + img_h ** 2) ** 0.5
    return max(0.0, 1.0 - dist / (max_dist * 0.5))


class HungarianMatcher:
    """
    Optimal dialogue-to-region matcher using the Hungarian algorithm.

    Falls back to a greedy approach if scipy is not installed.
    Uses OCR text similarity to improve matching accuracy.
    """

    def match(
        self,
        image: "Image.Image",
        dialogues: list[dict],
        regions: list["TextRegion"],
        hint_bboxes: list["tuple[int,int,int,int] | None"],
        source_language: str = "auto",
        ocr_weight: float = 0.4,
        spatial_weight: float = 0.4,
        position_weight: float = 0.2,
        min_score: float = 0.05,
    ) -> dict[int, "MatchResult"]:
        """Assign dialogues to regions. Returns {dialogue_index: MatchResult}."""
        return _match_dialogues_to_regions(
            image=image,
            dialogues=dialogues,
            regions=regions,
            hint_bboxes=hint_bboxes,
            source_language=source_language,
            ocr_weight=ocr_weight,
            spatial_weight=spatial_weight,
            position_weight=position_weight,
            min_score=min_score,
        )




# ── internal implementation ────────────────────────────────────────────────────

def _match_dialogues_to_regions(
    image: Image.Image,
    dialogues: list[dict],
    regions: list[TextRegion],
    hint_bboxes: list[tuple[int, int, int, int] | None],
    source_language: str = "auto",
    ocr_weight: float = 0.4,
    spatial_weight: float = 0.4,
    position_weight: float = 0.2,
    min_score: float = 0.05,
) -> dict[int, MatchResult]:
    """
    Optimally match dialogues to regions using the Hungarian algorithm.
    Each region is assigned to at most one dialogue.
    Returns {dialogue_index: MatchResult}.
    """
    if not regions or not dialogues:
        return {}

    img_w, img_h = image.size
    n_dlg, n_reg = len(dialogues), len(regions)

    # ── OCR cache: run once per region ───────────────────────────────────────
    _ocr_cache: dict[int, str] = {}

    def get_ocr(r: TextRegion) -> str:
        k = id(r)
        if k not in _ocr_cache:
            _ocr_cache[k] = ocr_region(image, r.bbox, source_language)
        return _ocr_cache[k]

    # ── build score matrix [n_dlg × n_reg] ───────────────────────────────────
    scores      = np.zeros((n_dlg, n_reg))
    spatial_mat = np.zeros((n_dlg, n_reg))
    text_mat    = np.zeros((n_dlg, n_reg))
    pos_mat     = np.zeros((n_dlg, n_reg))

    for i, (dlg, hint) in enumerate(zip(dialogues, hint_bboxes)):
        vlm_text   = dlg.get("text", "").strip()
        text_pos   = dlg.get("text_position")
        hint_valid = (
            hint is not None
            and (hint[2] - hint[0]) * (hint[3] - hint[1]) > 100
        )

        for j, region in enumerate(regions):
            # spatial
            if hint is not None and hint_valid:
                sp = region.overlap_score(hint)
                hcx = (hint[0] + hint[2]) // 2
                hcy = (hint[1] + hint[3]) // 2
                if region.x1 <= hcx <= region.x2 and region.y1 <= hcy <= region.y2:
                    sp = max(sp, 0.35)
            else:
                sp = 0.05

            # text similarity (skip if zero spatial and valid hint — expensive)
            tx = 0.0
            if vlm_text and (sp > 0.02 or not hint_valid):
                ocr_t = get_ocr(region)
                tx = _text_similarity(vlm_text, ocr_t)
                if tx < 0.1 and ocr_t:
                    tx = max(tx, _text_similarity(
                        re.sub(r"[^\w]", "", vlm_text.lower()),
                        re.sub(r"[^\w]", "", ocr_t.lower()),
                    ))

            pz = _zone_score(region, text_pos, img_w, img_h)

            spatial_mat[i, j] = sp
            text_mat[i, j]    = tx
            pos_mat[i, j]     = pz
            scores[i, j]      = sp * spatial_weight + tx * ocr_weight + pz * position_weight

    # ── Hungarian assignment ──────────────────────────────────────────────────
    try:
        from scipy.optimize import linear_sum_assignment
        row_ind, col_ind = linear_sum_assignment(-scores)
    except ImportError:
        print("  [match] scipy missing — install with: pip install scipy", file=sys.stderr)
        row_ind, col_ind = _greedy(scores)

    results: dict[int, MatchResult] = {}
    for dlg_i, reg_j in zip(row_ind, col_ind):
        score = float(scores[dlg_i, reg_j])
        if score < min_score:
            print(f"  [match] dlg {dlg_i} below threshold ({score:.2f})", file=sys.stderr)
            continue
        ocr_t = _ocr_cache.get(id(regions[reg_j]), "")
        results[int(dlg_i)] = MatchResult(
            dialogue_index=int(dlg_i), region=regions[reg_j],
            spatial_score=float(spatial_mat[dlg_i, reg_j]),
            text_score=float(text_mat[dlg_i, reg_j]),
            position_score=float(pos_mat[dlg_i, reg_j]),
            total_score=score, ocr_text=ocr_t,
        )
        print(
            f"  [match] dlg {dlg_i} → reg {reg_j} "
            f"sp={spatial_mat[dlg_i,reg_j]:.2f} tx={text_mat[dlg_i,reg_j]:.2f} "
            f"pz={pos_mat[dlg_i,reg_j]:.2f} tot={score:.2f}",
            file=sys.stderr,
        )

    unmatched = [i for i in range(len(dialogues)) if i not in results]
    if unmatched:
        print(f"  [match] unmatched: {unmatched}", file=sys.stderr)
    return results


def _greedy(scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n_dlg, n_reg = scores.shape
    used: set[int] = set()
    rows, cols = [], []
    for i in range(n_dlg):
        best_j, best_s = -1, -1.0
        for j in range(n_reg):
            if j not in used and scores[i, j] > best_s:
                best_s, best_j = scores[i, j], j
        if best_j >= 0:
            rows.append(i); cols.append(best_j); used.add(best_j)
    return np.array(rows), np.array(cols)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower())


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    def tg(s: str) -> set[str]:
        return {s[i:i+3] for i in range(len(s)-2)} if len(s) >= 3 else {s}
    sa, sb = tg(na), tg(nb)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union > 0 else 0.0