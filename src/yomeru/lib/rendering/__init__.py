"""
Rendering stage — public interface.

Usage:
    from yomeru.lib.rendering import build_renderer, RenderResult

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

from typing import Any, Protocol

from PIL import Image

# Re-export from the actual implementation
from yomeru.core.typesetting.stages.rendering.pil import RenderResult, PILRenderer, _font_cache  # noqa: F401


class BaseRenderer(Protocol):
    """Interface every rendering backend must satisfy."""
    @property
    def name(self) -> str: ...

    def render(
        self,
        image: Image.Image,
        bbox: tuple[int, int, int, int],
        text: str,
        tone: str,
        bubble_type: str,
        font_style: str | None,
        line_break_hint: str | None,
        source_language: str,
        padding: int,
        min_font_size: int,
        max_font_size: int,
    ) -> "tuple[Image.Image, RenderResult]": ...


_cache: dict[str, Any] = {}


def build_renderer(backend: str = "pil") -> Any:
    """
    Return a cached renderer instance.

    backend: "pil" (only production option currently)
      - "pil" : PIL v2 + pyphen, with outline, rotation, CJK, shape fitting
    """
    if backend in _cache:
        return _cache[backend]

    if backend == "pil":
        inst: Any = PILRenderer()
    else:
        raise ValueError(f"unknown renderer backend: {backend!r}")

    _cache[backend] = inst
    return inst