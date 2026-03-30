# Stage 2 — Matching

Assign each dialogue entry to its corresponding detected text region.

## Input

| Field              | Type               | Description                                                                   |
| ------------------ | ------------------ | ----------------------------------------------------------------------------- |
| `image`            | `PIL.Image.Image`  | Full page image (used for OCR on regions)                                     |
| `dialogues`        | `list[dict]`       | VLM-parsed dialogue dicts (with `region_id`, `bbox`, `text`, `text_position`) |
| `regions`          | `list[TextRegion]` | Detected regions from the detection stage                                     |
| `saved_detections` | `dict[int, dict]`  | `{region_id: region_dict}` from `page_detections.json`                        |
| `source_language`  | `str`              | Source language for OCR (e.g. `"Japanese"`, `"English"`)                      |
| `ocr_weight`       | `float`            | Weight for OCR text similarity score (0–1)                                    |
| `spatial_weight`   | `float`            | Weight for bbox spatial overlap score (0–1)                                   |
| `position_weight`  | `float`            | Weight for 9-zone position hint score (0–1)                                   |
| `min_score`        | `float`            | Reject matches below this combined score                                      |

## Output

`dict[int, MatchResult]` — maps dialogue index → matched region:

| Field            | Type         | Description                        |
| ---------------- | ------------ | ---------------------------------- |
| `dialogue_index` | `int`        | Index into the `dialogues` list    |
| `region`         | `TextRegion` | The matched region                 |
| `spatial_score`  | `float`      | Overlap-based score component      |
| `text_score`     | `float`      | OCR trigram similarity component   |
| `position_score` | `float`      | 9-zone position hint component     |
| `total_score`    | `float`      | Weighted sum of the above          |
| `ocr_text`       | `str`        | OCR text extracted from the region |

## Match priority

1. **Direct** — `region_id` from VLM is present and maps to a saved detection → `total_score = 1.0`, no OCR needed.
2. **Fallback Hungarian** — for dialogues without `region_id`, builds a score matrix and uses scipy's `linear_sum_assignment` for optimal one-to-one assignment.

## Backends

| Key           | Class              | Notes                                                                               |
| ------------- | ------------------ | ----------------------------------------------------------------------------------- |
| `"hungarian"` | `HungarianMatcher` | Default. Optimal one-to-one assignment via scipy. Greedy fallback if scipy missing. |

## Adding a new backend

1. Implement `BaseMatcher` protocol (see `__init__.py`)
2. Register in `build_matcher()`
3. Add to the backends table above
