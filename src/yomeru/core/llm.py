"""Model access through two protocols: OpenAI Chat Completions and Anthropic Messages.

Every model call in yomeru goes through `stream_vision()` / `list_models()` /
`test_connection()`. Connections carry their own base_url + api_key, so there
is no process-wide environment mutation and concurrent runs never interfere.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from yomeru.core.settings import Connection, ModelRef, store

REQUEST_TIMEOUT = 180.0  # seconds; a hung endpoint must not hold a run lock forever
# Reasoning models (Gemini 3 Pro, o-series…) spend output budget on hidden
# thinking before the JSON; 8k truncated real pages mid-answer.
MAX_OUTPUT_TOKENS = 32768


class LLMError(RuntimeError):
    pass


@dataclass
class ResolvedModel:
    connection: Connection
    model: str

    @property
    def label(self) -> str:
        return f"{self.connection.name} · {self.model}"


def resolve_model(ref: ModelRef) -> ResolvedModel:
    if not ref.is_set():
        raise LLMError("no model selected — choose one in Settings or when creating the run")
    conn = store.load().connection(ref.connection_id)
    if conn is None:
        raise LLMError(f"connection {ref.connection_id!r} no longer exists — pick another in Settings")
    return ResolvedModel(conn, ref.model)


def _openai_client(conn: Connection):
    from openai import OpenAI
    # Local servers (Ollama, LM Studio) accept any key but the SDK requires one.
    return OpenAI(api_key=conn.api_key or "not-needed", base_url=conn.effective_base_url(),
                  timeout=REQUEST_TIMEOUT, max_retries=2)


def _anthropic_client(conn: Connection):
    from anthropic import Anthropic
    return Anthropic(api_key=conn.api_key or "not-needed", base_url=conn.effective_base_url(),
                     timeout=REQUEST_TIMEOUT, max_retries=2)


def stream_vision(
    rm: ResolvedModel,
    system: str,
    text: str,
    image_b64: str,
    mime: str,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Send one image + prompt, stream the reply, return the full text."""
    chunks: list[str] = []
    try:
        for tok in _stream(rm, system, text, image_b64, mime):
            chunks.append(tok)
            if on_token:
                on_token(tok)
    except LLMError:
        raise
    except Exception as e:  # SDK errors → one readable message for the UI
        raise LLMError(f"{rm.label}: {type(e).__name__}: {e}") from e
    return "".join(chunks)


def _stream(rm: ResolvedModel, system: str, text: str, b64: str, mime: str) -> Iterator[str]:
    if rm.connection.protocol == "anthropic":
        client = _anthropic_client(rm.connection)
        messages: Any = [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
            {"type": "text", "text": text},
        ]}]
        with client.messages.stream(
            model=rm.model, max_tokens=MAX_OUTPUT_TOKENS, system=system, messages=messages,
        ) as stream:
            yield from stream.text_stream
            final = stream.get_final_message()
        if final.stop_reason == "max_tokens":
            raise LLMError(f"{rm.label}: reply cut off at {MAX_OUTPUT_TOKENS} output tokens")
        return

    client = _openai_client(rm.connection)
    stream = client.chat.completions.create(
        model=rm.model,
        max_tokens=MAX_OUTPUT_TOKENS,
        stream=True,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ],
    )
    finish = None
    for chunk in stream:
        if not chunk.choices:
            continue
        c = chunk.choices[0]
        finish = c.finish_reason or finish
        if c.delta and c.delta.content:
            yield c.delta.content
    # A truncated reply still parses (json_repair) into a page with half the
    # dialogues — fail loudly so the page is retried instead.
    if finish == "length":
        raise LLMError(f"{rm.label}: reply cut off at {MAX_OUTPUT_TOKENS} output tokens")


def list_models(conn: Connection) -> list[dict]:
    """Models the connection exposes. `vision` is True/False when the API says so, else None."""
    try:
        if conn.protocol == "anthropic":
            page = _anthropic_client(conn).models.list(limit=100)
            # Every Claude model in the models API accepts images
            return [{"id": m.id, "name": getattr(m, "display_name", m.id), "vision": True} for m in page.data]
        out = []
        for m in _openai_client(conn).models.list().data:
            extra = getattr(m, "model_extra", None) or {}
            arch = extra.get("architecture") or {}  # OpenRouter reports input modalities
            mods = arch.get("input_modalities")
            vision = ("image" in mods) if isinstance(mods, list) else None
            out.append({"id": m.id, "name": extra.get("name") or m.id, "vision": vision})
        return sorted(out, key=lambda x: x["id"])
    except Exception as e:
        raise LLMError(f"{conn.name}: cannot list models ({type(e).__name__}: {e})") from e


def test_connection(conn: Connection) -> dict:
    try:
        n = len(list_models(conn))
        return {"ok": True, "models": n}
    except LLMError as e:
        return {"ok": False, "error": str(e)}
