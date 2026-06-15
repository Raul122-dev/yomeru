from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from yomeru.core.config import config
from yomeru.core.models import COMIC_FORMATS

router = APIRouter(prefix="/config", tags=["config"])


class ProviderUpdate(BaseModel):
    api_key: str = ""
    base_url: str = ""


class DefaultsUpdate(BaseModel):
    model: str | None = None
    format: str | None = None
    provider: str | None = None
    source_language: str | None = None
    target_language: str | None = None


class TranslationUpdate(BaseModel):
    enabled: bool | None = None
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class PhasesUpdate(BaseModel):
    detection: dict | None = None
    matching: dict | None = None
    inpainting: dict | None = None
    rendering: dict | None = None


@router.get("")
def get_config():
    return config.load()


@router.patch("/providers/{provider}")
def update_provider(provider: str, body: ProviderUpdate):
    cfg = config.load()
    if provider not in cfg["providers"]:
        cfg["providers"][provider] = {}
    cfg["providers"][provider]["api_key"] = body.api_key
    cfg["providers"][provider]["base_url"] = body.base_url
    config.save(cfg)
    return cfg["providers"][provider]


@router.patch("/defaults")
def update_defaults(body: DefaultsUpdate):
    cfg = config.load()
    defaults = cfg.setdefault("defaults", {})
    if body.model is not None:
        defaults["model"] = body.model
    if body.format is not None:
        defaults["format"] = body.format
    if body.provider is not None:
        defaults["provider"] = body.provider
    if body.source_language is not None:
        defaults["source_language"] = body.source_language
    if body.target_language is not None:
        defaults["target_language"] = body.target_language
    config.save(cfg)
    return defaults


@router.patch("/translation")
def update_translation(body: TranslationUpdate):
    """Update translation model settings."""
    cfg = config.load()
    trans = cfg.setdefault("translation", {})
    if body.enabled is not None:
        trans["enabled"] = body.enabled
    if body.model is not None:
        trans["model"] = body.model
    if body.provider is not None:
        trans["provider"] = body.provider
    if body.base_url is not None:
        trans["base_url"] = body.base_url
    if body.api_key is not None:
        trans["api_key"] = body.api_key
    config.save(cfg)
    return trans


@router.patch("/phases")
def update_phases(body: PhasesUpdate):
    """Update phase-specific settings."""
    cfg = config.load()
    phases = cfg.setdefault("phases", {})
    if body.detection is not None:
        phases.setdefault("detection", {}).update(body.detection)
    if body.matching is not None:
        phases.setdefault("matching", {}).update(body.matching)
    if body.inpainting is not None:
        phases.setdefault("inpainting", {}).update(body.inpainting)
    if body.rendering is not None:
        phases.setdefault("rendering", {}).update(body.rendering)
    config.save(cfg)
    return phases
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
    return await _fetch_models(base_url)


@router.get("/models/test-connection")
async def test_connection():
    """Test that the custom endpoint is reachable and responds."""
    base_url = config.get_custom_base_url()
    if not base_url:
        return {"ok": False, "error": "no base_url configured"}

    base_url = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Try common health/model endpoints
            for url in [f"{base_url}/api/tags", f"{base_url}/v1/models", f"{base_url}/health"]:
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return {"ok": True, "endpoint": url, "status": r.status_code}
                except Exception:
                    continue
        return {"ok": False, "error": f"endpoint not responding at {base_url}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _fetch_models(base_url: str) -> list[dict]:
    """Fetch models from an OpenAI-compatible or Ollama endpoint."""
    base_url = base_url.rstrip("/")
    for url in [f"{base_url}/api/tags", f"{base_url}/v1/models"]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                # Ollama format
                if "models" in data:
                    return [
                        {"id": m["name"], "name": m["name"], "vision": _is_vision_model(m["name"])}
                        for m in data["models"]
                    ]
                # OpenAI format (OpenRouter, LM Studio, etc.)
                if "data" in data:
                    return [
                        {"id": m["id"], "name": m.get("name", m["id"]), "vision": _is_vision_model(m["id"])}
                        for m in data["data"]
                    ]
        except Exception:
            continue

    raise HTTPException(502, f"cannot reach {base_url} — check the url in Settings")


def _is_vision_model(model_id: str) -> bool | None:
    """
    Heuristic check for vision support based on model name.
    Returns True/False for known models, None for unknown.
    """
    model_lower = model_id.lower()

    # Known vision models (patterns)
    vision_patterns = [
        "vision", "vl", "image", "-v", "4o", "gpt-4-turbo",
        "gemini", "claude-3", "claude-sonnet", "claude-opus",
        "llava", "qwen-vl", "qwen2-vl", "minicpm-v",
        "internvl", "cogvlm", "pixtral", "molmo",
    ]
    # Known non-vision models
    no_vision_patterns = [
        "embed", "whisper", "tts", "dall-e", "codestral",
        "mistral-small", "mistral-7b", "mixtral",
    ]

    for p in no_vision_patterns:
        if p in model_lower:
            return False
    for p in vision_patterns:
        if p in model_lower:
            return True
    return None  # unknown


@router.get("/capabilities")
def get_capabilities():
    """Return system capabilities (available detectors, inpainters, device)."""
    status_file = Path(__file__).parent.parent.parent / "typesetting_status.json"
    if not status_file.exists():
        return {
            "ready": False,
            "message": "Run setup_typesetting.py first",
            "detectors": [],
            "device": "cpu",
        }
    status = json.loads(status_file.read_text())
    from yomeru.core.typesetting.stages.detection.ctd import CTDDetector
    from yomeru.core.typesetting.stages.inpainting import lama_available
    detectors = [
        {
            "key": "ogkalu",
            "label": "ogkalu RT-DETR",
            "available": True,
            "note": "HuggingFace model, downloads on first use.",
        },
        {
            "key": "ctd",
            "label": "CTD (Comic Text Detector)",
            "available": CTDDetector.is_available(),
            "note": "Pixel-level masks for better inpainting.",
        },
    ]
    return {
        "ready": status.get("torch", False),
        "device": status.get("device", "cpu"),
        "detectors": detectors,
        "inpainter": "lama" if lama_available() else "opencv",
        "lama_ready": lama_available(),
        "message": None if status.get("torch", False) else "Run setup first",
    }


@router.get("/formats")
def list_formats():
    return [
        {"key": k, "name": v.name, "reading_order": v.reading_order, "origin": v.origin}
        for k, v in COMIC_FORMATS.items()
    ]