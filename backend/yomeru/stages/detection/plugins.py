"""
Detection backends.

Every later phase is keyed on the detector's region ids and labels
(config/labels: bubble / text_bubble / text_free). A detector backend MUST emit
only that vocabulary — the phase validates the output against the Region
contract, so a detector with other classes fails loudly instead of silently
breaking matching, inpainting and rendering (what happened with CTD). A new
model with different classes needs an adapter that maps them.
"""
from __future__ import annotations

from PIL import Image
from pydantic import BaseModel, ConfigDict

from yomeru.pipeline.registry import register


class OgkaluOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


@register("detection", "ogkalu", title="Comic text detector", options=OgkaluOptions, needs_gpu=True,
          description="RT-DETR-v2 fine-tuned on manga: bubbles, text in bubbles, free text")
class OgkaluBackend:
    def __init__(self, options: OgkaluOptions):
        from yomeru.stages.detection.ogkalu import OgkaluDetector
        self.detector = OgkaluDetector()

    def detect(self, image: Image.Image, threshold: float) -> list[dict]:
        """Regions as dicts (x1..y2, label, score) above `threshold`, in model order."""
        # The threshold must reach the model's post-processing: it used to be
        # called with its default 0.5, so settings below 0.5 never had an effect.
        return [
            {"x1": r.x1, "y1": r.y1, "x2": r.x2, "y2": r.y2, "label": r.label, "score": r.score}
            for r in self.detector.detect(image, threshold=threshold)
        ]

