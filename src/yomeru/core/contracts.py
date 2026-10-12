"""
Phase contracts — typed inputs/outputs exchanged between phases and backends.

A backend (see yomeru.plugins) only ever sees these objects: never a Run, a
path or meta.json. Contracts for matching, analysis and rendering are added
when those phases become backends (vault "Yomeru - Flujo de datos y backends").
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
