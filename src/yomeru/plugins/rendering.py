"""
Rendering backends.

`scanline` — the built-in typesetter: lays every dialogue inside its bubble's
contour (centre-first wrap, syllable splits, size harmony across the page,
collision nudging) and draws it with PIL. See lib/rendering/scanline_engine.

A new technique (e.g. an image-generation model that redraws the text) takes
the same RenderRequest and returns a RenderResult; per-dialogue `events` keep
the render editor and the logs working.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from yomeru.core.contracts import RenderRequest, RenderResult
from yomeru.plugins import register


class ScanlineOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register("rendering", "scanline", options=ScanlineOptions, needs_gpu=False,
          description="Text laid out inside each bubble's contour and drawn with PIL")
class ScanlineRenderer:
    def __init__(self, options: ScanlineOptions):
        self.options = options

    def render_page(self, req: RenderRequest) -> RenderResult:
        from yomeru.lib.rendering.scanline_engine import layout_and_draw
        return layout_and_draw(req)
