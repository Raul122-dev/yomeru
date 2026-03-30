from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import config
from core.models import COMIC_FORMATS

router = APIRouter(prefix="/config", tags=["config"])


class ProviderUpdate(BaseModel):
    api_key: str = ""
    base_url: str = ""


class DefaultsUpdate(BaseModel):
    model:           str = ""
    format:          str = "auto"
    provider:        str = ""
    ui_language:     str = "English"
    source_language: str = "auto"


@router.get("")
def get_config():
    return config.load()


@router.patch("/providers/{provider}")
def update_provider(provider: str, body: ProviderUpdate):
    cfg = config.load()
    if provider not in cfg["providers"]:
        cfg["providers"][provider] = {}
    cfg["providers"][provider]["api_key"]  = body.api_key
    cfg["providers"][provider]["base_url"] = body.base_url
    config.save(cfg)
    return cfg["providers"][provider]


@router.patch("/defaults")
def update_defaults(body: DefaultsUpdate):
    cfg = config.load()
    if body.model:
        cfg["defaults"]["model"] = body.model
    cfg["defaults"]["format"]          = body.format
    cfg["defaults"]["ui_language"]     = body.ui_language
    cfg["defaults"]["source_language"] = body.source_language
    if body.provider:
        cfg["defaults"]["provider"] = body.provider
    config.save(cfg)
    return cfg["defaults"]


@router.get("/providers")
def list_providers():
    """Which providers are configured and ready."""
    cfg = config.load()
    meta = {
        "anthropic": {"label": "Anthropic",       "needs": "api_key"},
        "openai":    {"label": "OpenAI",           "needs": "api_key"},
        "google":    {"label": "Google",           "needs": "api_key"},
        "custom":    {"label": "Custom endpoint",  "needs": "base_url"},
    }
    result = []
    for key, m in meta.items():
        prov = cfg["providers"].get(key, {})
        ready = bool(prov.get(m["needs"], "").strip())
        result.append({"key": key, "label": m["label"], "ready": ready, "needs": m["needs"]})
    return result


@router.get("/models/local")
async def list_local_models():
    """Query the configured custom endpoint for available models."""
    base_url = config.get_custom_base_url()
    if not base_url:
        raise HTTPException(400, "no custom endpoint configured — set base_url in Settings")

    base_url = base_url.rstrip("/")
    # try Ollama-native /api/tags first, fall back to OpenAI /v1/models
    for url in [f"{base_url}/api/tags", f"{base_url}/v1/models"]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                # Ollama format
                if "models" in data:
                    return [{"id": m["name"], "name": m["name"]} for m in data["models"]]
                # OpenAI format
                if "data" in data:
                    return [{"id": m["id"], "name": m["id"]} for m in data["data"]]
        except Exception:
            continue

    raise HTTPException(502, f"cannot reach {base_url} — check the url in Settings")


@router.get("/formats")
def list_formats():
    return [
        {"key": k, "name": v.name, "reading_order": v.reading_order, "origin": v.origin}
        for k, v in COMIC_FORMATS.items()
    ]