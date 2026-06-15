"""
Reading-order based matcher.

Matches text regions to dialogues by sorting both into manga reading order
and pairing by position. This is the standard approach used by all major
manga translation tools (manga-image-translator, etc.).

Algorithm:
  1. Sort text regions into reading order (RTL top-to-bottom for manga)
  2. Dialogues are assumed to already be in reading order (from VLM/translator)
  3. Match positionally: sorted_regions[i] ↔ dialogues[i]

For manga reading order:
  - Group regions into rows (adaptive Y-gap threshold)
  - Within each row, sort right-to-left
  - This handles standard manga panel flow automatically

Handles N≠M (different counts of regions vs dialogues) gracefully by
matching as many as possible from the top.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..detection import TextRegion
from . import MatchResult


class ReadingOrderMatcher:
    """Match regions to dialogues by reading order (positional identity)."""

    def match(
        self,
        image: Image.Image,
        dialogues: list[dict],
        regions: list[TextRegion],
        hint_bboxes: list[tuple[int, int, int, int] | None] | None = None,
        source_language: str = "auto",
        right_to_left: bool = True,
        **kwargs,
    ) -> dict[int, MatchResult]:
        """
        Match by reading order.

        1. Sort regions into manga reading order
        2. Pair sorted_regions[i] with dialogues[i]
        """
        if not regions or not dialogues:
            return {}

        # Sort regions into reading order
        sorted_indices = _sort_reading_order(regions, right_to_left)

        # Match positionally
        results: dict[int, MatchResult] = {}
        n_matches = min(len(sorted_indices), len(dialogues))

        for dlg_idx in range(n_matches):
            region_idx = sorted_indices[dlg_idx]
            region = regions[region_idx]

            # Score based on how well the position matches
            # (for reading order, all matches are "confident" since order is the signal)
            results[dlg_idx] = MatchResult(
                dialogue_index=dlg_idx,
                region=region,
                spatial_score=1.0,
                text_score=0.0,
                position_score=1.0,
                total_score=0.8,  # High confidence for reading-order match
                ocr_text="",
            )

        return results


def _sort_reading_order(
    regions: list[TextRegion],
    right_to_left: bool = True,
) -> list[int]:
    """
    Sort text regions into manga reading order.

    Algorithm (from manga-image-translator research):
    1. Compute center points of all regions
    2. Group into rows using adaptive Y-gap threshold
    3. Within each row, sort by X (RTL for manga, LTR for manhwa)
    4. Return indices in reading order
    """
    if not regions:
        return []

    # Compute centers
    centers = [
        ((r.x1 + r.x2) / 2, (r.y1 + r.y2) / 2, i)
        for i, r in enumerate(regions)
    ]

    # Sort by Y first
    centers_sorted = sorted(centers, key=lambda c: c[1])

    # Adaptive row gap threshold: 50% of smallest region height
    heights = [r.y2 - r.y1 for r in regions]
    if heights:
        min_h = min(heights)
        gap_threshold = max(20, min_h * 0.5)
    else:
        gap_threshold = 30

    # Group into rows
    rows: list[list[tuple[float, float, int]]] = []
    current_row: list[tuple[float, float, int]] = [centers_sorted[0]]

    for k in range(1, len(centers_sorted)):
        y_diff = centers_sorted[k][1] - centers_sorted[k - 1][1]
        if y_diff > gap_threshold:
            rows.append(current_row)
            current_row = [centers_sorted[k]]
        else:
            current_row.append(centers_sorted[k])
    rows.append(current_row)

    # Sort within each row by X
    ordered_indices: list[int] = []
    for row in rows:
        # RTL: rightmost first. LTR: leftmost first.
        row_sorted = sorted(row, key=lambda c: c[0], reverse=right_to_left)
        ordered_indices.extend(c[2] for c in row_sorted)

    return ordered_indices
