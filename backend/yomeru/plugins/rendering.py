"""
Rendering backends.

`scanline` — the built-in typesetter: lays every dialogue inside its bubble's
contour (centre-first wrap, syllable splits, size harmony across the page,
collision nudging) and draws it with PIL. See lib/rendering/scanline_engine.

`image_edit` — letters dialogues with an image-edit model reached through a
chain of providers (lib/rendering/edit_providers), scanline for the rest and
for every dialogue no provider could do. See lib/rendering/image_edit.
"""
from __future__ import annotations

import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from yomeru.core.contracts import RenderRequest, RenderResult
from yomeru.plugins import register


class ScanlineOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register("rendering", "scanline", title="Scanline (programmatic)", options=ScanlineOptions, needs_gpu=False,
          description="Text laid out inside each bubble's contour and drawn with PIL")
class ScanlineRenderer:
    def __init__(self, options: ScanlineOptions):
        self.options = options

    def render_page(self, req: RenderRequest) -> RenderResult:
        from yomeru.lib.rendering.scanline_engine import layout_and_draw
        return layout_and_draw(req)


def _adapter_choices(schema: dict) -> None:
    from yomeru.lib.rendering.edit_providers import provider_names
    schema["enum"] = provider_names()


class EditModelRef(BaseModel):
    """One image-edit model: an adapter (wire protocol) on a saved connection."""
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(title="Connection", json_schema_extra={"x-widget": "connection"})
    adapter: str = Field(default="openrouter", title="Adapter",
                         description="How to talk to the connection: openrouter (image models on OpenRouter) "
                                     "or comfyui (a ComfyUI server running a workflow)",
                         json_schema_extra=_adapter_choices)
    model: str = Field(default="", title="Model",
                       description="OpenRouter model id (e.g. microsoft/mai-image-2.6-flash) or ComfyUI "
                                   "workflow name (e.g. qwen-image-2.1-edit)")
    quality: str = Field(default="", title="Quality", description="Passed to models that take it (e.g. high)")


class ImageEditOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: list[EditModelRef] = Field(
        default_factory=list, title="Models",
        description="Tried in order; dialogues none of them can do are drawn by scanline")
    scope: Literal["hard", "all", "manual"] = Field(
        default="hard", title="Dialogues",
        description="hard: SFX, free text, shouts and vertical lettering. all: every dialogue — every "
                    "dialogue of every page is one paid edit, so the cost grows with the chapter. "
                    "manual: only the ones marked in the render editor.",
        json_schema_extra={"x-confirm": {"all": (
            "Every dialogue of every page will be sent to the image model, one paid edit each. "
            "For example, with a model at 0.017 USD per edit a 20-page chapter with 10 dialogues per page "
            "costs about 3.40 USD, and re-renders that change the text cost again. "
            "The limits per rendering still apply.\n\nUse it for all dialogues?")}})
    max_cost_usd: float = Field(
        default=5.0, ge=0, le=100, title="Cost cap per rendering (USD)",
        description="Counted from zero each time rendering runs or a page is re-rendered; once reached, "
                    "the rest of that rendering is drawn by scanline (calls already running still finish)")
    max_edits: int = Field(
        default=300, ge=0, le=5000, title="Max edits per rendering",
        description="Limit on model calls per rendering, for models that report no cost (local ones); "
                    "whichever limit comes first stops the calls")
    max_parallel: int = Field(default=4, ge=1, le=16, title="Parallel requests")
    max_drift: float = Field(default=10.0, ge=1, le=40, title="Max image drift",
                             description="Edits that moved the art around the bubble more than this are rejected")


def _providers(refs: list[EditModelRef]):
    from yomeru.core.contracts import EditError
    from yomeru.core.settings import store
    from yomeru.lib.rendering.edit_providers import make_provider
    from yomeru.lib.rendering.image_edit import Provider

    cfg = store.load()
    out = []
    for ref in refs:
        conn = cfg.connection(ref.connection_id)
        if conn is None:
            print(f"  [image-edit] connection {ref.connection_id!r} no longer exists, skipping {ref.model}",
                  file=sys.stderr)
            continue
        try:
            impl = make_provider(ref.adapter, base_url=conn.base_url, api_key=conn.api_key,
                                 model=ref.model, quality=ref.quality)
        except EditError as e:
            print(f"  [image-edit] {ref.adapter} · {ref.model}: {e}", file=sys.stderr)
            continue
        out.append(Provider(label=f"{ref.adapter} · {ref.model}", impl=impl,
                            key=f"{ref.adapter}|{ref.model}|{ref.quality}"))
    return out


@register("rendering", "image_edit", title="Image-edit model (experimental)", options=ImageEditOptions,
          needs_gpu=False, description="An image-edit model re-letters the chosen dialogues; scanline draws the rest")
class ImageEditRenderer:
    def __init__(self, options: ImageEditOptions):
        self.options = options

    def render_page(self, req: RenderRequest) -> RenderResult:
        from yomeru.lib.rendering.image_edit import render_page
        # connections are resolved per page: a key edited in Settings applies at once
        return render_page(req, self.options, _providers(self.options.providers))
