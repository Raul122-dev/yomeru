"""
Backend registry — the "plugin" point of every phase.

A phase (stages/<stage>/phase.py) is a thin orchestrator: it loads the effective
inputs (runs/artifacts), builds a typed request (pipeline/contracts), calls the
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

# Version of the contract between yomeru and its plugins (pipeline/contracts +
# this registry). A plugin declares the range it supports in `api`; bump the
# major when a contract changes incompatibly.
PLUGIN_API = 1

# Modules that register the built-in backends (imported lazily, on first lookup)
_BUILTINS: dict[str, list[str]] = {
    "detection": ["yomeru.stages.detection.plugins"],
    "analysis": ["yomeru.stages.analysis.plugins"],
    "matching": ["yomeru.stages.matching.plugins"],
    "inpainting": ["yomeru.stages.inpainting.plugins"],
    "rendering": ["yomeru.stages.rendering.plugins"],
}


@dataclass(frozen=True)
class BackendSpec:
    phase: str
    name: str
    factory: Callable[[BaseModel], Any]
    options_model: type[BaseModel]
    needs_gpu: bool
    version: str                       # the plugin's own version (shown, stored in run snapshots)
    description: str
    title: str = ""                    # human name for the settings UI (defaults to `name`)
    schema_version: int = 1            # version of its options model
    migrate: Callable[[int, dict], dict] | None = None  # (from_version, options) -> options of from_version+1
    api: tuple[int, int] = (1, 2)      # supported PLUGIN_API range [min, max)

    @property
    def compatible(self) -> bool:
        return self.api[0] <= PLUGIN_API < self.api[1]

    def upgrade(self, options: dict, from_version: int) -> dict:
        """Stored options of an older schema version → current, step by step."""
        if from_version > self.schema_version:
            raise ValueError(f"{self.phase} backend '{self.name}' options are from a newer version "
                             f"({from_version} > {self.schema_version}); update the plugin")
        for v in range(from_version, self.schema_version):
            if self.migrate is None:
                raise ValueError(f"{self.phase} backend '{self.name}' has no migration from v{v}")
            options = self.migrate(v, dict(options))
        return options


_REGISTRY: dict[str, dict[str, BackendSpec]] = {}
_instances: dict[tuple[str, str, str], Any] = {}
_lock = threading.Lock()


class UnknownBackend(ValueError):
    pass


def register(phase: PhaseName, name: str, *, options: type[BaseModel], needs_gpu: bool = False,
             version: str = "1.0.0", description: str = "", title: str = "", schema_version: int = 1,
             migrate: Callable[[int, dict], dict] | None = None, api: tuple[int, int] = (1, 2)):
    """Class/factory decorator: make a backend selectable as `<phase>.backend = name`.

    schema_version/migrate: bump `schema_version` when the options model changes
    incompatibly and give `migrate(from_version, options)` that upgrades one
    step; stored settings and run snapshots carry the version they were saved with.
    api: range of PLUGIN_API this backend works with; outside it the backend is
    listed as incompatible and cannot be selected."""
    def deco(factory):
        _REGISTRY.setdefault(phase, {})[name] = BackendSpec(
            phase=phase, name=name, factory=factory, options_model=options,
            needs_gpu=needs_gpu, version=version,
            description=description or (factory.__doc__ or "").strip().split("\n")[0],
            schema_version=schema_version, migrate=migrate, api=api, title=title or name,
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
    if not spec.compatible:
        raise UnknownBackend(f"{phase} backend '{name}' needs plugin API {spec.api}, yomeru has {PLUGIN_API}")
    opts = spec.options_model.model_validate(options or {})
    key = (phase, name, opts.model_dump_json())
    with _lock:
        if key not in _instances:
            _instances[key] = spec.factory(opts)
        return spec, _instances[key]


def list_backends(phase: PhaseName) -> list[dict]:
    """For the settings UI: name, description and the options schema."""
    return [
        {"name": s.name, "title": s.title or s.name, "description": s.description, "needs_gpu": s.needs_gpu,
         "version": s.version, "schema_version": s.schema_version, "compatible": s.compatible,
         "options": s.options_model.model_json_schema(),
         "defaults": s.options_model().model_dump()}
        for s in specs(phase).values()
    ]
