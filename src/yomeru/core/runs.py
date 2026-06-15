"""
Run model — directory-backed run state.

A run is stored as ~/.yomeru/runs/<id>/ with:
  - meta.json       ← all state/config
  - pages/          ← uploaded source images
  - output/         ← phase outputs (detections, analyses, typeset images, etc.)
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from yomeru.core.config import RUNS_DIR

RunStatus = Literal["pending", "running", "done", "failed"]

PHASES = ["detection", "analysis", "matching", "inpainting", "rendering"]


class Run:
    """A run is a directory inside ~/.yomeru/runs/<id>/"""

    def __init__(self, id: str):
        self.id = id
        self.dir = RUNS_DIR / id

    @classmethod
    def create(
        cls,
        name: str,
        model: str,
        comic_format: str,
        provider: str = "",
        source_language: str = "auto",
        target_language: str = "Spanish",
        global_context: str = "",
        detector_backend: str = "auto",
        detector_threshold: float = 0.4,
        inpainter_backend: str = "auto",
        ui_language: str = "English",
        execution_mode: str = "sequential",
    ) -> "Run":
        run_id = uuid.uuid4().hex[:12]
        run = cls(run_id)
        run.dir.mkdir(parents=True, exist_ok=True)
        (run.dir / "pages").mkdir()
        (run.dir / "output").mkdir()

        phase_status = {p: "pending" for p in PHASES}

        run._write_meta({
            "id": run_id,
            "name": name,
            "model": model,
            "provider": provider,
            "comic_format": comic_format,
            "source_language": source_language,
            "target_language": target_language,
            "global_context": global_context,
            "detector_backend": detector_backend,
            "detector_threshold": detector_threshold,
            "inpainter_backend": inpainter_backend,
            "ui_language": ui_language,
            "execution_mode": execution_mode,
            "status": "pending",
            "phase_status": phase_status,
            "total_pages": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
        })
        return run

    @classmethod
    def load(cls, run_id: str) -> "Run | None":
        run = cls(run_id)
        return run if (run.dir / "meta.json").exists() else None

    @classmethod
    def list_all(cls) -> list[dict]:
        runs = []
        for meta_file in sorted(RUNS_DIR.glob("*/meta.json"), reverse=True):
            try:
                runs.append(json.loads(meta_file.read_text()))
            except Exception:
                pass
        return runs

    def meta(self) -> dict:
        return json.loads((self.dir / "meta.json").read_text())

    def update(self, **kwargs: Any) -> None:
        m = self.meta()
        m.update(kwargs)
        self._write_meta(m)

    def set_phase_status(self, phase: str, status: str) -> None:
        """Atomically update a single phase's status."""
        m = self.meta()
        if "phase_status" not in m:
            m["phase_status"] = {p: "pending" for p in PHASES}
        m["phase_status"][phase] = status
        # Also update legacy fields for backwards compat
        m[f"{phase}_status"] = status
        if phase in ("matching", "inpainting", "rendering"):
            m[f"typeset_{phase}_status"] = status
        self._write_meta(m)

    def get_phase_status(self, phase: str) -> str:
        m = self.meta()
        return m.get("phase_status", {}).get(phase, "pending")

    def pages_dir(self) -> Path:
        return self.dir / "pages"

    def output_dir(self) -> Path:
        return self.dir / "output"

    def context_file(self) -> Path:
        return self.dir / "output" / "context.json"

    def delete(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── File helpers ───────────────────────────────────────────────────────────

    def detections_file(self, refined: bool = False) -> Path:
        name = "page_detections_refined.json" if refined else "page_detections.json"
        return self.output_dir() / name

    def analyses_file(self, refined: bool = False) -> Path:
        name = "page_analyses_refined.json" if refined else "page_analyses.json"
        return self.output_dir() / name

    def active_detections_file(self) -> Path:
        """Returns refined if exists, else original."""
        r = self.detections_file(refined=True)
        return r if r.exists() else self.detections_file(refined=False)

    def active_analyses_file(self) -> Path:
        """Returns refined if exists, else original."""
        r = self.analyses_file(refined=True)
        return r if r.exists() else self.analyses_file(refined=False)

    def matching_file(self) -> Path:
        return self.output_dir() / "matching.json"

    def typeset_dir(self) -> Path:
        d = self.output_dir() / "typeset"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def debug_dir(self) -> Path:
        d = self.output_dir() / "typeset" / "debug"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_meta(self, data: dict) -> None:
        (self.dir / "meta.json").write_text(json.dumps(data, indent=2))
