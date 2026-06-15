"""
ogkalu RT-DETR detection backend.

Model: ogkalu/comic-text-and-bubble-detector (HuggingFace)
- RT-DETR-v2 fine-tuned on manga/comic panels
- No local model download required (loaded from HuggingFace on first use)
- Detects: bubble, text_bubble, text_free, sfx

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations
import sys
from typing import Any

from PIL import Image

from . import TextRegion


class OgkaluDetector:
    """RT-DETR-v2 comic text detector via HuggingFace (ogkalu checkpoint)."""

    MODEL_ID = "ogkalu/comic-text-and-bubble-detector"

    def __init__(self) -> None:
        self._processor: Any = None
        self._model: Any = None

    @property
    def name(self) -> str:
        return "ogkalu"

    def _load(self) -> None:
        if self._processor is not None:
            return
        print("  [detector] loading ogkalu…", file=sys.stderr)
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
        import torch
        self._processor = AutoImageProcessor.from_pretrained(self.MODEL_ID)
        self._model = AutoModelForObjectDetection.from_pretrained(self.MODEL_ID)
        self._model.eval()
        if torch.cuda.is_available():
            self._model = self._model.cuda()
        print("  [detector] ogkalu ready", file=sys.stderr)

    def detect(self, image: Image.Image, threshold: float = 0.5) -> list[TextRegion]:
        self._load()
        assert self._processor is not None and self._model is not None
        import torch

        inputs = self._processor(images=image, return_tensors="pt")
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)

        results = self._processor.post_process_object_detection(
            outputs,
            threshold=threshold,
            target_sizes=torch.tensor([image.size[::-1]]),
        )[0]

        label_map: dict = self._model.config.id2label
        regions: list[TextRegion] = []

        for score, label_id, box in zip(
            results["scores"].cpu(),
            results["labels"].cpu(),
            results["boxes"].cpu(),
        ):
            x1, y1, x2, y2 = (int(v) for v in box.tolist())
            label = label_map.get(int(label_id), "text").lower()
            regions.append(TextRegion(
                x1=max(0, x1), y1=max(0, y1),
                x2=min(image.width, x2), y2=min(image.height, y2),
                label=label, score=float(score),
            ))

        summary = ", ".join(sorted({r.label for r in regions})) or "none"
        print(f"  [detector] ogkalu: {len(regions)} regions ({summary})", file=sys.stderr)
        return regions