"""
Rendering stage — public interface.

Usage:
    from yomeru.core.typesetting.stages.rendering import build_renderer, RenderResult

    renderer = build_renderer("pil")
    image, result = renderer.render(
        image=clean_image,
        bbox=(x1, y1, x2, y2),
        text="Translated text here.",
        tone="neutral",
        bubble_type="speech",
        source_language="Spanish",
    )
"""
from __future__ import annotations

from typing import Any

from .pil import RenderResult, PILRenderer, _font_cache  # noqa: F401


def build_renderer(backend: str = "pil") -> Any:
    """Return a cached renderer instance."""
    if backend == "pil":
        return PILRenderer()
    raise ValueError(f"unknown renderer backend: {backend!r}")