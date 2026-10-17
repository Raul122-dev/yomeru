# Detection

Locate the text regions of a page. Every later phase is keyed on their ids
and labels.

## Contract
- Phase: `stages/detection/phase.py` → backend `ogkalu` (`stages/detection/plugins.py`) →
  technique `stages/detection/ogkalu.py` (`OgkaluDetector`, RT-DETR-v2
  `ogkalu/comic-text-and-bubble-detector`, loaded from HuggingFace).
- Output per region: `pipeline/contracts.Region` — `id`, `x1..y2` (original-image
  pixels), `label`, `score`. Saved to `output/page_detections.json`; the
  detection editor writes `page_detections_refined.json`, which then shadows
  it as a whole (`runs/artifacts.active_detections`).
- `stages/detection.TextRegion` is the in-memory form the matching code works on
  (bbox helpers, optional pixel mask).

## Labels
Only the vocabulary of `config/labels.py`: `bubble` (container, no text of its
own), `text_bubble`, `text_free` (narration, signs, sound effects). The phase
validates detector output against it, and `PUT /runs/{id}/detections/{page}`
rejects other labels with 400. A detector with other classes needs an adapter
that maps them.

## Adding a detector
Register a backend in `stages/detection/plugins.py` (`@register("detection", name, ...)`) that
returns `Region`s in that vocabulary. See `.agents/skills/add-backend`.
