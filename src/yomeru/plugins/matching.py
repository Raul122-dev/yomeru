"""
Matching backends.

`cascade` — the built-in matcher: VLM region_id first, then Hungarian
(spatial + OCR) for the unresolved, reading order as a last resort near the
dialogue's own bbox, and OCR rescue of orphaned text regions
(lib/matching/cascade.py). The three numeric knobs are its options.

A new technique (e.g. a VLM that returns region ids directly, or an
embedding matcher) takes the same MatchRequest and returns a PageMatch; the
phase keeps writing the render log the editors read.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from yomeru.core.contracts import MatchRequest, PageMatch
from yomeru.plugins import register


class CascadeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ocr_weight: float = Field(default=0.4, ge=0, le=1, title="OCR weight",
                              description="How much the text read by OCR counts")
    spatial_weight: float = Field(default=0.4, ge=0, le=1, title="Spatial weight",
                                  description="How much the box position counts")
    min_score: float = Field(default=0.05, ge=0, le=0.5, title="Minimum score",
                             description="Matches below this are discarded")


@register("matching", "cascade", title="Model region IDs + OCR check", options=CascadeOptions, needs_gpu=True,
          description="Uses the region numbers the reading model gave each line, checked with OCR; position and reading order fill the gaps")
class CascadeMatcher:
    def __init__(self, options: CascadeOptions):
        from yomeru.lib.matching import build_matcher
        self.options = options
        self.matcher = build_matcher("hungarian")

    def match_page(self, req: MatchRequest) -> PageMatch:
        from yomeru.lib.matching.cascade import match_page
        o = self.options
        return match_page(req, self.matcher, o.ocr_weight, o.spatial_weight, o.min_score)
