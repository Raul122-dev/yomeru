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
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from yomeru.core.settings import PipelineSettings

from yomeru.core.paths import RUNS_DIR

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
        settings: "PipelineSettings",
        global_context: str = "",
        preset_id: str | None = None,
    ) -> "Run":
        """Create a run with a frozen copy of the effective settings."""
        from yomeru.core.settings import store
        run_id = uuid.uuid4().hex[:12]
        run = cls(run_id)
        run.dir.mkdir(parents=True, exist_ok=True)
        (run.dir / "pages").mkdir()
        (run.dir / "output").mkdir()

        conn = store.load().connection(settings.analysis_model.connection_id)
        lang = settings.language
        run._write_meta({
            "id": run_id,
            "name": name,
            "settings": settings.model_dump(),
            "preset_id": preset_id,
            "global_context": global_context,
            # Denormalised for listing/search in the UI: the model that actually reads
            "model": (f"local · {settings.analysis.options.get('model') or 'auto'}"
                      if settings.analysis.backend == "local" else settings.analysis_model.model),
            "connection_name": "" if settings.analysis.backend == "local" else (conn.name if conn else ""),
            "comic_format": lang.comic_format,
            "source_language": lang.source,
            "target_language": lang.target,
            "status": "pending",
            "phase_status": {p: "pending" for p in PHASES},
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
        with _meta_lock(self.id):
            m = self.meta()
            m.update(kwargs)
            self._write_meta(m)

    def set_phase_status(self, phase: str, status: str) -> None:
        """Atomically update a single phase's status."""
        with _meta_lock(self.id):
            m = self.meta()
            if "phase_status" not in m:
                m["phase_status"] = {p: "pending" for p in PHASES}
            m["phase_status"][phase] = status
            self._write_meta(m)

    def mark_downstream_stale(self, phase: str) -> list[str]:
        """After `phase` re-runs, later phases that were done are now outdated."""
        later = PHASES[PHASES.index(phase) + 1:]
        with _meta_lock(self.id):
            m = self.meta()
            ps = m.setdefault("phase_status", {p: "pending" for p in PHASES})
            changed = [p for p in later if ps.get(p) in ("done", "partial")]
            for p in changed:
                ps[p] = "stale"
            if changed:
                self._write_meta(m)
        return changed

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

    def analyses_file(self) -> Path:
        return self.output_dir() / "page_analyses.json"

    def active_detections_file(self) -> Path:
        """Returns refined if exists, else original."""
        r = self.detections_file(refined=True)
        return r if r.exists() else self.detections_file(refined=False)

    def _write_meta(self, data: dict) -> None:
        # Atomic write: write to temp file then rename to prevent race conditions
        # Atomic: unique temp file per writer, then rename
        meta_path = self.dir / "meta.json"
        tmp_path = self.dir / f"meta.json.{uuid.uuid4().hex[:8]}.tmp"
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(meta_path)


_meta_locks: dict[str, threading.RLock] = {}
_meta_locks_guard = threading.Lock()


def _meta_lock(run_id: str) -> threading.RLock:
    """Serialises read-modify-write of one run's meta.json across threads."""
    with _meta_locks_guard:
        return _meta_locks.setdefault(run_id, threading.RLock())
