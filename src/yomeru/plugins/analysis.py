"""
Analysis backends — read each page and translate it.

`vlm` — one vision-model call per page (core/analyzer.analyze): the page with
numbered region badges + a region list + the story so far go in; dialogues
(text, translation, region_id, tone, type), characters, scene and a summary
come out as one JSON object. The model is any OpenAI- or Anthropic-compatible
connection from Settings (core/llm).

`local` — the same prompt and parsing, answered by a vision model on this
machine (Ollama). The reply is constrained to the PageAnalysis JSON schema,
which small models need to stay valid. No API cost.

A two-step reader→translator or an OCR-first technique takes the same
AnalysisRequest and returns a PageAnalysis.
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from yomeru.core.contracts import AnalysisRequest
from yomeru.core.models import PageAnalysis
from yomeru.plugins import register


class VlmOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register("analysis", "vlm", options=VlmOptions, needs_gpu=False,
          description="A vision model reads each page and translates it in one call (any OpenAI/Anthropic-compatible API)")
class VlmAnalyzer:
    def __init__(self, options: VlmOptions):
        self.options = options

    def analyze_page(self, req: AnalysisRequest, model, on_token: Callable[[str], None] | None = None) -> PageAnalysis:
        from yomeru.core.analyzer import analyze
        return analyze(req, model=model, on_token=on_token)


class LocalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="auto", title="Model",
                       description="Ollama model tag (e.g. qwen3.5:9b). 'auto' picks the largest "
                                   "suggested vision model that fits the free GPU memory.")
    server: str = Field(default="http://127.0.0.1:11434", title="Server",
                        description="Ollama address")
    context: int = Field(default=16384, ge=4096, le=131072, title="Context tokens",
                         description="Prompt + page image + reply. Raise it if replies get cut off.")
    structured_output: bool = Field(default=True, title="Structured output",
                                    description="Constrain the reply to the analysis JSON schema "
                                                "(keeps small models valid)")
    think: bool = Field(default=False, title="Thinking",
                        description="Let reasoning models think before answering (slower)")


def _reply_schema() -> dict:
    """JSON schema the local model must follow (Ollama `format`).

    Not PageAnalysis' own schema: that one has no required keys and no
    lengths, so a small model filled the first free-text field
    (page_summary) until it ran out of tokens. Here every key is required, in
    the order the prompt asks for (dialogues first — the part that matters),
    and descriptive text is capped. Parsing still goes through PageAnalysis.
    """
    s = lambda n: {"type": "string", "maxLength": n}  # noqa: E731
    nul = lambda t: {"anyOf": [t, {"type": "null"}]}  # noqa: E731
    dialogue = {
        "type": "object",
        "properties": {
            "region_id": nul({"type": "integer"}),
            "text": s(400),
            "text_translated": s(400),
            "speaker_id": nul(s(40)),
            "tone": s(20),
            "bubble_type": {"type": "string", "enum": ["speech", "thought", "narration", "sfx", "internal"]},
            "font_style": {"type": "string", "enum": ["regular", "bold", "thought", "narration"]},
            "skip": {"type": "boolean"},
            "skip_reason": nul(s(40)),
            "panel_index": {"type": "integer"},
        },
        # skip/skip_reason are optional ON PURPOSE: required, a 9B model copied
        # the first dialogue's skip:true ("decorative_title") onto all of them.
        "required": ["region_id", "text", "text_translated", "bubble_type"],
    }
    character = {
        "type": "object",
        "properties": {"id": s(40), "description": s(160),
                       "emotional_state": s(60), "last_action": s(120)},
        "required": ["id", "description", "emotional_state", "last_action"],
    }
    return {
        "type": "object",
        "properties": {
            "panel_count": {"type": "integer"},
            "dialogues": {"type": "array", "items": dialogue, "maxItems": 60},
            "characters_seen": {"type": "array", "items": character, "maxItems": 12},
            "scene": {"type": "object",
                      "properties": {"location": s(80), "mood": s(40), "narrative_beat": s(160)},
                      "required": ["location", "mood", "narrative_beat"]},
            "page_summary": s(300),
        },
        "required": ["panel_count", "dialogues", "characters_seen", "scene", "page_summary"],
    }


@register("analysis", "local", options=LocalOptions, needs_gpu=True,
          description="A vision model running on this machine (Ollama) — no API cost")
class LocalAnalyzer:
    def __init__(self, options: LocalOptions):
        self.options = options
        self._resolved: str | None = None

    def resolved_model(self) -> str:
        """The concrete tag for 'auto' (stored in the run's log)."""
        if self._resolved is None:
            from yomeru.lib.local_models import gpu_memory, ollama_status, suggest_model
            o = self.options
            if o.model != "auto":
                self._resolved = o.model
            else:
                st = ollama_status(o.server)
                if not st["running"]:
                    raise RuntimeError(f"no Ollama server at {o.server} — install/start Ollama or pick another technique")
                g = gpu_memory()
                want = suggest_model(g and g["free_gb"]).tag
                have = {m["name"] for m in st["models"]}
                self._resolved = want if want in have else next(
                    (m["name"] for m in st["models"] if m.get("vision")), want)
        return self._resolved

    def analyze_page(self, req: AnalysisRequest, model=None, on_token: Callable[[str], None] | None = None) -> PageAnalysis:
        import sys
        from yomeru.core.analyzer import parse_reply, prepare
        from yomeru.lib.local_models import chat_vision
        o = self.options
        name = self.resolved_model()
        p = prepare(req)
        print(f"  → local {name}  lang={req.source_language} → {req.target_language}", file=sys.stderr)
        raw = chat_vision(name, p.system, p.user_text, p.image_b64,
                          schema=_reply_schema() if o.structured_output else None,
                          num_ctx=o.context, think=o.think, base_url=o.server, on_token=on_token)
        return parse_reply(raw, req, f"local · {name}")

    def release(self) -> None:
        """Free the GPU for the next phase (inpainting/detection share it)."""
        from yomeru.lib.local_models import unload
        if self._resolved:
            unload(self._resolved, self.options.server)
