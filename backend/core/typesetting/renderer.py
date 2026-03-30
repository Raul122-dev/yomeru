"""
Backward-compatibility shim. The canonical location is: core.typesetting.stages.rendering
"""
from .stages.rendering import build_renderer, RenderResult, BaseRenderer  # noqa: F401
from .stages.rendering.pil import PILRenderer, render_text_in_bubble  # noqa: F401