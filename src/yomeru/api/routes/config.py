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
        cfg.settings = PipelineSettings.model_validate(merged)
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
        cfg.presets.append(Preset(name=body.name, settings=body.settings or cfg.settings))
    return public_config(store.update(fn))


@router.put("/presets/{pid}")
def update_preset(pid: str, body: PresetIn):
    def fn(cfg: AppConfig):
        preset = next((p for p in cfg.presets if p.id == pid), None)
        if preset is None:
            raise HTTPException(404, f"preset {pid!r} not found")
        preset.name = body.name
        if body.settings is not None:
            preset.settings = body.settings
    return public_config(store.update(fn))


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


@router.get("/formats")
def list_formats():
    return [
        {"key": k, "name": v.name, "reading_order": v.reading_order, "origin": v.origin}
        for k, v in COMIC_FORMATS.items()
    ]
