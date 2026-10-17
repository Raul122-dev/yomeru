"""
Manga reading order of text regions.

Used by the cascade's positional fallback: regions are grouped into rows
(adaptive Y-gap threshold) and sorted right-to-left (or left-to-right) inside
each row, which follows the usual panel flow.
"""
from __future__ import annotations

from ..detection import TextRegion


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
