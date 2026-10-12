"""
Backend registry — the "plugin" point of every phase.

A phase (phases/<phase>.py) is a thin orchestrator: it loads the effective
inputs (core/artifacts), builds a typed request (core/contracts), calls the
selected backend once per page and persists the result. The *technique* lives
in a backend registered here and selected by name in the run's settings:

    @register("inpainting", "classic", options=ClassicOptions, needs_gpu=True)
    class ClassicInpainter:
        def __init__(self, options: ClassicOptions): ...
        def inpaint_page(self, req: InpaintRequest) -> InpaintResult: ...

Adding a technique = one module with one registered class; nothing else in the
pipeline changes. Backends never touch the run, paths, meta.json or progress
events (orchestrators own those, so cancellation and editors keep working).
"""
from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel

PhaseName = Literal["detection", "analysis", "matching", "inpainting", "rendering"]

# Modules that register the built-in backends (imported lazily, on first lookup)
_BUILTINS: dict[str, list[str]] = {
    "detection": ["yomeru.plugins.detection"],
    "inpainting": ["yomeru.plugins.inpainting"],
}


@dataclass(frozen=True)
class BackendSpec:
    phase: str
    name: str
    factory: Callable[[BaseModel], Any]
    options_model: type[BaseModel]
    needs_gpu: bool
    version: str
    description: str


_REGISTRY: dict[str, dict[str, BackendSpec]] = {}
_instances: dict[tuple[str, str, str], Any] = {}
_lock = threading.Lock()


class UnknownBackend(ValueError):
    pass


def register(phase: PhaseName, name: str, *, options: type[BaseModel], needs_gpu: bool = False,
             version: str = "1", description: str = ""):
    """Class/factory decorator: make a backend selectable as `<phase>.backend = name`."""
    def deco(factory):
        _REGISTRY.setdefault(phase, {})[name] = BackendSpec(
            phase=phase, name=name, factory=factory, options_model=options,
            needs_gpu=needs_gpu, version=version,
            description=description or (factory.__doc__ or "").strip().split("\n")[0],
        )
        return factory
    return deco


def _load_builtins(phase: str) -> None:
    for mod in _BUILTINS.get(phase, []):
        importlib.import_module(mod)


def specs(phase: PhaseName) -> dict[str, BackendSpec]:
    _load_builtins(phase)
    return _REGISTRY.get(phase, {})


def get_spec(phase: PhaseName, name: str) -> BackendSpec:
    s = specs(phase).get(name)
    if s is None:
        raise UnknownBackend(f"no {phase} backend '{name}' (available: {', '.join(specs(phase)) or 'none'})")
    return s


def get_backend(phase: PhaseName, name: str, options: dict | None = None) -> tuple[BackendSpec, Any]:
    """Validated, cached backend instance (one per phase/name/options)."""
    spec = get_spec(phase, name)
    opts = spec.options_model.model_validate(options or {})
    key = (phase, name, opts.model_dump_json())
    with _lock:
        if key not in _instances:
            _instances[key] = spec.factory(opts)
        return spec, _instances[key]


def list_backends(phase: PhaseName) -> list[dict]:
    """For the settings UI: name, description and the options schema."""
    return [
        {"name": s.name, "description": s.description, "needs_gpu": s.needs_gpu,
         "version": s.version, "options": s.options_model.model_json_schema()}
        for s in specs(phase).values()
    ]
