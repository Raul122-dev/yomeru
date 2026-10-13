"""Settings API: connections, global pipeline settings, presets."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from yomeru.core import llm
from yomeru.core.models import COMIC_FORMATS
from yomeru.core.settings import (
    AppConfig,
    Connection,
    PipelineSettings,
    Preset,
    Protocol,
    _deep_merge,
    require_available,
    is_unchanged_secret,
    new_connection_id,
    public_config,
    store,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
def get_config():
    return public_config(store.load())


# ── connections ──────────────────────────────────────────────────────────────

class ConnectionIn(BaseModel):
    name: str
    protocol: Protocol = "openai"
    base_url: str = ""
    api_key: str | None = None  # None / masked value → keep the stored key


def _conn_or_404(cfg: AppConfig, cid: str) -> Connection:
    conn = cfg.connection(cid)
    if conn is None:
        raise HTTPException(404, f"connection {cid!r} not found")
    return conn


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionIn):
    def fn(cfg: AppConfig):
        cid = new_connection_id(body.name, {c.id for c in cfg.connections})
        cfg.connections.append(Connection(
            id=cid, name=body.name, protocol=body.protocol, base_url=body.base_url,
            api_key="" if is_unchanged_secret(body.api_key) else (body.api_key or ""),
        ))
        # First connection becomes the default for analysis
        if not cfg.settings.analysis_model.connection_id:
            cfg.settings.analysis_model.connection_id = cid
    return public_config(store.update(fn))


@router.put("/connections/{cid}")
def update_connection(cid: str, body: ConnectionIn):
    def fn(cfg: AppConfig):
        conn = _conn_or_404(cfg, cid)
        conn.name, conn.protocol, conn.base_url = body.name, body.protocol, body.base_url
        if not is_unchanged_secret(body.api_key):
            conn.api_key = body.api_key or ""
    return public_config(store.update(fn))


@router.delete("/connections/{cid}")
def delete_connection(cid: str):
    def fn(cfg: AppConfig):
        _conn_or_404(cfg, cid)
        cfg.connections = [c for c in cfg.connections if c.id != cid]
        for ref in (cfg.settings.analysis_model, cfg.settings.translation_model):
            if ref.connection_id == cid:
                ref.connection_id = ""
    return public_config(store.update(fn))


@router.get("/connections/{cid}/models")
def connection_models(cid: str):
    conn = _conn_or_404(store.load(), cid)
    try:
        return llm.list_models(conn)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


@router.post("/connections/{cid}/test")
def connection_test(cid: str):
    return llm.test_connection(_conn_or_404(store.load(), cid))


@router.post("/connections/test")
def connection_test_unsaved(body: ConnectionIn):
    """Test a connection before saving it."""
    conn = Connection(name=body.name, protocol=body.protocol, base_url=body.base_url,
                      api_key=body.api_key or "")
    return llm.test_connection(conn)


# ── global pipeline settings ─────────────────────────────────────────────────

@router.patch("/settings")
def update_settings(patch: dict[str, Any]):
    """Deep-merge a partial PipelineSettings into the global settings."""
    def fn(cfg: AppConfig):
        merged = _deep_merge(cfg.settings.model_dump(), patch)
        cfg.settings = require_available(PipelineSettings.model_validate(merged))
    try:
        return public_config(store.update(fn))
    except ValueError as e:
        raise HTTPException(422, str(e))


# ── presets ──────────────────────────────────────────────────────────────────

class PresetIn(BaseModel):
    name: str
    settings: PipelineSettings | None = None  # None → snapshot of the current global settings


@router.post("/presets", status_code=201)
def create_preset(body: PresetIn):
    def fn(cfg: AppConfig):
        cfg.presets.append(Preset(name=body.name, settings=require_available(body.settings or cfg.settings)))
    try:
        return public_config(store.update(fn))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.put("/presets/{pid}")
def update_preset(pid: str, body: PresetIn):
    def fn(cfg: AppConfig):
        preset = next((p for p in cfg.presets if p.id == pid), None)
        if preset is None:
            raise HTTPException(404, f"preset {pid!r} not found")
        preset.name = body.name
        if body.settings is not None:
            preset.settings = require_available(body.settings)
    try:
        return public_config(store.update(fn))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.delete("/presets/{pid}")
def delete_preset(pid: str):
    def fn(cfg: AppConfig):
        cfg.presets = [p for p in cfg.presets if p.id != pid]
    return public_config(store.update(fn))


# ── backends (techniques per phase) ─────────────────────────────────────────

@router.get("/backends/{phase}")
def get_backends(phase: str):
    """Registered techniques for a phase, with each one's options schema."""
    from yomeru.plugins import list_backends
    if phase not in ("detection", "analysis", "matching", "inpainting", "rendering"):
        raise HTTPException(404, f"unknown phase {phase!r}")
    return list_backends(phase)  # type: ignore[arg-type]


# ── local vision models (Ollama on this machine) ────────────────────────────

_pulls: dict[str, dict] = {}   # model tag → {status, completed, total, error, done}
_pulls_lock = __import__("threading").Lock()


@router.get("/local-models")
def local_models(server: str | None = None):
    """Model server status, installed models, GPU memory and the suggested model."""
    from yomeru.lib.local_models import CATALOGUE, OLLAMA_URL, gpu_memory, ollama_status, suggest_model
    st = ollama_status(server or OLLAMA_URL)
    gpu = gpu_memory()
    sug = suggest_model(gpu and gpu["free_gb"])
    with _pulls_lock:
        pulls = {k: dict(v) for k, v in _pulls.items() if not v.get("done") or v.get("error")}
    return {
        **st,
        "server": server or OLLAMA_URL,
        "gpu": gpu,
        "suggested": {"tag": sug.tag, "note": sug.note},
        "catalogue": [{"tag": c.tag, "min_vram_gb": c.min_vram_gb, "note": c.note} for c in CATALOGUE],
        "pulls": pulls,
    }


class PullIn(BaseModel):
    model: str
    server: str | None = None


@router.post("/local-models/pull", status_code=202)
def local_models_pull(body: PullIn):
    """Start downloading a model in the background; poll GET /local-models."""
    import threading
    from yomeru.lib.local_models import OLLAMA_URL, LocalModelError, pull

    name = body.model.strip()
    if not name:
        raise HTTPException(422, "model is required")
    with _pulls_lock:
        cur = _pulls.get(name)
        if cur and not cur.get("done"):
            return {"started": False, "model": name}
        _pulls[name] = {"status": "starting", "completed": 0, "total": 0, "done": False, "error": None}

    layers: dict[str, tuple[int, int]] = {}   # digest → (completed, total): one bar for all files

    def progress(ev: dict) -> None:
        with _pulls_lock:
            p = _pulls[name]
            status = ev.get("status", p["status"])
            p["status"] = "downloading" if status.startswith("pulling ") and ev.get("digest") else status
            if ev.get("digest") and ev.get("total"):
                layers[ev["digest"]] = (ev.get("completed", 0), ev["total"])
                p["completed"] = sum(c for c, _ in layers.values())
                p["total"] = sum(t for _, t in layers.values())

    def work() -> None:
        try:
            pull(name, body.server or OLLAMA_URL, on_progress=progress)
            with _pulls_lock:
                _pulls[name].update(done=True, status="success")
        except (LocalModelError, Exception) as e:  # noqa: BLE001 — reported to the UI
            with _pulls_lock:
                _pulls[name].update(done=True, error=str(e))

    threading.Thread(target=work, daemon=True, name=f"pull-{name}").start()
    return {"started": True, "model": name}


@router.get("/formats")
def list_formats():
    return [
        {"key": k, "name": v.name, "reading_order": v.reading_order, "origin": v.origin}
        for k, v in COMIC_FORMATS.items()
    ]
