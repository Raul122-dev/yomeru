from __future__ import annotations
import json
import sys
import os
from pathlib import Path
from typing import Any


from yomeru.core.paths import (  # noqa: F401  (re-exported)
    CONFIG_FILE, DATA_DIR, MODELS_DIR, RUNS_DIR, STATIC_DIR, ensure_dirs,
)

PORT = int(os.environ.get("PORT", 7788))
HOST = os.environ.get("HOST", "127.0.0.1")


# ── provider schema ────────────────────────────────────────────────────────────
# Four provider slots:
#   anthropic   — Claude models. api_key required.
#   openai      — GPT models. api_key required.
#   google      — Gemini models. api_key required.
#   custom      — Any OpenAI-compatible endpoint: Ollama (local/cloud),
#                 LM Studio, vLLM, DeepSeek, Together, Groq, self-hosted, etc.
#                 base_url required. api_key optional (needed for cloud services).
#
# litellm routing:
#   anthropic  → model as-is            e.g. "claude-sonnet-4-5"
#   openai     → model as-is            e.g. "gpt-4o"
#   google     → "gemini/{model}"       e.g. "gemini/gemini-1.5-flash"
#   custom     → "openai/{model}"       e.g. "openai/qwen3.5-32k"
#                + api_base             e.g. "http://localhost:11434/v1"

_DEFAULTS: dict[str, Any] = {
    "providers": {
        "anthropic": {"api_key": ""},
        "openai":    {"api_key": ""},
        "google":    {"api_key": ""},
        "custom":    {"base_url": "", "api_key": ""},
    },
    "defaults": {
        "model":           "google/gemini-3.1-flash-image-preview",
        "format":          "auto",
        "provider":        "custom",
        "source_language": "auto",
        "target_language": "Spanish",
    },
    "translation": {
        "enabled":    False,   # use separate model for translation
        "model":      "",
        "provider":   "",      # same provider options as main
        "base_url":   "",      # override base_url for translation model
        "api_key":    "",      # override api_key for translation model
    },
    "phases": {
        "detection": {
            "backend":   "auto",
            "threshold": 0.4,
        },
        "matching": {
            "backend":          "hungarian",
            "ocr_weight":       0.4,
            "spatial_weight":   0.4,
            "position_weight":  0.2,
            "min_score":        0.05,
        },
        "inpainting": {
            "backend": "auto",
        },
        "rendering": {
            "backend":        "pil",
            "use_translation": True,
            "skip_sfx":       True,
            "skip_narration": False,
            "padding":        12,
            "min_font_size":  9,
            "max_font_size":  30,
        },
    },
}


class ConfigStore:
    def load(self) -> dict:
        if not CONFIG_FILE.exists():
            CONFIG_FILE.write_text(json.dumps(_DEFAULTS, indent=2))
            return json.loads(json.dumps(_DEFAULTS))
        try:
            data = json.loads(CONFIG_FILE.read_text())
            # forward-migrate: rename ollama → custom if present
            if "ollama" in data.get("providers", {}):
                old = data["providers"].pop("ollama")
                if "custom" not in data["providers"]:
                    data["providers"]["custom"] = {
                        "base_url": old.get("base_url", ""),
                        "api_key":  old.get("api_key", ""),
                    }
                CONFIG_FILE.write_text(json.dumps(data, indent=2))
            # forward-migrate: rename ui_language → target_language
            defaults = data.get("defaults", {})
            if "ui_language" in defaults and "target_language" not in defaults:
                defaults["target_language"] = defaults.pop("ui_language")
                CONFIG_FILE.write_text(json.dumps(data, indent=2))
            elif "ui_language" in defaults:
                del defaults["ui_language"]
            # fill missing keys from defaults
            for section, values in _DEFAULTS.items():
                if section not in data:
                    data[section] = values
                elif isinstance(values, dict):
                    for k, v in values.items():
                        if k not in data[section]:
                            data[section][k] = v
            return data
        except json.JSONDecodeError:
            # Keep the broken file instead of letting the next save() wipe the
            # user's keys with defaults.
            import time
            backup = CONFIG_FILE.with_name(f"config.corrupt-{int(time.time())}.json")
            CONFIG_FILE.replace(backup)
            print(f"  [config] config.json was invalid JSON, moved to {backup.name}", file=sys.stderr)
            return self.load()

    def save(self, data: dict) -> None:
        tmp = CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(CONFIG_FILE)

    def get_provider(self, provider: str) -> dict:
        return self.load()["providers"].get(provider, {})

    def get_custom_base_url(self) -> str:
        return self.get_provider("custom").get("base_url", "")

    def get_defaults(self) -> dict:
        return self.load().get("defaults", _DEFAULTS["defaults"])

    def get_translation(self) -> dict:
        return self.load().get("translation", _DEFAULTS["translation"])

    def get_phases(self) -> dict:
        return self.load().get("phases", _DEFAULTS["phases"])


config = ConfigStore()


# ── litellm model string builder ───────────────────────────────────────────────

def build_litellm_model(provider: str, model: str) -> tuple[str, str | None]:
    """
    Returns (litellm_model_string, api_base).

    provider: anthropic | openai | google | custom
    model:    raw model name as typed by user (no prefix needed)
    """
    cfg = config.load()

    if provider == "anthropic":
        key = cfg["providers"]["anthropic"].get("api_key", "")
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        return model, None

    if provider == "openai":
        key = cfg["providers"]["openai"].get("api_key", "")
        if key:
            os.environ["OPENAI_API_KEY"] = key
        return model, None

    if provider == "google":
        key = cfg["providers"]["google"].get("api_key", "")
        if key:
            os.environ["GEMINI_API_KEY"] = key
        # litellm expects "gemini/model-name"
        m = model if model.startswith("gemini/") else f"gemini/{model}"
        return m, None

    if provider == "custom":
        prov = cfg["providers"]["custom"]
        base_url = prov.get("base_url", "").rstrip("/")
        api_key  = prov.get("api_key", "").strip()
        if not base_url:
            raise ValueError("custom provider has no base_url configured — set it in Settings")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        # Always use openai/ prefix so litellm routes through OpenAI-compat path
        # using api_base. Without it, litellm recognizes prefixes like "google/"
        # or "anthropic/" as its own native providers and ignores api_base entirely.
        # litellm strips "openai/" before sending the model name to the endpoint,
        # so OpenRouter receives "google/gemini-2.5-flash-preview" correctly.
        litellm_model = model if model.startswith("openai/") else f"openai/{model}"
        os.environ["OPENAI_API_KEY"] = api_key or "local"
        return litellm_model, base_url

    raise ValueError(f"unknown provider '{provider}'")