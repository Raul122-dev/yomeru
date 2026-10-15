"""Image-edit providers: adapters from `EditRequest` to one wire protocol.

An adapter is chosen by protocol, not by model: the model id is data the user
types (e.g. any image model on OpenRouter). Adapters ship here or in another
package through the `yomeru.edit_providers` entry point group:

    @register_provider("myservice")
    class MyService:
        local = False                      # True = uses this machine's GPU
        def __init__(self, base_url: str, api_key: str, model: str, quality: str = ""): ...
        def edit(self, req: EditRequest) -> EditResult: ...   # raises EditError subclasses
"""
from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Any, Callable

_BUILTINS = ["yomeru.lib.rendering.edit_providers.openrouter"]
_PROVIDERS: dict[str, Callable[..., Any]] = {}
_loaded = False


def register_provider(name: str):
    def deco(factory):
        _PROVIDERS[name] = factory
        return factory
    return deco


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for mod in _BUILTINS:
        importlib.import_module(mod)
    for ep in entry_points(group="yomeru.edit_providers"):
        try:
            ep.load()
        except Exception as e:   # a broken third-party adapter must not break rendering
            import sys
            print(f"  [image-edit] provider {ep.name!r} failed to load: {e}", file=sys.stderr)


def provider_names() -> list[str]:
    _load()
    return sorted(_PROVIDERS)


def make_provider(name: str, *, base_url: str, api_key: str, model: str, quality: str = ""):
    _load()
    if name not in _PROVIDERS:
        from yomeru.core.contracts import EditUnavailable
        raise EditUnavailable(f"no image-edit adapter '{name}' (available: {', '.join(sorted(_PROVIDERS))})")
    return _PROVIDERS[name](base_url=base_url, api_key=api_key, model=model, quality=quality)
