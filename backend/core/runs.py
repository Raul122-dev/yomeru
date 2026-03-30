from __future__ import annotations
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from core.config import RUNS_DIR


RunStatus = Literal["pending", "running", "done", "failed"]
PhaseStatus = Literal["pending", "running", "done", "failed"]


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
        provider: str = "local",
        source_language: str = "auto",
        translate: bool = False,
        target_language: str | None = None,
        global_context: str = "",
        detector_backend: str = "auto",
        detector_threshold: float = 0.4,
        ui_language: str = "English",
    ) -> "Run":
        run_id = uuid.uuid4().hex[:12]
        run = cls(run_id)
        run.dir.mkdir(parents=True, exist_ok=True)
        (run.dir / "pages").mkdir()
        (run.dir / "output").mkdir()
        run._write_meta({
            "id": run_id,
            "name": name,
            "model": model,
            "provider": provider,
            "comic_format": comic_format,
            "source_language": source_language,
            "translate": translate,
            "target_language": target_language,
            "global_context": global_context,
            "detector_backend": detector_backend,
            "detector_threshold": detector_threshold,
            "ui_language": ui_language,
            # overall status (backwards compat)
            "status": "pending",
            # per-phase sub-statuses
            "detection_status":          "pending",
            "analysis_status":           "pending",
            # typeset sub-stage statuses
            "typeset_matching_status":   "pending",
            "typeset_inpainting_status": "pending",
            "typeset_rendering_status":  "pending",
            "typeset_status":    "pending",
            "total_pages": 0,
            "processed_pages": 0,
            "detected_pages": 0,
            "created_at": datetime.utcnow().isoformat(),
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

    def update(self, **kwargs) -> None:
        m = self.meta()
        m.update(kwargs)
        self._write_meta(m)

    def pages_dir(self) -> Path:
        return self.dir / "pages"

    def output_dir(self) -> Path:
        return self.dir / "output"

    def context_file(self) -> Path:
        return self.dir / "output" / "context.json"

    def delete(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # ── refined file helpers ───────────────────────────────────────────────────

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

    def _write_meta(self, data: dict) -> None:
        (self.dir / "meta.json").write_text(json.dumps(data, indent=2))