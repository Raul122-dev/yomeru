"""
Detection stage — public interface.

Usage:
    from yomeru.lib.detection import build_detector, TextRegion

    detector = build_detector()
    regions  = detector.detect(image, threshold=0.5)

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations

from typing import Any, Protocol

from PIL import Image


# ── shared data model ─────────────────────────────────────────────────────────

from dataclasses import dataclass


@dataclass
class TextRegion:
    """A detected text region in image pixel coordinates."""
    x1: int
    y1: int
    x2: int
    y2: int
    label: str = "text"
    score: float = 1.0

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def area(self) -> int:
        return self.width * self.height

    def overlap_score(self, hint: tuple[int, int, int, int]) -> float:
        """IoU-style overlap with a hint bbox."""
        hx1, hy1, hx2, hy2 = hint
        ox1, oy1 = max(self.x1, hx1), max(self.y1, hy1)
        ox2, oy2 = min(self.x2, hx2), min(self.y2, hy2)
        if ox2 <= ox1 or oy2 <= oy1:
            return 0.0
        return (ox2 - ox1) * (oy2 - oy1) / max(1, (hx2 - hx1) * (hy2 - hy1))


# ── protocol ──────────────────────────────────────────────────────────────────

class BaseDetector(Protocol):
    """Interface every detection backend must satisfy."""
    @property
    def name(self) -> str: ...

    def detect(self, image: Image.Image, threshold: float = 0.5) -> list[TextRegion]: ...


# ── factory ───────────────────────────────────────────────────────────────────

_cache: dict[str, Any] = {}


def build_detector(backend: str = "ogkalu") -> Any:
    """
    Return the cached detector. ogkalu RT-DETR is the only backend: every later
    phase (matching, inpainting, rendering) is keyed on its bubble /
    text_bubble / text_free regions, so the detector is not interchangeable.
    "auto" and the retired "ctd" are accepted for old runs and resolve to ogkalu.
    """
    from .ogkalu import OgkaluDetector
    if "ogkalu" not in _cache:
        _cache["ogkalu"] = OgkaluDetector()
    return _cache["ogkalu"]


def list_backends() -> list[dict]:
    return [{"key": "ogkalu", "label": "ogkalu RT-DETR", "available": True}]
