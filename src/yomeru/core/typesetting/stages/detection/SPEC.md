# Stage 1 — Detection

Locate all text-containing regions in a comic/manga page image.

## Input

| Field       | Type              | Description                                                                             |
| ----------- | ----------------- | --------------------------------------------------------------------------------------- |
| `image`     | `PIL.Image.Image` | Full page image, any size                                                               |
| `threshold` | `float`           | Confidence threshold (0.0–1.0). Default 0.5. Lower = more regions, more false positives |

## Output

`list[TextRegion]` — each region has:

| Field                  | Type                     | Description                                                      |
| ---------------------- | ------------------------ | ---------------------------------------------------------------- |
| `x1, y1, x2, y2`       | `int`                    | Bounding box in pixel coordinates of `image`                     |
| `label`                | `str`                    | Region type: `"bubble"`, `"text_bubble"`, `"text_free"`, `"sfx"` |
| `score`                | `float`                  | Detection confidence                                             |
| `mask`                 | `np.ndarray \| None`     | Binary pixel mask (same HxW as image), or None                   |
| `.bbox`                | `tuple[int,int,int,int]` | Property: `(x1, y1, x2, y2)`                                     |
| `.center`              | `tuple[int,int]`         | Property: center pixel                                           |
| `.area`                | `int`                    | Property: pixel area                                             |
| `.overlap_score(hint)` | `float`                  | IoU with a hint bbox                                             |

## Backends

| Key        | Class            | Notes                                                                                                  |
| ---------- | ---------------- | ------------------------------------------------------------------------------------------------------ |
| `"ogkalu"` | `OgkaluDetector` | RT-DETR-v2 via HuggingFace. No local model needed. Best general-purpose.                               |
| `"ctd"`    | `CTDDetector`    | Comic Text Detector (dmMaze). Requires `models/ctd/comictextdetector.pt`. Provides segmentation masks. |
| `"auto"`   | —                | Uses CTD if model present, falls back to ogkalu                                                        |

## Adding a new backend

1. Create a class implementing `BaseDetector` protocol (see `__init__.py`)
2. Register it in `build_detector()` in `__init__.py`
3. Add an entry to the backends table above

## Notes

- Detection runs **before** the VLM call (detection-first flow). The annotated image
  with numbered boxes is sent to the VLM, which returns `region_id` per dialogue.
- Results are saved to `output/page_detections.json` and reused during typesetting —
  the detector does NOT run again during the typesetting stage.
