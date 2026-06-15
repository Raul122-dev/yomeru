"""
yomeru.phases — Unified pipeline phase system.

Each phase is a self-contained module that:
  - Reads input from previous phases' file-based outputs
  - Produces its own file-based output in the run's output directory
  - Reports progress via callbacks
  - Can be run independently (if dependencies are satisfied)

Phase order: detection → analysis → matching → inpainting → rendering
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Callable

PhaseStatus = Literal["pending", "running", "done", "failed", "partial"]
PhaseName = Literal["detection", "analysis", "matching", "inpainting", "rendering"]

PHASE_ORDER: list[PhaseName] = [
    "detection",
    "analysis",
    "matching",
    "inpainting",
    "rendering",
]

PHASE_DEPS: dict[PhaseName, list[PhaseName]] = {
    "detection": [],
    "analysis": ["detection"],
    "matching": ["detection", "analysis"],
    "inpainting": ["matching"],
    "rendering": ["inpainting"],
}


@dataclass
class PageResult:
    """Result for a single page within a phase."""
    page_num: int
    filename: str
    success: bool
    error: str | None = None


@dataclass
class PhaseResult:
    """Result of running a phase."""
    phase: PhaseName
    status: PhaseStatus
    total_pages: int = 0
    processed_pages: int = 0
    failed_pages: list[int] = field(default_factory=list)
    page_results: list[PageResult] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "done"


# Progress event types emitted by phases
ProgressEvent = dict[str, Any]
ProgressCallback = Callable[[ProgressEvent], None]


def null_progress(event: ProgressEvent) -> None:
    """No-op progress callback."""
    pass
