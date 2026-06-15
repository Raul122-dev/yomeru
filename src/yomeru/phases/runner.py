"""
RunExecutor — Central orchestrator for phase execution.

Responsibilities:
  - Per-run locking (prevent concurrent phase execution)
  - Dependency validation (ensure required phases are done)
  - Atomic meta.json status updates
  - Sequential execution mode (run-all)
  - Progress event normalization and dispatch
"""
from __future__ import annotations

import asyncio
import threading
import traceback
from typing import Any, Callable

from yomeru.core.runs import Run
from yomeru.phases import (
    PHASE_DEPS,
    PHASE_ORDER,
    PhaseName,
    PhaseResult,
    PhaseStatus,
    ProgressCallback,
    ProgressEvent,
    null_progress,
)


class PhaseError(Exception):
    """Raised when a phase cannot be started."""
    pass


# Per-run locks to prevent concurrent execution
_run_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_lock(run_id: str) -> threading.Lock:
    with _locks_lock:
        if run_id not in _run_locks:
            _run_locks[run_id] = threading.Lock()
        return _run_locks[run_id]


def check_dependencies(run: Run, phase: PhaseName) -> list[str]:
    """
    Check if phase dependencies are satisfied.
    Returns list of error messages (empty = OK).
    """
    meta = run.meta()
    errors = []
    for dep in PHASE_DEPS[phase]:
        dep_status = meta.get("phase_status", {}).get(dep, "pending")
        if dep_status not in ("done", "partial"):
            errors.append(f"Phase '{dep}' must be completed first (current: {dep_status})")
    return errors


def run_phase(
    run: Run,
    phase: PhaseName,
    options: dict[str, Any] | None = None,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult:
    """
    Execute a single phase for a run.

    Args:
        run: The run to execute the phase for
        phase: Which phase to run
        options: Phase-specific options (model, thresholds, etc.)
        on_progress: Callback for progress events
        page_scope: If set, only process these page numbers (1-based).
                    Scoped runs don't overwrite global phase status if the phase
                    was already "done" — they keep it as-is on success.

    Returns:
        PhaseResult with status and per-page results.
    """
    lock = _get_lock(run.id)
    if not lock.acquire(blocking=False):
        raise PhaseError(f"Run '{run.id}' already has a phase in progress")

    is_scoped = page_scope is not None and len(page_scope) > 0

    try:
        # Check dependencies
        dep_errors = check_dependencies(run, phase)
        if dep_errors:
            raise PhaseError("; ".join(dep_errors))

        # Update status to running
        run.set_phase_status(phase, "running")
        on_progress({"type": "phase_start", "phase": phase, "scoped": is_scoped})

        # Import and run the phase module
        phase_fn = _get_phase_fn(phase)
        result = phase_fn(
            run=run,
            options=options or {},
            on_progress=on_progress,
            page_scope=page_scope,
        )

        # Update status based on result.
        # For scoped runs: don't promote to "done" if only a subset was processed.
        # Keep the previous status if it was already "done" and the scoped run succeeded.
        if is_scoped:
            meta = run.meta()
            prev_status = meta.get("phase_status", {}).get(phase, "pending")
            if result.status == "done" and prev_status == "done":
                # Scoped success on an already-done phase: keep "done"
                run.set_phase_status(phase, "done")
            elif result.status == "failed":
                run.set_phase_status(phase, "partial")
            else:
                # Scoped success on a non-done phase: mark partial
                run.set_phase_status(phase, prev_status if prev_status == "done" else "done")
        else:
            run.set_phase_status(phase, result.status)

        if result.error:
            run.update(error=result.error)

        on_progress({
            "type": "phase_done",
            "phase": phase,
            "status": result.status,
            "processed": result.processed_pages,
            "failed": result.failed_pages,
            "scoped": is_scoped,
        })

        return result

    except PhaseError:
        raise
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        if is_scoped:
            # Scoped failure shouldn't mark the whole phase as failed
            run.set_phase_status(phase, "partial")
        else:
            run.set_phase_status(phase, "failed")
        run.update(error=error_msg)
        on_progress({"type": "phase_error", "phase": phase, "error": error_msg, "scoped": is_scoped})
        return PhaseResult(
            phase=phase,
            status="failed",
            error=error_msg,
        )
    finally:
        lock.release()


def run_all(
    run: Run,
    options: dict[str, Any] | None = None,
    on_progress: ProgressCallback = null_progress,
    start_from: PhaseName | None = None,
) -> dict[PhaseName, PhaseResult]:
    """
    Run all phases sequentially.

    Args:
        run: The run to execute
        options: Shared options (phase-specific options keyed by phase name)
        on_progress: Progress callback
        start_from: Skip phases before this one (for resuming)

    Returns:
        Dict of phase → result
    """
    opts = options or {}
    results: dict[PhaseName, PhaseResult] = {}

    phases_to_run = PHASE_ORDER
    if start_from:
        idx = PHASE_ORDER.index(start_from)
        phases_to_run = PHASE_ORDER[idx:]

    run.update(status="running")

    for phase in phases_to_run:
        phase_opts = opts.get(phase, {})
        # Merge global options
        for k, v in opts.items():
            if k not in PHASE_ORDER and k not in phase_opts:
                phase_opts[k] = v

        result = run_phase(run, phase, options=phase_opts, on_progress=on_progress)
        results[phase] = result

        if result.status == "failed":
            run.update(status="failed")
            return results

    run.update(status="done")
    return results


def _get_phase_fn(phase: PhaseName):
    """Lazy import of phase execution functions."""
    if phase == "detection":
        from yomeru.phases.detection import run
        return run
    elif phase == "analysis":
        from yomeru.phases.analysis import run
        return run
    elif phase == "matching":
        from yomeru.phases.matching import run
        return run
    elif phase == "inpainting":
        from yomeru.phases.inpainting import run
        return run
    elif phase == "rendering":
        from yomeru.phases.rendering import run
        return run
    else:
        raise PhaseError(f"Unknown phase: {phase}")
