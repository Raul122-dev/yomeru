"""
Region label vocabulary — the contract every phase is keyed on.

Detection (ogkalu RT-DETR-v2) emits exactly these three labels. Analysis,
matching, inpainting and rendering all branch on them, so they are defined
once here and nowhere else. A future detector must map its classes to this
vocabulary (adapter) — see vault "Yomeru - Flujo de datos y backends" §4.
"""
from __future__ import annotations

from typing import Literal

RegionLabel = Literal["bubble", "text_bubble", "text_free"]

BUBBLE: RegionLabel = "bubble"            # speech-bubble container (no text of its own)
TEXT_BUBBLE: RegionLabel = "text_bubble"  # text inside a bubble
TEXT_FREE: RegionLabel = "text_free"      # free-floating text: narration, SFX, signs

ALL_LABELS: frozenset[str] = frozenset({BUBBLE, TEXT_BUBBLE, TEXT_FREE})

# Regions that carry text: candidates for a dialogue, masked and typeset.
TEXT_LABELS: frozenset[str] = frozenset({TEXT_BUBBLE, TEXT_FREE})
# Regions whose shape can hold typeset text (contour extraction in rendering).
CONTAINER_LABELS: frozenset[str] = frozenset({BUBBLE, TEXT_BUBBLE})
# Text not enclosed by a bubble: whole-box mask + LaMa, bold text with outline.
FREE_LABELS: frozenset[str] = frozenset({TEXT_FREE})


def is_text(label: str | None) -> bool:
    return label in TEXT_LABELS


def is_free(label: str | None) -> bool:
    return label in FREE_LABELS
