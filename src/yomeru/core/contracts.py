"""
Phase contracts — typed inputs/outputs exchanged between phases and backends.

A backend (see yomeru.plugins) only ever sees these objects: never a Run, a
path or meta.json. Every phase now has its contract here (vault "Yomeru - Flujo de datos y backends").
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict

from yomeru.core.labels import RegionLabel


# ── Detection ─────────────────────────────────────────────────────────────────

class Region(BaseModel):
    """One detected region, in original-image pixels. `id` is the join key every
    later phase (prompt badges, region_id, matches, editors) uses."""
    model_config = ConfigDict(extra="forbid")

    id: int
    x1: int
    y1: int
    x2: int
    y2: int
    label: RegionLabel
    score: float

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)


class PageDetections(BaseModel):
    """One entry of page_detections.json (and of the refined file)."""
    model_config = ConfigDict(extra="forbid")

    page_number: int
    original_w: int
    original_h: int
    regions: list[Region]


# ── Inpainting ────────────────────────────────────────────────────────────────

@dataclass
class InpaintTarget:
    """A region whose text must be erased (skipped dialogues already removed)."""
    bbox: tuple[int, int, int, int]
    label: str
    dialogue_index: int


@dataclass
class InpaintRequest:
    image: Image.Image                 # original page, RGB
    targets: list[InpaintTarget]       # from effective matches (refined matches applied)
    mask_edit: np.ndarray | None = None  # user's RGBA delta (mask editor), page size


@dataclass
class InpaintResult:
    image: Image.Image                 # same size as the input image
    mask: np.ndarray                   # final combined mask (uint8 0/255) → mask editor
    stats: dict = field(default_factory=dict)            # → render_log.s4_inpainting
    debug: dict[str, Image.Image] = field(default_factory=dict)  # name → image



# ── Analysis ──────────────────────────────────────────────────────────────────

@dataclass
class AnalysisRequest:
    """One page to read and translate. The model choice and connection are
    resolved by the backend (it may not use a remote model at all)."""
    image: Image.Image                 # original page, RGB
    page_number: int
    regions: list[dict]                # active detections (id, x1..y2, label, score) — the badges to cite
    previous_context: str | None = None  # story so far (characters, recent pages), built by the phase
    comic_format: str = "auto"
    source_language: str = "auto"
    target_language: str | None = None
    ui_language: str = "English"       # language of descriptions (scene, summary)
    global_context: str = ""           # user notes for the whole series
    page_context: str = ""             # user note for this page


# ── Matching ──────────────────────────────────────────────────────────────────

@dataclass
class MatchRequest:
    """One page: which detected region does each dialogue go into."""
    image: Image.Image                 # original page, RGB (OCR reads it)
    detections: dict[int, dict]        # active detections {region_id: {x1..y2, label, score, id}}
    dialogues: list[dict]              # analysis dialogues (edits merged): text, region_id hint, bbox, skip
    source_language: str
    comic_format: str                  # reading direction (manga RTL, others LTR)
    analysis_w: int = 0                # size of the image the VLM saw (dialogue bboxes are in it)
    analysis_h: int = 0


@dataclass
class PageMatch:
    matches: dict                      # {dialogue_index: lib.matching.MatchResult}
    orphaned: list[dict]               # text regions no dialogue landed in
    rescued: int = 0


# ── Rendering ─────────────────────────────────────────────────────────────────

@dataclass
class RenderRequest:
    """One page to typeset, with every user edit already resolved."""
    inpainted: Image.Image             # text-free page (inpainting output), RGB
    original: Image.Image              # source page, RGB (bubble outlines are visible here)
    matches: list[dict]                # effective matches: {dialogue_index, region_id, region{x1..y2,label}}
    dialogues: list[dict]              # analysis dialogues (edits merged): text, text_translated, tone, bubble_type...
    overrides: dict[int, dict]         # render editor overrides by dialogue_index
    skipped: set[int]                  # dialogue indices not to draw (editor > VLM)
    containers: list[tuple[int, int, int, int]]  # bubble / text_bubble boxes (file order)
    use_translation: bool              # False = draw the original text (layout check)
    lang_code: str                     # hyphenation language of the DRAWN text (pyphen code)


@dataclass
class RenderResult:
    image: Image.Image                 # final page, same size as the input
    events: list[dict]                 # one per match: status ok/skip (+reason), text, font_size, lines, bbox → render log
    layouts: int = 0
    preview: Image.Image | None = None  # optional debug view (e.g. contours drawn)
