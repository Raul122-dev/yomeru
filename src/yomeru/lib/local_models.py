"""
Local vision models — find a model server on this machine and talk to it.

yomeru does not ship or run a model server itself: it uses one the user
already has (Ollama by default; llama.cpp `llama-server` and LM Studio are
detected too, through their OpenAI-compatible API). Everything here is plain
HTTP (httpx) — no extra dependency.

Ollama is driven through its native API because it is the one that, for
vision models, constrains the reply to a JSON schema (`format`), reports
download progress (`/api/pull`) and frees VRAM on demand (`keep_alive: 0`).
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx

OLLAMA_URL = "http://127.0.0.1:11434"
TIMEOUT = httpx.Timeout(600.0, connect=3.0)  # a local 9B model can take minutes per page


class LocalModelError(RuntimeError):
    pass


# ── catalogue: which model for how much free VRAM ──────────────────────────────
# Sizes are Ollama Q4 downloads + room for one large manga page (image tokens
# and KV cache). Qwen3.5 has native vision; Qwen3-VL is the older generation.

@dataclass(frozen=True)
class Suggested:
    tag: str
    min_vram_gb: float
    note: str


CATALOGUE: tuple[Suggested, ...] = (
    Suggested("qwen3.6:27b", 22.0, "best quality that fits a 24 GB card"),
    Suggested("qwen3.5:9b", 9.5, "default for 12-16 GB cards"),
    Suggested("qwen3.5:4b", 5.5, "8 GB cards"),
    Suggested("qwen3.5:2b", 3.5, "6 GB cards"),
    Suggested("qwen3.5:0.8b", 0.0, "CPU / very small GPUs — expect weak translations"),
)


def suggest_model(free_vram_gb: float | None) -> Suggested:
    """Largest catalogued model that fits; CPU-only machines get the smallest."""
    if free_vram_gb is None:
        return CATALOGUE[-1]
    return next(s for s in CATALOGUE if free_vram_gb >= s.min_vram_gb)


def gpu_memory() -> dict | None:
    """{name, total_gb, free_gb} of GPU 0, or None without CUDA (torch is
    already a dependency for detection/inpainting)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        free, total = torch.cuda.mem_get_info(0)
        return {"name": torch.cuda.get_device_name(0),
                "total_gb": round(total / 1e9, 1), "free_gb": round(free / 1e9, 1)}
    except Exception:
        return None


# ── Ollama ─────────────────────────────────────────────────────────────────────

def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url.rstrip("/"), timeout=TIMEOUT)


def ollama_status(base_url: str = OLLAMA_URL) -> dict:
    """{running, version, models:[{name, size_gb, vision}]} — never raises."""
    try:
        with _client(base_url) as c:
            version = c.get("/api/version").json().get("version")
            models = []
            for m in c.get("/api/tags").json().get("models", []):
                models.append({"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                               "vision": _has_vision(c, m["name"])})
            return {"running": True, "version": version, "models": models}
    except Exception as e:
        return {"running": False, "error": f"{type(e).__name__}: {e}", "models": []}


def _has_vision(c: httpx.Client, name: str) -> bool | None:
    try:
        caps = c.post("/api/show", json={"model": name}).json().get("capabilities")
        return ("vision" in caps) if isinstance(caps, list) else None
    except Exception:
        return None


def pull(name: str, base_url: str = OLLAMA_URL,
         on_progress: Callable[[dict], None] | None = None) -> None:
    """Download a model; `on_progress` gets {status, completed, total}."""
    with _client(base_url) as c, c.stream("POST", "/api/pull", json={"model": name, "stream": True}) as r:
        if r.status_code != 200:
            raise LocalModelError(f"pull {name}: HTTP {r.status_code} {r.read().decode()[:200]}")
        for line in r.iter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if "error" in ev:
                raise LocalModelError(f"pull {name}: {ev['error']}")
            if on_progress:
                on_progress(ev)


def unload(name: str, base_url: str = OLLAMA_URL) -> None:
    """Free the model's VRAM now (before inpainting needs the GPU)."""
    try:
        with _client(base_url) as c:
            c.post("/api/generate", json={"model": name, "keep_alive": 0})
    except Exception:
        pass


def chat_vision(
    name: str,
    system: str,
    text: str,
    image_b64: str,
    *,
    schema: dict | None = None,
    num_ctx: int = 16384,
    keep_alive: str = "5m",
    think: bool = False,
    base_url: str = OLLAMA_URL,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """One image + prompt → full reply text (streamed). `schema` constrains the
    reply to that JSON schema (works with vision models in Ollama)."""
    body: dict = {
        "model": name,
        "stream": True,
        "keep_alive": keep_alive,
        "think": think,
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text, "images": [image_b64]},
        ],
    }
    if schema is not None:
        body["format"] = schema
    chunks: list[str] = []
    done_reason = None
    try:
        for ev in _stream_chat(base_url, body):
            if "error" in ev:
                raise LocalModelError(f"{name}: {ev['error']}")
            tok = (ev.get("message") or {}).get("content") or ""
            if tok:
                chunks.append(tok)
                if on_token:
                    on_token(tok)
            if ev.get("done"):
                done_reason = ev.get("done_reason")
    except httpx.ConnectError as e:
        raise LocalModelError(f"no model server at {base_url} — is Ollama running?") from e
    if done_reason == "length":
        raise LocalModelError(f"{name}: reply cut off (context {num_ctx} tokens) — raise num_ctx")
    return "".join(chunks)


def chat_text(
    name: str,
    system: str,
    text: str,
    *,
    schema: dict | None = None,
    num_ctx: int = 16384,
    keep_alive: str = "5m",
    base_url: str = OLLAMA_URL,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Text-only chat (translation step), same streaming/limits as chat_vision."""
    body: dict = {
        "model": name, "stream": True, "keep_alive": keep_alive, "think": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.3},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
    }
    if schema is not None:
        body["format"] = schema
    chunks: list[str] = []
    done_reason = None
    try:
        for ev in _stream_chat(base_url, body):
            if "error" in ev:
                raise LocalModelError(f"{name}: {ev['error']}")
            tok = (ev.get("message") or {}).get("content") or ""
            if tok:
                chunks.append(tok)
                if on_token:
                    on_token(tok)
            if ev.get("done"):
                done_reason = ev.get("done_reason")
    except httpx.ConnectError as e:
        raise LocalModelError(f"no model server at {base_url} — is Ollama running?") from e
    if done_reason == "length":
        raise LocalModelError(f"{name}: reply cut off (context {num_ctx} tokens)")
    return "".join(chunks)


def _stream_chat(base_url: str, body: dict) -> Iterator[dict]:
    with _client(base_url) as c, c.stream("POST", "/api/chat", json=body) as r:
        if r.status_code == 404:
            raise LocalModelError(f"model '{body['model']}' is not downloaded — pull it from Settings")
        if r.status_code != 200:
            raise LocalModelError(f"{body['model']}: HTTP {r.status_code} {r.read().decode()[:300]}")
        for line in r.iter_lines():
            if line:
                yield json.loads(line)
