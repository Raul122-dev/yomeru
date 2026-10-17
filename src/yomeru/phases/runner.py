"""Phase execution: one job per run at a time.

A job is accepted synchronously by `start_job()` — it takes the run's lock and
validates dependencies *before* the HTTP response, so conflicts surface as a
409/400 instead of a silent failure inside a background thread. The work then
runs in a daemon thread that releases the lock when it ends.

Cancellation is cooperative: phases call `progress()`/emit between pages and
the emitter raises `Cancelled` once a cancel was requested.
"""
from __future__ import annotations

import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any

from yomeru.core.runs import Run
from yomeru.phases import (
    PHASE_DEPS,
    PHASE_ORDER,
    PhaseName,
    PhaseResult,
    ProgressCallback,
    null_progress,
)

COMPLETE = ("done", "partial")
# Phases not yet behind a backend take the GPU lock for the whole phase.
# Backend-based phases (inpainting) lock per page from BackendSpec.needs_gpu,
# and rendering locks per page, so previews can interleave.
GPU_PHASES = ("matching",)


class PhaseError(Exception):
    """A phase cannot be started (busy, unmet dependencies, unknown phase)."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code  # "busy" | "dependencies" | "invalid"


class Cancelled(BaseException):
    """BaseException so per-page `except Exception` blocks inside phases don't swallow it."""


class _Job:
    def __init__(self, run_id: str, label: str):
        self.run_id = run_id
        self.label = label
        self.cancel = threading.Event()


_guard = threading.Lock()
_jobs: dict[str, _Job] = {}


def active_job(run_id: str) -> str | None:
    with _guard:
        job = _jobs.get(run_id)
        return job.label if job else None


def request_cancel(run_id: str) -> bool:
    with _guard:
        job = _jobs.get(run_id)
    if job is None:
        return False
    job.cancel.set()
    return True


def check_dependencies(run: Run, phase: PhaseName) -> list[str]:
    status = run.meta().get("phase_status", {})
    return [
        f"Phase '{dep}' must be completed first (current: {status.get(dep, 'pending')})"
        for dep in PHASE_DEPS[phase]
        if status.get(dep, "pending") not in COMPLETE
    ]


def start_job(
    run: Run,
    label: str,
    work: Callable[[Callable[[dict], None], threading.Event], Any],
    on_progress: ProgressCallback = null_progress,
    first_phase: PhaseName | None = None,
) -> None:
    """Reserve the run and launch `work(emit, cancel_event)` in a thread."""
    if first_phase is not None:
        if first_phase not in PHASE_ORDER:
            raise PhaseError(f"Unknown phase: {first_phase}")
        errors = check_dependencies(run, first_phase)
        if errors:
            raise PhaseError("; ".join(errors), "dependencies")

    job = _Job(run.id, label)
    with _guard:
        if run.id in _jobs:
            raise PhaseError(f"'{_jobs[run.id].label}' is already running on this run", "busy")
        _jobs[run.id] = job

    def emit(event: dict) -> None:
        on_progress(event)
        if job.cancel.is_set() and event.get("type") in ("page_start", "page_done", "page_error"):
            raise Cancelled()

    def target() -> None:
        try:
            work(emit, job.cancel)
        except Cancelled:
            pass  # run_phase already recorded the cancellation
        except Exception:  # never let a worker die silently
            traceback.print_exc(file=sys.stderr)
        finally:
            with _guard:
                _jobs.pop(run.id, None)

    threading.Thread(target=target, name=f"yomeru-{run.id}-{label}", daemon=True).start()


def run_phase(
    run: Run,
    phase: PhaseName,
    options: dict[str, Any] | None = None,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """Execute one phase synchronously (caller holds the run's job)."""
    is_scoped = bool(page_scope)
    errors = check_dependencies(run, phase)
    if errors:
        msg = "; ".join(errors)
        on_progress({"type": "phase_error", "phase": phase, "error": msg, "scoped": is_scoped})
        return PhaseResult(phase=phase, status="failed", error=msg)

    prev_status = run.get_phase_status(phase)
    run.set_phase_status(phase, "running")
    run.update(error=None)
    on_progress({"type": "phase_start", "phase": phase, "scoped": is_scoped})

    try:
        fn = _get_phase_fn(phase)
        kwargs = dict(run=run, options=options or {}, on_progress=on_progress, page_scope=page_scope)
        if phase in GPU_PHASES:
            from yomeru.core.gpu import gpu_lock
            with gpu_lock():
                result = fn(**kwargs)
        else:
            result = fn(**kwargs)
    except Cancelled:
        # Keep what was there before; a cancelled full run is not "done"
        status = prev_status if (is_scoped and prev_status in COMPLETE) else "cancelled"
        run.set_phase_status(phase, status)
        on_progress({"type": "phase_cancelled", "phase": phase, "status": status, "scoped": is_scoped})
        raise
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)
        status = "partial" if (is_scoped and prev_status in COMPLETE) else "failed"
        run.set_phase_status(phase, status)
        run.update(error=msg)
        on_progress({"type": "phase_error", "phase": phase, "error": msg, "scoped": is_scoped})
        return PhaseResult(phase=phase, status="failed", error=msg)

    if is_scoped:
        # Re-running some pages of a phase that was complete keeps it complete;
        # a failure on those pages degrades it to partial. A phase that never
        # completed only becomes done after a full run.
        if prev_status in COMPLETE:
            status = prev_status if result.status == "done" else "partial"
        else:
            status = "partial" if result.status != "failed" else "failed"
    else:
        status = result.status
    run.set_phase_status(phase, status)
    if result.error:
        run.update(error=result.error)

    stale = run.mark_downstream_stale(phase) if result.processed_pages else []
    on_progress({
        "type": "phase_done", "phase": phase, "status": status,
        "processed": result.processed_pages, "failed": result.failed_pages,
        "scoped": is_scoped, "stale": stale,
    })
    return result


def run_all(
    run: Run,
    options: dict[str, Any] | None = None,
    on_progress: ProgressCallback = null_progress,
    start_from: PhaseName | None = None,
) -> dict[PhaseName, PhaseResult]:
    """Run phases sequentially from `start_from` (caller holds the run's job)."""
    opts = options or {}
    results: dict[PhaseName, PhaseResult] = {}
    phases = PHASE_ORDER[PHASE_ORDER.index(start_from):] if start_from else PHASE_ORDER

    run.update(status="running", finished_at=None)
    try:
        for phase in phases:
            result = run_phase(run, phase, options=dict(opts.get(phase, {})), on_progress=on_progress)
            results[phase] = result
            if result.status == "failed":
                run.update(status="failed", finished_at=_now())
                return results
    except Cancelled:
        run.update(status="cancelled", finished_at=_now())
        return results
    run.update(status="done", finished_at=_now())
    return results


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def recover_interrupted_runs() -> int:
    """At startup no job can be running: reset states left by a crash/restart."""
    from yomeru.core.paths import RUNS_DIR
    fixed = 0
    for meta_file in RUNS_DIR.glob("*/meta.json"):
        run = Run(meta_file.parent.name)
        try:
            meta = run.meta()
        except Exception:
            continue
        hung = [p for p, s in meta.get("phase_status", {}).items() if s == "running"]
        for p in hung:
            run.set_phase_status(p, "failed")
        if hung or meta.get("status") == "running":
            run.update(status="failed", finished_at=_now(),
                       error="Interrupted: the server stopped while this was running")
            fixed += 1
    return fixed


def _get_phase_fn(phase: PhaseName):
    if phase == "detection":
        from yomeru.phases.detection import run
    elif phase == "analysis":
        from yomeru.phases.analysis import run
    elif phase == "matching":
        from yomeru.phases.matching import run
    elif phase == "inpainting":
        from yomeru.phases.inpainting import run
    elif phase == "rendering":
        from yomeru.phases.rendering import run
    else:
        raise PhaseError(f"Unknown phase: {phase}")
    return run
