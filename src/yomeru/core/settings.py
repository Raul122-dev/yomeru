"""Configuration: schema, storage, migrations and resolution.

Single source of truth for settings. Stored as data/config.json.

Model access is reduced to two wire protocols:
  - "openai"    → OpenAI Chat Completions API (OpenAI, OpenRouter, Ollama,
                  LM Studio, vLLM, DeepSeek, Groq, ...)
  - "anthropic" → Anthropic Messages API (Anthropic, or any compatible proxy)
A *connection* is one of those protocols + base_url + api_key. The official
OpenAI/Anthropic endpoints are just connections with their default URLs.

Resolution order for a run: defaults → global settings → preset → run snapshot
→ request overrides. The effective settings are copied into the run when it is
created, so editing Settings later never changes an existing run.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from yomeru.core.paths import CONFIG_FILE

SCHEMA_VERSION = 2

Protocol = Literal["openai", "anthropic"]

DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


# ── schema ───────────────────────────────────────────────────────────────────

class Connection(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    protocol: Protocol = "openai"
    base_url: str = ""
    api_key: str = ""

    @field_validator("base_url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip().rstrip("/")

    def effective_base_url(self) -> str:
        return self.base_url or DEFAULT_BASE_URLS[self.protocol]


class ModelRef(BaseModel):
    """A model on a given connection."""
    connection_id: str = ""
    model: str = ""

    def is_set(self) -> bool:
        return bool(self.connection_id and self.model)


class LanguageSettings(BaseModel):
    source: str = "auto"
    target: str = "Spanish"
    comic_format: str = "auto"


class DetectionSettings(BaseModel):
    """Detector = a registered backend. It must emit the core/labels vocabulary
    (bubble / text_bubble / text_free): every later phase is keyed on it."""
    backend: str = "ogkalu"
    options: dict = Field(default_factory=dict)
    threshold: float = Field(default=0.4, ge=0.05, le=0.95)

    @field_validator("backend", mode="before")
    @classmethod
    def _legacy(cls, v: object) -> object:
        # "auto" / retired "ctd" in old configs and runs → the default detector
        return "ogkalu" if v in (None, "auto", "ctd") else v

    @model_validator(mode="after")
    def _known_backend(self):
        from yomeru.plugins import get_spec
        spec = get_spec("detection", self.backend)
        self.options = spec.options_model.model_validate(self.options).model_dump()
        return self


class MatchingSettings(BaseModel):
    ocr_weight: float = Field(default=0.4, ge=0, le=1)
    spatial_weight: float = Field(default=0.4, ge=0, le=1)
    min_score: float = Field(default=0.05, ge=0, le=1)


class InpaintingSettings(BaseModel):
    """Inpainting technique = a registered backend (yomeru/plugins) + its options."""
    backend: str = "classic"
    options: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _legacy_backend(cls, data):
        # v1/v2 configs and old runs stored the engine name; it maps onto the
        # classic backend ("opencv" = OpenCV everywhere, else LaMa for free text).
        if isinstance(data, dict) and data.get("backend") in ("auto", "lama", "opencv"):
            data = {**data, "backend": "classic",
                    "options": {"free_text": "opencv" if data["backend"] == "opencv" else "lama"}}
        return data

    @model_validator(mode="after")
    def _known_backend(self):
        from yomeru.plugins import get_spec
        spec = get_spec("inpainting", self.backend)  # raises UnknownBackend
        self.options = spec.options_model.model_validate(self.options).model_dump()
        return self


class RenderingSettings(BaseModel):
    """Rendering technique = a registered backend (yomeru/plugins) + its options."""
    use_translation: bool = True
    backend: str = "scanline"
    options: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_backend(self):
        from yomeru.plugins import get_spec
        spec = get_spec("rendering", self.backend)  # raises UnknownBackend
        self.options = spec.options_model.model_validate(self.options).model_dump()
        return self


class PipelineSettings(BaseModel):
    """Everything a run needs. This is what presets and run snapshots store."""
    analysis_model: ModelRef = Field(default_factory=ModelRef)
    translation_model: ModelRef = Field(default_factory=ModelRef)  # empty → analysis model translates
    language: LanguageSettings = Field(default_factory=LanguageSettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    inpainting: InpaintingSettings = Field(default_factory=InpaintingSettings)
    rendering: RenderingSettings = Field(default_factory=RenderingSettings)


class Preset(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    settings: PipelineSettings


class AppConfig(BaseModel):
    schema_version: int = SCHEMA_VERSION
    connections: list[Connection] = []
    settings: PipelineSettings = Field(default_factory=PipelineSettings)
    presets: list[Preset] = []

    def connection(self, connection_id: str) -> Connection | None:
        return next((c for c in self.connections if c.id == connection_id), None)


# ── migrations ───────────────────────────────────────────────────────────────

def _migrate_v1(old: dict) -> dict:
    """v1 (providers/defaults/translation/phases) → v2."""
    providers = old.get("providers", {}) or {}
    defaults = old.get("defaults", {}) or {}
    phases = old.get("phases", {}) or {}
    translation = old.get("translation", {}) or {}

    connections: list[dict] = []
    ids: dict[str, str] = {}

    def add(key: str, name: str, protocol: str, base_url: str, api_key: str) -> None:
        connections.append({"id": key, "name": name, "protocol": protocol,
                            "base_url": base_url, "api_key": api_key})
        ids[key] = key

    custom = providers.get("custom") or providers.get("ollama") or {}
    if custom.get("base_url"):
        url = custom["base_url"].rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        name = "OpenRouter" if "openrouter.ai" in url else "Custom"
        add("custom", name, "openai", url, custom.get("api_key", ""))
    if (providers.get("openai") or {}).get("api_key"):
        add("openai", "OpenAI", "openai", "", providers["openai"]["api_key"])
    if (providers.get("anthropic") or {}).get("api_key"):
        add("anthropic", "Anthropic", "anthropic", providers["anthropic"].get("base_url", ""),
            providers["anthropic"]["api_key"])
    # Google direct access is dropped: use it through an OpenAI-compatible
    # endpoint (OpenRouter or Google's own /v1beta/openai) instead.

    provider = defaults.get("provider") or "custom"
    conn = ids.get(provider) or (connections[0]["id"] if connections else "")
    det = phases.get("detection", {})
    mat = phases.get("matching", {})
    inp = phases.get("inpainting", {})
    ren = phases.get("rendering", {})
    settings = {
        "analysis_model": {"connection_id": conn, "model": defaults.get("model", "")},
        "translation_model": (
            {"connection_id": ids.get(translation.get("provider") or provider, conn),
             "model": translation.get("model", "")}
            if translation.get("enabled") and translation.get("model") else {}
        ),
        "language": {
            "source": defaults.get("source_language", "auto"),
            "target": defaults.get("target_language", "Spanish"),
            "comic_format": defaults.get("format", "auto"),
        },
        "detection": {k: det[k] for k in ("backend", "threshold") if k in det},
        "matching": {k: mat[k] for k in ("ocr_weight", "spatial_weight", "min_score") if k in mat},
        "inpainting": {"backend": inp.get("backend", "auto")},
        "rendering": {"use_translation": ren.get("use_translation", True)},
    }
    return {"schema_version": 2, "connections": connections, "settings": settings, "presets": []}


def migrate(data: dict) -> dict:
    if data.get("schema_version", 1) < 2:
        data = _migrate_v1(data)
    return data


# ── storage ──────────────────────────────────────────────────────────────────

class ConfigStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def load(self) -> AppConfig:
        with self._lock:
            if not CONFIG_FILE.exists():
                cfg = AppConfig()
                self.save(cfg)
                return cfg
            try:
                raw = json.loads(CONFIG_FILE.read_text())
            except json.JSONDecodeError:
                backup = CONFIG_FILE.with_name(f"config.corrupt-{int(time.time())}.json")
                CONFIG_FILE.replace(backup)
                print(f"  [config] config.json was invalid JSON, moved to {backup.name}", file=sys.stderr)
                return self.load()
            version = raw.get("schema_version", 1)
            if version < SCHEMA_VERSION:
                backup = CONFIG_FILE.with_name(f"config.v{version}.bak.json")
                if not backup.exists():
                    backup.write_text(json.dumps(raw, indent=2))
                cfg = AppConfig.model_validate(migrate(raw))
                self.save(cfg)
                print(f"  [config] migrated config.json v{version} → v{SCHEMA_VERSION} "
                      f"(backup: {backup.name})", file=sys.stderr)
                return cfg
            return AppConfig.model_validate(raw)

    def save(self, cfg: AppConfig) -> None:
        with self._lock:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(cfg.model_dump_json(indent=2))
            tmp.replace(CONFIG_FILE)

    def update(self, fn) -> AppConfig:
        """Load → mutate with fn(cfg) → validate → save, under one lock."""
        with self._lock:
            cfg = self.load()
            fn(cfg)
            cfg = AppConfig.model_validate(cfg.model_dump())
            self.save(cfg)
            return cfg


store = ConfigStore()


# ── resolution ───────────────────────────────────────────────────────────────

def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_settings(preset_id: str | None = None, overrides: dict | None = None) -> PipelineSettings:
    """Effective pipeline settings for a NEW run: global → preset → overrides."""
    cfg = store.load()
    data = cfg.settings.model_dump()
    if preset_id:
        preset = next((p for p in cfg.presets if p.id == preset_id), None)
        if preset is None:
            raise ValueError(f"unknown preset {preset_id!r}")
        data = _deep_merge(data, preset.settings.model_dump())
    if overrides:
        data = _deep_merge(data, overrides)
    return PipelineSettings.model_validate(data)


# ── run snapshots (+ legacy runs) ────────────────────────────────────────────

def settings_from_legacy_meta(meta: dict) -> PipelineSettings:
    """Build a snapshot for runs created before schema v2."""
    cfg = store.load()
    provider = meta.get("provider") or "custom"
    conn = cfg.connection(provider) or (cfg.connections[0] if cfg.connections else None)
    return PipelineSettings.model_validate({
        "analysis_model": {"connection_id": conn.id if conn else "", "model": meta.get("model", "")},
        "language": {
            "source": meta.get("source_language", "auto"),
            "target": meta.get("target_language", "Spanish"),
            "comic_format": meta.get("comic_format", "auto"),
        },
        "detection": {
            "backend": meta.get("detector_backend", "auto"),
            "threshold": meta.get("detector_threshold", 0.4),
        },
        "inpainting": {"backend": meta.get("inpainter_backend", "auto")},
    })


def run_settings(meta: dict) -> PipelineSettings:
    snap = meta.get("settings")
    if snap:
        return PipelineSettings.model_validate(snap)
    return settings_from_legacy_meta(meta)


# ── secrets in API responses ─────────────────────────────────────────────────

MASK = "••••"


def mask_key(key: str | None) -> str:
    if not key:
        return ""
    return MASK + key[-4:] if len(key) > 8 else MASK


def is_unchanged_secret(value: str | None) -> bool:
    return value is None or value.startswith(MASK)


def public_config(cfg: AppConfig) -> dict:
    data = cfg.model_dump()
    for c in data["connections"]:
        c["api_key"] = mask_key(c["api_key"])
        c["has_key"] = bool(c["api_key"])
    return data


_SLUG = re.compile(r"[^a-z0-9]+")


def new_connection_id(name: str, existing: set[str]) -> str:
    base = _SLUG.sub("-", name.lower()).strip("-")[:24] or "conn"
    cid, n = base, 2
    while cid in existing:
        cid, n = f"{base}-{n}", n + 1
    return cid
