"""
Matching stage — public interface.

Usage:
    from yomeru.stages.matching import build_matcher, MatchResult

    matcher = build_matcher("hungarian")
    matches = matcher.match(
        image=image,
        dialogues=dialogues,
        regions=regions,
        saved_detections=saved_detections,
        source_language="Spanish",
    )

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..detection import TextRegion


@dataclass
class MatchResult:
    """Result of matching one dialogue to one detected region."""
    dialogue_index: int
    region: TextRegion
    spatial_score: float
    text_score: float
    total_score: float
    ocr_text: str = ""


_cache: dict[str, Any] = {}


def build_matcher(backend: str = "hungarian") -> Any:
    """
    Return a cached matcher instance.

    backend: "hungarian" — score-based optimal assignment (spatial + OCR)
    """
    if backend in _cache:
        return _cache[backend]

    if backend == "hungarian":
        from .hungarian import HungarianMatcher
        inst: Any = HungarianMatcher()
    else:
        raise ValueError(f"unknown matcher backend: {backend!r}")

    _cache[backend] = inst
    return inst