"""
Analysis backends — read each page and translate it.

`vlm` — one vision-model call per page (core/analyzer.analyze): the page with
numbered region badges + a region list + the story so far go in; dialogues
(text, translation, region_id, tone, type), characters, scene and a summary
come out as one JSON object. The model is any OpenAI- or Anthropic-compatible
connection from Settings (core/llm).

A local model, a two-step reader→translator, or an OCR-first technique takes
the same AnalysisRequest and returns a PageAnalysis.
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

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
