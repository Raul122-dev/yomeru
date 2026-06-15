# Yomeru Architecture

Generated from the current codebase in `/home/raul/projects/yomeru`.
This document describes the code that exists today, including some inconsistencies and technical debt.

---

## 1. Project Overview

Yomeru is a **manga/manhwa/comic translation and typesetting pipeline**.
It does two distinct jobs:

1. **Narrative/context extraction** from page images using a VLM.
2. **Translation typesetting** back into the original pages through detection, matching, inpainting, and rendering.

At runtime, Yomeru is:

- a **FastAPI backend** (`src/yomeru/app.py`)
- serving a **React/Vite frontend** from `/ui`
- orchestrating a **5-phase file-based pipeline**
- storing per-run state under `~/.yomeru/runs/<run_id>/`

### Main entrypoints

```py
# src/yomeru/__main__.py
def main()
```

```py
# src/yomeru/app.py
app = FastAPI(...)
```

```py
# src/yomeru/phases/runner.py
def run_phase(run: Run, phase: PhaseName, options: dict[str, Any] | None = None,
              on_progress: ProgressCallback = null_progress,
              page_scope: list[int] | None = None) -> PhaseResult

def run_all(run: Run, options: dict[str, Any] | None = None,
            on_progress: ProgressCallback = null_progress,
            start_from: PhaseName | None = None) -> dict[PhaseName, PhaseResult]
```

### The 5-phase pipeline

`src/yomeru/phases/__init__.py` defines the phase order and dependency chain:

```py
PHASE_ORDER = ["detection", "analysis", "matching", "inpainting", "rendering"]
PHASE_DEPS = {
    "detection": [],
    "analysis": ["detection"],
    "matching": ["detection", "analysis"],
    "inpainting": ["matching"],
    "rendering": ["inpainting"],
}
```

### How it runs

#### Production / normal mode

- `bash start.sh`
- runs `python3 -m yomeru`
- backend serves API and prebuilt SPA
- UI URL: `http://localhost:7788/ui`
- API docs: `http://localhost:7788/api/docs`

#### Dev mode

- `bash dev.sh`
- backend: `uvicorn yomeru.app:app --reload` on `:7788`
- frontend: `vite` on `:3000/ui`

### Pipeline execution model

A run can be started in two ways:

- **Auto/full run**: `run_all()` executes all 5 phases sequentially.
- **Manual/step-by-step**: the UI starts phases individually through `/api/phases/.../start`.

Each phase:

- reads prior artifacts from disk
- writes its own output files to disk
- emits progress events over a WebSocket queue
- can be re-run for only a subset of pages via `page_scope`

### Storage model

A run is a directory-backed object (`src/yomeru/core/runs.py`):

```text
~/.yomeru/runs/<id>/
  meta.json
  pages/
  output/
```

`meta.json` stores:

- run identity and UI metadata
- model/provider/language settings
- `phase_status`
- total/processed pages
- error state

### High-level architecture

```text
Browser UI (/ui)
  -> FastAPI routes (/api)
    -> phases.runner
      -> phases/detection.py
      -> phases/analysis.py
      -> phases/matching.py
      -> phases/inpainting.py
      -> phases/rendering.py
        -> reusable backends in src/yomeru/lib/
```

---

## 2. Directory Structure

### Repository tree (important paths only)

```text
/home/raul/projects/yomeru/
├── README.md
├── ARCHITECTURE.md
├── pyproject.toml
├── setup.sh
├── start.sh
├── dev.sh
├── models/                         # repo-root model cache area; mostly empty in current repo
├── src/
│   └── yomeru/
│       ├── __main__.py             # CLI entrypoint
│       ├── app.py                  # FastAPI app
│       ├── api/
│       │   ├── ws.py               # per-run websocket queue/emitter
│       │   └── routes/
│       │       ├── runs.py
│       │       ├── editing.py
│       │       ├── phases.py
│       │       ├── outputs.py
│       │       ├── config.py
│       │       └── fonts.py
│       ├── assets/
│       │   └── fonts/
│       │       ├── AnimeAce.ttf
│       │       ├── Bangers-Regular.ttf
│       │       ├── ComicNeue-Bold.ttf
│       │       ├── ComicNeue-Regular.ttf
│       │       └── NotoSansCJK-Regular.ttc
│       ├── core/
│       │   ├── analyzer.py         # VLM prompt building + LiteLLM call
│       │   ├── annotations.py      # annotations.json + edits.json merge layer
│       │   ├── annotator.py        # numbered detection overlays for VLM
│       │   ├── config.py           # ~/.yomeru/config.json store
│       │   ├── logger.py           # analysis streaming logger
│       │   ├── models.py           # PageAnalysis / Dialogue / ContextObject
│       │   ├── runs.py             # Run model + path helpers
│       │   └── typesetting/
│       │       ├── detector.py     # backward-compat shims
│       │       ├── matcher.py
│       │       ├── inpainter.py
│       │       ├── renderer.py
│       │       └── stages/
│       │           ├── detection/
│       │           ├── matching/
│       │           ├── inpainting/
│       │           └── rendering/
│       ├── lib/                    # currently used backends by the live phases
│       │   ├── detection/
│       │   │   ├── __init__.py
│       │   │   ├── ogkalu.py
│       │   │   ├── ctd.py
│       │   │   └── ctd_arch.py
│       │   ├── matching/
│       │   │   ├── __init__.py
│       │   │   ├── hungarian.py
│       │   │   ├── reading_order.py
│       │   │   └── ocr.py
│       │   ├── inpainting/
│       │   │   ├── __init__.py
│       │   │   ├── opencv.py
│       │   │   └── lama.py
│       │   └── rendering/
│       │       └── __init__.py     # thin re-export to core/typesetting/stages/rendering/pil.py
│       ├── models/
│       │   ├── ctd/
│       │   └── lama/
│       ├── phases/
│       │   ├── __init__.py
│       │   ├── runner.py
│       │   ├── detection.py
│       │   ├── analysis.py
│       │   ├── matching.py
│       │   ├── inpainting.py
│       │   └── rendering.py
│       ├── prompts/
│       │   ├── system.md
│       │   ├── format_auto.md
│       │   ├── format_manga.md
│       │   ├── format_manhwa.md
│       │   ├── format_manhua.md
│       │   └── format_comic.md
│       └── static/                 # built frontend output committed into repo
└── ui/
    ├── package.json
    └── src/
        ├── App.tsx
        ├── main.tsx
        ├── pages/
        │   ├── Dashboard.tsx
        │   ├── NewRun.tsx
        │   ├── RunDetail.tsx
        │   └── Settings.tsx
        ├── hooks/
        │   ├── usePhaseRunner.ts
        │   ├── useScopedPhaseRunner.ts
        │   ├── useRunDetailData.ts
        │   └── useRunPhaseNavigation.ts
        ├── lib/
        │   ├── api.ts
        │   ├── types.ts
        │   ├── phase.ts
        │   ├── partialJson.ts
        │   ├── debug.ts
        │   ├── languages.ts
        │   └── theme.tsx
        ├── components/
        │   ├── FontsCard.tsx
        │   ├── ImageSorter.tsx
        │   ├── ThemeToggle.tsx
        │   └── ui/
        └── features/
            ├── phases/
            │   ├── DetectionPhase.tsx
            │   ├── AnalysisPhase.tsx
            │   ├── MatchingPhase.tsx
            │   ├── InpaintingPhase.tsx
            │   ├── RenderingPhase.tsx
            │   └── PhaseBar.tsx
            ├── editors/
            │   ├── DetectionEditor.tsx
            │   ├── DialogueEditor.tsx
            │   ├── MatchingEditor.tsx
            │   ├── AlgorithmCompareModal.tsx
            │   ├── MaskEditor.tsx
            │   ├── RenderEditor.tsx
            │   └── RenderLog.tsx
            └── run/
                ├── RunPhaseContent.tsx
                ├── RunHeader.tsx
                ├── PageDetail.tsx
                ├── PipelineDebug.tsx
                └── FlowDiagram.tsx
```

### Directory roles

- `src/yomeru/phases/`: top-level orchestration steps used by the live app.
- `src/yomeru/lib/`: concrete detection/matching/inpainting backends used by those phases.
- `src/yomeru/core/`: config, persistence, data models, analysis prompting, annotation helpers.
- `src/yomeru/core/typesetting/stages/rendering/`: the real text-layout/rendering engine.
- `src/yomeru/core/typesetting/*`: mostly compatibility shims and an older parallel implementation tree.
- `src/yomeru/static/`: built frontend payload committed for production serving.
- `ui/src/`: editable frontend source.

---

## 3. Phase 1: Detection

### Entry point

```py
# src/yomeru/phases/detection.py

def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult
```

### Purpose

Detection turns raw page images into a numbered list of text-bearing regions and bubble containers.
Those regions drive every later stage.

### Backends

Factory:

```py
# src/yomeru/lib/detection/__init__.py
build_detector(backend: str = "auto") -> Any
```

`auto` chooses:

- `ctd` if `models/ctd/comictextdetector.pt` exists at repo root
- otherwise `ogkalu`

#### 1) Ogkalu detector

File: `src/yomeru/lib/detection/ogkalu.py`

- model id: `ogkalu/comic-text-and-bubble-detector`
- backend: Hugging Face Transformers
- loads `AutoImageProcessor` + `AutoModelForObjectDetection`
- CUDA is used if available
- returns `TextRegion` objects from object-detection boxes

Labels observed in code/comments:

- `bubble`
- `text_bubble`
- `text_free`
- `sfx`

#### 2) CTD detector

File: `src/yomeru/lib/detection/ctd.py`

- expects `models/ctd/comictextdetector.pt`
- attempts both TorchScript and state-dict extraction paths
- supports two output formats:
  - YOLO-like predictions
  - segmentation tensors with connected-component extraction
- can return `mask` data on `TextRegion`

### Core region type

```py
@dataclass
class TextRegion:
    x1: int
    y1: int
    x2: int
    y2: int
    label: str = "text"
    score: float = 1.0
    mask: np.ndarray | None = None
```

Helpers:

- `.bbox`
- `.width`
- `.height`
- `.center`
- `.area`
- `.overlap_score(hint_bbox)`

### Detection flow

For each page:

1. load image as RGB
2. run detector
3. apply score threshold from `options["threshold"]`
4. serialize each region to JSON with 1-based `id`
5. write all pages into one file

### Input

- source files in `run.pages_dir()`
- supported extensions: `.jpg .jpeg .png .webp`

### Output file

`output/page_detections.json`

Schema:

```json
[
  {
    "page_number": 1,
    "original_w": 1600,
    "original_h": 2400,
    "regions": [
      {
        "id": 1,
        "x1": 120,
        "y1": 340,
        "x2": 540,
        "y2": 720,
        "label": "text_bubble",
        "score": 0.9812
      }
    ]
  }
]
```

### Detection + VLM overlay path

Detection phase itself only saves JSON.
The **numbered colored boxes** used by the VLM in analysis are generated by `src/yomeru/core/annotator.py`:

```py
annotate_page(image, detector_backend="auto", detector_threshold=0.4) -> AnnotatedPage
annotate_from_detections(image, regions: list[dict]) -> AnnotatedPage
```

The annotator:

- draws large numbered badges
- thickens borders for text-bearing regions
- graph-colors overlapping regions for contrast
- adds dashed separators across overlapping areas

That overlay is what makes `region_id` possible in Phase 2.

---

## 4. Phase 2: Analysis

### Entry points

```py
# src/yomeru/phases/analysis.py

def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult
```

```py
# src/yomeru/core/analyzer.py

def analyze_page(
    image_path: Path,
    page_number: int,
    previous_context: str | None = None,
    model: str = "",
    comic_format: str = DEFAULT_FORMAT,
    api_base: str | None = None,
    on_token: Callable[[str], None] | None = None,
    source_language: str = "auto",
    target_language: str | None = None,
    ui_language: str = "English",
    global_context: str = "",
    page_context: str = "",
    output_dir: Path | None = None,
    detector_backend: str = "auto",
    detector_threshold: float = 0.4,
    on_detect_done: Callable[[dict], None] | None = None,
    saved_detections_dir: Path | None = None,
) -> PageAnalysis
```

### Purpose

Analysis is the VLM stage.
It is responsible for extracting the semantic representation of a page, not just the geometry.

It produces:

- dialogues
- translations (`text_translated`) if enabled
- speaker IDs
- tone / bubble type / font style hints
- optional bbox hints
- direct `region_id` assignments from the numbered detection overlay
- page summary / scene / character continuity
- downstream context for later pages

### How analysis is built

#### Prompt sources

Files:

- `src/yomeru/prompts/system.md`
- `src/yomeru/prompts/format_auto.md`
- `src/yomeru/prompts/format_manga.md`
- `src/yomeru/prompts/format_manhwa.md`
- `src/yomeru/prompts/format_manhua.md`
- `src/yomeru/prompts/format_comic.md`

#### Input image strategy

`analyze_page()` can send either:

- the **original page**, or
- the **annotated page with numbered detection boxes**

In the current phase pipeline, analysis usually loads **saved/refined detections** and uses:

```py
annotate_from_detections(raw_img, regions)
```

#### Image resize contract

`MAX_ANALYSIS_SIDE = 1600`

The image is resized before sending to the model so bbox coordinates are stable in a known model-space.
The resized dimensions are later saved as:

- `analysis_image_w`
- `analysis_image_h`

#### Detection-aware context block

`_build_detection_context()` injects:

- a full region listing
- region size and approximate position
- overlap / adjacency warnings
- explicit instructions to assign `region_id`
- an estimate of expected dialogue count based on text-bearing regions

### Context accumulation

`src/yomeru/core/models.py` defines `ContextObject`, which accumulates:

- persistent characters
- latest scene
- page summaries
- dialogue history
- compressed chunk summaries every 5 pages (`CHUNK_SIZE = 5`)

Analysis passes the last ~2 pages plus chunk summaries into the next call.

### Core analysis schema

```py
class Dialogue(BaseModel):
    panel_index: int = 0
    speaker_id: str | None = None
    text: str = ""
    text_translated: str | None = None
    tone: str = "neutral"
    bubble_type: str = "narration"
    region_id: int | None = None
    font_style: str | None = None
    line_break_hint: str | None = None
    bbox: list[float] | None = None
```

```py
class CharacterState(BaseModel):
    id: str = "unknown"
    description: str = ""
    emotional_state: str = "neutral"
    last_action: str = ""
    last_seen_page: int = 0
```

```py
class Scene(BaseModel):
    location: str = "unknown"
    mood: str = "neutral"
    narrative_beat: str = ""
```

```py
class PageAnalysis(BaseModel):
    page_number: int
    panel_count: int = 0
    reading_order: list[int] = []
    dialogues: list[Dialogue] = []
    characters_seen: list[CharacterState] = []
    scene: Scene
    page_summary: str = ""
```

### Saved analysis JSON format

`output/page_analyses.json`

Each saved page entry is `PageAnalysis.model_dump()` plus:

- `analysis_image_w`
- `analysis_image_h`
- `source_language`

Typical shape:

```json
[
  {
    "page_number": 1,
    "panel_count": 4,
    "reading_order": [0, 1, 2, 3],
    "dialogues": [
      {
        "panel_index": 0,
        "speaker_id": "char_1",
        "text": "...source text...",
        "text_translated": "...translated text...",
        "tone": "neutral",
        "bubble_type": "speech",
        "region_id": 3,
        "font_style": "regular",
        "line_break_hint": null,
        "bbox": [120, 85, 420, 210]
      }
    ],
    "characters_seen": [
      {
        "id": "char_1",
        "description": "...",
        "emotional_state": "tense",
        "last_action": "...",
        "last_seen_page": 1
      }
    ],
    "scene": {
      "location": "...",
      "mood": "...",
      "narrative_beat": "..."
    },
    "page_summary": "...",
    "analysis_image_w": 1066,
    "analysis_image_h": 1600,
    "source_language": "Japanese"
  }
]
```

### Context output

`output/context.json`

Schema mirrors `ContextObject`:

```json
{
  "total_pages_processed": 12,
  "characters": { "char_1": { "id": "char_1", "description": "..." } },
  "scene": { "location": "...", "mood": "...", "narrative_beat": "..." },
  "page_summaries": [{ "page": 1, "summary": "..." }],
  "dialogue_history": [{ "page": 1, "panel_index": 0, "text": "..." }],
  "chunk_summaries": ["[pp1-5] ..."]
}
```

### Analysis edits and reanalysis

There are **two editing layers**:

1. `page_analyses_refined.json` via `PUT /api/runs/{run}/analyses/{page}/refined`
2. `edits.json` via `PUT /api/runs/{run}/edits/{page}`

Later phases load:

- refined analyses if present
- then merge `edits.json` on top through `AnnotationStore.merged_analyses()`

Reanalysis route:

```text
POST /api/phases/{run_id}/analysis/reanalyze
```

It injects page-specific correction text into `page_context` and reruns only one page.

---

## 5. Phase 3: Matching

### Entry point

```py
# src/yomeru/phases/matching.py

def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult
```

### Purpose

Matching connects **semantic dialogue objects** from analysis to **physical text regions** from detection.
This is the bridge from understanding to typesetting.

### Supporting functions

```py
_load_detections(run) -> dict[int, dict[int, dict]]
_load_analyses(run) -> list[dict]
_region_from_det(det, img_w, img_h) -> TextRegion
_to_pixel_bbox(bbox, img_w, img_h, analysis_w, analysis_h) -> tuple[int, int, int, int]
_validate_vlm_matches(...) -> dict
_rescue_orphaned_text_regions(...) -> dict[int, MatchResult]
```

### Matcher backends

Factory:

```py
# src/yomeru/lib/matching/__init__.py
build_matcher(backend: str = "hungarian") -> Any
```

Available implementations:

- `hungarian` (`src/yomeru/lib/matching/hungarian.py`)
- `reading_order` (`src/yomeru/lib/matching/reading_order.py`)

In the live phase pipeline, Hungarian is the main fallback matcher.

### OCR support

File: `src/yomeru/lib/matching/ocr.py`

OCR engine choice:

- `manga_ocr` for Japanese if installed
- otherwise EasyOCR
- other languages use EasyOCR with language mapping

`ocr_region(image, crop, source_language)` pads the crop and ignores very small regions.

### Full matching pipeline

#### Step 1: VLM direct assignment (`region_id`)

For each dialogue:

- skip if `dlg.get("skip")`
- if `region_id` exists and matches a detected region, create a perfect `MatchResult`
- scores are all `1.0`
- duplicates are prevented here: if the same `region_id` is claimed twice, later dialogue(s) go to `unresolved`

Perfect direct match object:

```py
MatchResult(
    dialogue_index=i,
    region=region,
    spatial_score=1.0,
    text_score=1.0,
    position_score=1.0,
    total_score=1.0,
)
```

#### Step 2: Validation (`Capa 2`)

Validator function:

```py
_validate_vlm_matches(matches, dialogues, page_dets, img,
                      img_w, img_h, analysis_w, analysis_h, source_lang) -> {
    "reassignments": {dlg_idx: new_region_id},
    "splits": [...],
    "warnings": [...],
}
```

It checks:

1. **Duplicate claims**: multiple dialogues referencing the same `region_id`
2. **Unclaimed text regions**: `text_bubble` / `text_free` not claimed by any dialogue
3. **Possible merged text**: nearby matched dialogue with suspiciously dense text relative to region area
4. **Spatial coherence** between dialogue bbox hint and assigned region

##### Important fix: trust `region_id` over bbox

If the VLM provided both:

- an explicit `region_id`, and
- a bbox that poorly overlaps that region,

then the validator **keeps the explicit `region_id`**.

This is encoded here:

- overlap `< 0.01`
- if `vlm_rid` exists and is valid, keep it and only warn
- only reassign when there is **no explicit region_id** and another region overlaps the bbox hint strongly (`> 0.5`)

Reassigned matches get synthetic scores of `0.9`.

#### Step 3: Hungarian fallback

For unresolved dialogues, Yomeru builds a score matrix over remaining candidate text regions.

File: `src/yomeru/lib/matching/hungarian.py`

Scoring terms:

- **spatial**: bbox overlap + center containment hint
- **text**: trigram similarity between dialogue text and OCR text from the region
- **position**: 9-zone page position score from `text_position`

Default weights from code/config:

- `ocr_weight = 0.4`
- `spatial_weight = 0.4`
- `position_weight = 0.2`
- `min_score = 0.05`

Algorithm:

- build `scores[n_dialogues][n_regions]`
- solve with `scipy.optimize.linear_sum_assignment`
- fallback to greedy if SciPy is absent

Returned object:

```py
MatchResult(
    dialogue_index=int(dlg_i),
    region=regions[reg_j],
    spatial_score=float(...),
    text_score=float(...),
    position_score=float(...),
    total_score=score,
    ocr_text=ocr_t,
)
```

#### Step 3b: Reading Order fallback (new)

If some dialogues still remain unmatched after Hungarian, Yomeru uses positional reading order as the last fallback.

File: `src/yomeru/lib/matching/reading_order.py`

```py
_sort_reading_order(regions: list[TextRegion], right_to_left: bool = True) -> list[int]
```

Algorithm:

1. compute region center points
2. sort by Y
3. derive an adaptive row-gap threshold:
   - `max(20, min_region_height * 0.5)`
4. group centers into rows
5. sort within row by X
   - RTL for manga
   - LTR for manhwa/comics
6. return region indices in reading order

Phase logic chooses RTL if:

- `source_language.lower()` in `("japanese", "auto", "chinese (traditional)")`

The fallback then:

- filters already-claimed region bboxes
- assigns remaining dialogues to the next available region in reading order
- uses `position_score=1.0`, `total_score=0.5`

#### Step 4: Orphaned identification

After all assignments, a region becomes **orphaned** if:

- it is a `bubble`, `text_bubble`, or `text_free`
- and it is not claimed by either direct or fallback matching

#### Step 5: Rescue (`Capa 3`)

`_rescue_orphaned_text_regions()` tries to recover orphaned `text_bubble` / `text_free` regions.

Strategy:

1. OCR the orphaned region
2. compare OCR text against already-matched dialogue text for merge detection
3. compare OCR text against unmatched dialogues
4. if similarity `> 0.3`, create a rescued `MatchResult`

Rescue scores are intentionally weaker, e.g.:

- `spatial_score = 0.5`
- `text_score = best_text_score`
- `total_score = best_text_score * 0.8`

### Match output: `render_log.json`

Per-page file:

```text
output/typeset/debug/pXX_render_log.json
```

The matching phase writes:

```json
{
  "page_number": 1,
  "image_size": { "w": 1600, "h": 2400 },
  "s2_detection": {
    "regions_found": 12,
    "source": "saved",
    "regions": [
      { "id": 1, "label": "text_bubble", "score": 0.98, "bbox": [10, 20, 30, 40] }
    ]
  },
  "s3_matching": {
    "total_dialogues": 10,
    "matched": 9,
    "unmatched_dialogues": 1,
    "direct": 7,
    "fallback": 2,
    "orphaned_regions": 1,
    "matches": [
      {
        "dialogue_index": 0,
        "region_id": 3,
        "match_type": "direct",
        "region": {
          "x1": 100, "y1": 200, "x2": 300, "y2": 400,
          "label": "text_bubble", "score": 0.98
        },
        "scores": { "spatial": 1.0, "text": 1.0, "position": 1.0, "total": 1.0 },
        "ocr_text": null,
        "dialogue_text": "..."
      }
    ],
    "unmatched": [
      { "dialogue_index": 9, "text": "..." }
    ],
    "orphaned": [
      { "region_id": 12, "label": "text_free", "bbox": [500, 500, 600, 600] }
    ]
  }
}
```

### Debug image

`_save_debug_image()` generates a visual overlay:

- green = direct
- yellow = fallback
- red = orphaned

File name:

```text
output/typeset/debug/pXX_s3_matching.jpg   # via UI grouping convention
```

### Algorithm-only comparison modal

Backend route:

```text
POST /api/phases/{run_id}/matching/algorithm-only/{page_num}
```

Frontend modal:

- `ui/src/features/editors/AlgorithmCompareModal.tsx`

It runs Hungarian **without trusting VLM region_id assignments**, returns:

- region match table
- score breakdown (spatial/text/position/total)
- agreement rate with VLM assignment
- debug image `pXX_algo_only.jpg`

This is diagnostic only; it does not modify pipeline state.

---

## 6. Phase 4: Inpainting

### Entry point

```py
# src/yomeru/phases/inpainting.py

def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult
```

### Purpose

Inpainting removes the original text from matched regions, producing a clean page for rendering.

### Mask generation (`build_text_mask`)

Live implementation used by the phase:

```py
# src/yomeru/lib/inpainting/__init__.py
build_text_mask(image, region_bbox, region_mask=None, region_label="text_bubble") -> np.ndarray
```

Actual algorithm:

1. **Crop** the region from the full page image
2. convert to **grayscale**
3. apply **Otsu thresholding**
   - bright regions -> `THRESH_BINARY_INV + OTSU`
   - dark regions -> `THRESH_BINARY + OTSU`
4. **remove connected components touching the bbox edges**
   - intended to strip bubble borders while preserving interior text
5. **morphological close** with `3x3`
6. **dilate** with `3x3`
7. paste the local binary mask back into a **full-page mask**

Returned mask is `uint8`, same size as the page:

- `255` = inpaint
- `0` = preserve

### Dual backend strategy

The phase always constructs:

- `opencv_inpainter = build_inpainter("opencv")`
- `lama_inpainter = build_inpainter("lama") if lama_available() else None`

Then it splits region masks into:

- `bubble_mask` for normal bubble text
- `free_mask` for `text_free` / `sfx`

Two-pass behavior:

1. **OpenCV** for `text_bubble`
2. **LaMa** for `text_free` / `sfx` if available, else OpenCV

This is explicitly logged as:

- `backend_bubble`
- `backend_free`
- `backend`

### Inpainting backends

#### OpenCV backend

File: `src/yomeru/lib/inpainting/opencv.py`

- always available
- chooses algorithm by total mask coverage:
  - coverage `> 1%` -> `cv2.INPAINT_NS`
  - otherwise -> `cv2.INPAINT_TELEA`
- radius = `5`

#### LaMa backend

File: `src/yomeru/lib/inpainting/lama.py`

- wrapper around `simple-lama-inpainting`
- lazy-loads model on first use
- falls back to OpenCV on load/inference failure

### Manual mask editor

Frontend:

- `ui/src/features/editors/MaskEditor.tsx`

Saved file:

```text
output/typeset/debug/pXX_mask_refined.png
```

Behavior:

- user paints/erases mask in original image coordinates
- saved as base64 PNG through `PUT /api/runs/{run}/typeset/masks/{page}`
- if the refined mask exists, the phase skips per-region mask generation and uses the manual mask directly
- for manual masks, the phase prefers LaMa if available, otherwise OpenCV

### Mask debug overlay endpoint

Route:

```text
GET /api/phases/{run_id}/inpainting/mask-debug/{page_num}
```

It regenerates `pXX_s4_mask_debug.jpg` on demand.

Overlay colors in `_save_mask_debug()`:

- `text_bubble` = magenta
- `text_free` = cyan
- `sfx` = orange

### Output files

- `output/typeset/debug/pXX_s4_inpainted.jpg`
- `output/typeset/debug/pXX_s4_mask_debug.jpg`

### `render_log.json` section added by Phase 4

```json
"s4_inpainting": {
  "backend_bubble": "opencv",
  "backend_free": "lama",
  "backend": "opencv+lama",
  "mask_pixels": 12345,
  "total_pixels": 3840000,
  "coverage_pct": 0.32,
  "skipped": false
}
```

---

## 7. Phase 5: Rendering

### Entry point

```py
# src/yomeru/phases/rendering.py

def run(
    run: Run,
    options: dict,
    on_progress: ProgressCallback = null_progress,
    page_scope: list[int] | None = None,
) -> PhaseResult
```

### Purpose

Rendering draws translated text into cleaned regions and writes final page images.

It consumes:

- inpainted page image
- matching log (`s3_matching.matches`)
- analyses (dialogue text, tone, bubble_type, source_language)
- optional per-dialogue render overrides

### Stable renderer (`pil.py`)

Real implementation:

- `src/yomeru/core/typesetting/stages/rendering/pil.py`
- exposed through `src/yomeru/lib/rendering/__init__.py`

Main API:

```py
render_text_in_bubble(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    text: str,
    tone: str = "neutral",
    bubble_type: str = "speech",
    font_style: str | None = None,
    line_break_hint: str | None = None,
    source_language: str = "auto",
    padding: int = 10,
    min_font_size: int = 8,
    max_font_size: int = 30,
    is_free_text: bool = False,
) -> tuple[Image.Image, RenderResult]
```

#### `_find_fit`: largest-font-that-fits

```py
_find_fit(text, embedded_lines, box_w, box_h, min_size, max_size, style, lang_code)
```

Behavior:

- iterates from `max_size` down to `min_size`
- for each size, computes line height and max lines
- tries embedded newlines first
- otherwise auto-wraps text
- prefers the first fit with **zero hyphenated lines**
- keeps a hyphenated candidate only if no cleaner fit exists

This is a very stable, deterministic "largest font that fits" strategy.

#### BBox + padding behavior

The stable renderer currently uses a **padded rectangle**, not contour-aware shape fitting:

- clamp region bbox to image bounds
- choose padding based on region size and `is_free_text`
- compute `fx1, fy1, fx2, fy2`
- center lines horizontally and vertically inside that box

For normal bubbles it does **not** currently call `find_usable_rect()` even though `shape_fit.py` exists and is imported.

#### Vertical text

`_is_vertical_bubble()` triggers vertical mode when:

- `bubble_h > bubble_w * 2.0`, or
- CJK text in moderately tall bubble (`bubble_h > bubble_w * 1.5`)

`_render_vertical()`:

- removes spaces
- stacks characters top-to-bottom
- lays columns right-to-left

#### Color and outline

- colored text detection via `detect_text_color()`
- fallback text color by background luminance
- free text uses an outline for contrast
- `compute_outline_color()` or text-color inversion picks stroke color

#### Angle detection

`detect_text_angle()`:

- thresholds text pixels
- merges contours
- gets `cv2.minAreaRect`
- returns nonzero angle only if absolute tilt `>= 5°`
- clamps to roughly `[-45°, 45°]`

Free text regions with angle `> 3°` are rendered through `_render_rotated()`.

#### SFX subtitle mode (Option D)

If `bubble_type.lower() == "sfx"`, the renderer does **not** replace the original art text.
Instead `_render_sfx_subtitle()` places a small subtitle near the original region:

- positioned just below the bbox when possible
- rendered as `({translation})`
- outlined for readability

### Scanline renderer (preview / experimental)

The scanline path is exposed as API preview endpoints, not the default production renderer.

Files:

- `src/yomeru/core/typesetting/stages/rendering/scanline.py`
- API wrapper in `src/yomeru/api/routes/phases.py`

Routes:

- `GET /api/phases/{run_id}/rendering/scanline-preview/{page_num}`
- `GET /api/phases/{run_id}/rendering/scanline-production/{page_num}`

#### Bubble contour detection

`extract_bubble_contour(image, bbox)` uses the **original page image**, not the inpainted one.

Pipeline:

1. crop original bubble area
2. grayscale + Gaussian blur
3. Canny edge detection
4. draw temporary rectangle at crop border
5. find contours
6. draw qualifying contours
7. flood-fill from crop center
8. select the best enclosed area
9. clean with morphological close
10. return the largest final contour in page coordinates

#### Contour erosion for padding

`erode_contour(contour, padding=10)`:

- fills contour into a mask
- erodes with elliptical kernel sized from `padding`
- returns an inset contour or `None`

#### Scanline computation

`compute_scanlines(contour, line_height, bbox)`:

- rasterizes contour into a local mask
- scans horizontal rows at line-height spacing
- collects contiguous white runs wider than 20 px
- returns `ScanlineSegment(y, x_start, x_end)`

#### Variable-width word wrap

`variable_width_wrap(text, segments, font, lang_code, min_segment_width=30, width_factor=1.0)`:

- uses each scanline segment width as per-line capacity
- greedily fills each segment before moving to next
- for CJK, treats each character as a word
- for Latin, splits by words
- centers each line within its own scanline segment

#### Vertical centering

`scanline_layout()` first uses scanlines for width estimation, then recenters the text block vertically in the **bubble bbox**.
It compensates for font ascender/descender asymmetry with:

```py
visual_offset = (asc - abs(desc)) // 4
```

#### Font size selection in preview endpoint

The preview endpoint chooses size adaptively:

- `max_size = max(30, min(60, bubble_h // 6))`
- tries sizes descending by `3`
- for each size, tries `width_factor` values:
  - `0.90`
  - `0.70`
  - `0.55`
  - `0.45`
- prefers vertical fill ratio `0.4 <= v_fill <= 0.85`
- rejects `v_fill > 0.95`
- falls back to simple bbox-centered wrap if scanline layout fails

#### Anti-collision system (line-level)

The scanline renderer uses a **2-pass layout + collision resolution** approach:

**Pass 1 — Compute all layouts independently:**
Each region gets its full contour-based scanline layout without any constraints.
All layouts are stored with their positioned lines, style, and bubble bbox.

**Pass 2 — Resolve line-level collisions:**
For each pair of layouts, individual line bounding boxes are compared.
When two lines from different regions overlap:

1. Compute `overlap_x` and `overlap_y` of the collision rectangle
2. Choose the axis requiring less movement:
   - `overlap_x <= overlap_y` → **horizontal nudge** (shift the colliding line left/right)
   - `overlap_y < overlap_x` → **vertical nudge** (shift a block of lines up/down)
3. The line/region with **more margin** in the nudge direction is the one that moves
4. After each nudge, line rects are recomputed and re-checked

This handles:
- Corner overlaps (e.g., bottom-left of upper bubble text touching top of lower bubble text)
- Full vertical overlaps between adjacent bubbles
- Cascading collisions via iterative resolution

**Pass 3 — Render:**
Production version reuses the same resolved layouts (no duplicate computation).

**Known limitations / future work:**
- Only resolves the first collision per pair then moves to next pair; complex multi-way overlaps may need multiple iterations
- Nudge amount is `overlap + 4px gap`; could be tuned per font size
- Does not re-wrap text after nudging (shifts entire lines); for extreme cases, re-layout with constrained width might produce better results

### Font system

`_FONTS_DIR`:

```text
src/yomeru/assets/fonts/
```

Style registry in `pil.py`:

- `bold`
- `regular`
- `thought`
- `narration`

Selection logic:

1. choose style from `_tone_to_style()`
2. start with style-specific font list
3. append discovered custom fonts from `_discover_custom_fonts()`
4. append system fallbacks
5. cache the chosen `ImageFont` in `_font_cache[(style, size)]`

**Default practical font**: `ComicNeue-Bold.ttf` is the first candidate for both `bold` and `regular`, so it is the default most of the time.

### Color detection

File: `color_detect.py`

- `detect_text_color()` -> median color of thresholded text pixels
- `detect_background_color()` -> median color of non-text pixels
- `compute_outline_color()` -> black or white depending on luminance
- `is_colored_text()` -> checks channel spread > 40

### CJK line breaking and text layout engine

File: `text_layout.py`

Key functions:

```py
is_cjk_text(text)
wrap_cjk(text, box_w, max_lines, font)
wrap_latin(text, box_w, max_lines, font, lang_code)
wrap_segments(segments, box_w, max_lines, font, lang_code, is_cjk=False)
wrap_text(text, box_w, max_lines, font, lang_code)
extract_embedded_breaks(text)
hyphen_count(lines)
```

#### CJK behavior

- character-level wrapping
- no-space layout
- kinsoku rules via `_NO_START` and `_NO_END`
- prevents punctuation like `、。！？` from starting lines
- prevents opening brackets/quotes from ending lines

#### Latin behavior

- word wrapping
- optional `pyphen` hyphenation
- `_split_word_punct()` strips surrounding punctuation before hyphenation

### Render output schema

`RenderResult.to_dict()` writes:

```json
{
  "text": "...",
  "status": "ok",
  "skip_reason": "",
  "lines": ["..."],
  "font_size": 24,
  "font_style": "regular",
  "line_source": "wrap",
  "bbox": [100, 200, 300, 400],
  "box_size": [180, 120],
  "angle": 0.0,
  "text_color": [0, 0, 0],
  "has_outline": false
}
```

### Final outputs

- `output/typeset/<original_filename>`
- `output/typeset/debug/pXX_s5_final.jpg`

Phase 5 also appends this to the per-page log:

```json
"s5_rendering": {
  "ok": 8,
  "skipped": 2,
  "renders": [ ...RenderResult-derived objects... ]
}
```

---

## 8. API Structure

### App wiring

`src/yomeru/app.py` mounts all routers under `/api` and serves the SPA under `/ui`.

Extra endpoints:

- `GET /health`
- `GET /` -> redirect to `/ui/`

### `src/yomeru/api/routes/runs.py`

| Method | Path | Handler | Purpose |
|---|---|---|---|
| GET | `/api/runs` | `list_runs()` | list all runs |
| GET | `/api/runs/{run_id}` | `get_run()` | run metadata |
| POST | `/api/runs` | `create_run()` | create run + upload pages |
| DELETE | `/api/runs/{run_id}` | `delete_run()` | delete run directory |
| GET | `/api/runs/{run_id}/pages` | `list_pages()` | enumerate uploaded pages |
| GET | `/api/runs/{run_id}/pages/{filename}` | `get_page_image()` | serve original page |
| GET | `/api/runs/{run_id}/context` | `get_context()` | serve `context.json` |
| GET | `/api/runs/{run_id}/annotations` | `get_annotations()` | load reviewer notes |
| POST | `/api/runs/{run_id}/annotations/{page_number}` | `add_annotation()` | add note |
| DELETE | `/api/runs/{run_id}/annotations/{page_number}/{annotation_id}` | `delete_annotation()` | delete note |
| GET | `/api/runs/{run_id}/edits` | `get_edits()` | load `edits.json` |
| PUT | `/api/runs/{run_id}/edits/{page_number}` | `save_edit()` | save edited page analysis |
| DELETE | `/api/runs/{run_id}/edits/{page_number}` | `revert_edit()` | remove edited page analysis |

#### `create_run()` form fields

- `name`
- `model`
- `provider`
- `comic_format`
- `source_language`
- `target_language`
- `global_context`
- `ui_language`
- `detector_backend`
- `detector_threshold`
- `auto_start`
- `files[]`

### `src/yomeru/api/routes/editing.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/runs/{run_id}/detections` | active detections |
| GET | `/api/runs/{run_id}/detections/{page_num}` | single-page detections |
| PUT | `/api/runs/{run_id}/detections/{page_num}` | save refined detections |
| DELETE | `/api/runs/{run_id}/detections/{page_num}/refined` | revert refined detections |
| GET | `/api/runs/{run_id}/analyses` | active analyses + merged edits |
| PUT | `/api/runs/{run_id}/analyses/{page_num}/refined` | save refined analysis page |
| DELETE | `/api/runs/{run_id}/analyses/{page_num}/refined` | revert refined analysis page |
| PUT | `/api/runs/{run_id}/typeset/matches/{page_num}` | save `pXX_matches_refined.json` |
| DELETE | `/api/runs/{run_id}/typeset/matches/{page_num}/refined` | delete match override file |
| PUT | `/api/runs/{run_id}/typeset/masks/{page_num}` | save `pXX_mask_refined.png` |
| PUT | `/api/runs/{run_id}/typeset/renders/{page_num}` | save `pXX_render_overrides.json` |

Pydantic bodies defined here:

```py
class MatchOverride(BaseModel):
    dialogue_index: int
    region_id: int
    match_type: str = "manual"
    dialogue_text: str = ""

class MatchesBody(BaseModel):
    matches: list[MatchOverride] = []

class MaskBody(BaseModel):
    mask_data_url: str

class RenderOverrideItem(BaseModel):
    dialogue_index: int
    text_translated: str | None = None
    font_style: str | None = None
    font_size_override: int | None = None
    tone: str | None = None
    skip: bool | None = None
```

### `src/yomeru/api/routes/phases.py`

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/phases/{run_id}/{phase}/start` | start phase in thread |
| POST | `/api/phases/{run_id}/{phase}/retry` | scoped retry |
| POST | `/api/phases/{run_id}/analysis/reanalyze` | reanalyze one page with corrections |
| POST | `/api/phases/{run_id}/matching/algorithm-only/{page_num}` | diagnostic Hungarian-only comparison |
| GET | `/api/phases/{run_id}/inpainting/mask-debug/{page_num}` | mask overlay image |
| GET | `/api/phases/{run_id}/rendering/scanline-preview/{page_num}` | scanline debug render |
| GET | `/api/phases/{run_id}/rendering/scanline-production/{page_num}` | scanline production-style render |
| POST | `/api/phases/{run_id}/start-all` | run all phases |
| GET | `/api/phases/{run_id}/{phase}/status` | single phase status |
| GET | `/api/phases/{run_id}/status` | all phase statuses |
| WS | `/api/phases/{run_id}/ws` | progress stream |

Request models:

```py
class PhaseStartRequest(BaseModel):
    options: dict[str, Any] = {}
    page_scope: list[int] | None = None

class StartAllRequest(BaseModel):
    options: dict[str, Any] = {}
    start_from: str | None = None

class ReanalysisRequest(BaseModel):
    page_number: int
    corrections: dict[str, str] = {}
```

### `src/yomeru/api/routes/outputs.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/runs/{run_id}/typeset/status` | list final rendered pages |
| GET | `/api/runs/{run_id}/typeset/debug` | list debug images |
| GET | `/api/runs/{run_id}/typeset/debug/{filename}` | serve debug image |
| GET | `/api/runs/{run_id}/typeset/render-log/{page_num}` | serve `pXX_render_log.json` |
| GET | `/api/runs/{run_id}/typeset/pages/{filename}` | serve final typeset page |

### `src/yomeru/api/routes/config.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | full config |
| PATCH | `/api/config/providers/{provider}` | provider credentials/base URL |
| PATCH | `/api/config/defaults` | default model/languages/format |
| PATCH | `/api/config/translation` | separate translation model config |
| PATCH | `/api/config/phases` | phase-specific defaults |
| GET | `/api/config/providers` | configured provider readiness |
| GET | `/api/config/models/local` | query custom endpoint for models |
| GET | `/api/config/models/test-connection` | health check custom endpoint |
| GET | `/api/config/capabilities` | detector/device/inpainter capabilities |
| GET | `/api/config/formats` | comic formats |

### `src/yomeru/api/routes/fonts.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/fonts` | list custom fonts |
| POST | `/api/fonts/upload` | upload `.ttf/.otf/.ttc` |
| DELETE | `/api/fonts/{filename}` | delete uploaded font |

### WebSocket event model

Producer: `src/yomeru/api/ws.py`

Common event types observed in phases/UI:

- `phase_start`
- `phase_progress`
- `page_start`
- `token` (analysis only)
- `page_done`
- `page_error`
- `phase_done`
- `phase_error`
- `heartbeat`

The websocket queue is per run, with a 30-second heartbeat timeout loop.

---

## 9. UI Structure

### Top-level routing

`ui/src/App.tsx`

Routes:

- `/` -> `Dashboard`
- `/new` -> `NewRun`
- `/runs/:id` -> `RunDetail`
- `/settings` -> `Settings`

Providers:

- `ThemeProvider`
- `QueryClientProvider`
- `BrowserRouter basename="/ui"`

### Data/API layer

`ui/src/lib/api.ts` is the single frontend API client.
It wraps all backend routes and exposes typed helpers like:

- `listRuns()`
- `getRun()`
- `startPhase()`
- `connectPhaseWs()`
- `getDetections()`
- `getAnalyses()`
- `getRenderLog()`
- `savePageMatches()`
- `saveMask()`
- `listFonts()`

### Run detail composition

`RunDetail.tsx` + hooks:

- `useRunDetailData()`
  - loads run metadata, pages, rendered-status
  - derives phase states from backend status
- `useRunPhaseNavigation()`
  - chooses default phase
  - auto-switches to running/next phase
  - prevents navigation into phases with unmet dependencies

`RunPhaseContent.tsx` dispatches to:

- `DetectionPhase`
- `AnalysisPhase`
- `MatchingPhase`
- `InpaintingPhase`
- `RenderingPhase`

### Phase display pattern

All five phase components share the same general UX shape:

1. phase card with status badge
2. run/re-run button
3. live progress section while running
4. page-level summary cards after completion
5. detailed editor/preview panel for the selected page

### Key frontend pages

#### `Dashboard.tsx`

- lists runs
- search/sort/delete
- opens run detail pages

#### `NewRun.tsx`

- uploads and orders page images via `ImageSorter`
- chooses provider/model/language/format
- chooses run mode:
  - auto all-phases
  - manual step-by-step
- optional detection backend + threshold settings

#### `Settings.tsx`

Sections include:

- primary vision model defaults
- optional separate translation model
- custom endpoint connection details
- detector/matching/inpainting/rendering phase defaults
- font management via `FontsCard`

### Key phase components

#### `DetectionPhase.tsx`

- starts phase 1
- listens for per-page region counts
- loads `page_detections.json`
- opens `DetectionEditor`

#### `AnalysisPhase.tsx`

- streams live VLM tokens
- parses partial JSON (`partialJson.ts`) during generation
- shows context summary and page detail
- opens `PageDetail` for corrections / skip toggles
- supports reanalysis with explicit reviewer corrections

#### `MatchingPhase.tsx`

- shows page cards with matched/unmatched/orphaned counts
- displays matching debug image
- opens `MatchingEditor`
- can open `AlgorithmCompareModal`

#### `InpaintingPhase.tsx`

- shows original vs inpainted previews
- can toggle mask debug overlay
- opens `MaskEditor`

#### `RenderingPhase.tsx`

- shows final output cards
- compares:
  - original
  - stable render
  - scanline debug preview
  - scanline production preview
- opens `RenderEditor`

### Editors

#### `DetectionEditor.tsx`

Features:

- Konva-based box editing
- create/move/resize/delete regions
- relabel regions
- zoom + keyboard shortcuts
- undo/redo
- writes original image coordinates back to JSON

#### `DialogueEditor.tsx`

- edits translated text, speaker, tone, bubble type
- saves to `page_analyses_refined.json`

#### `PageDetail.tsx`

- separate analysis detail/editor path
- saves full-page edits to `edits.json`
- toggles `skip` per dialogue
- submits correction notes for one-page reanalysis

#### `MatchingEditor.tsx`

- shows matched/fallback/orphaned regions overlaid on page
- lets user remap a region to a dialogue
- saves `pXX_matches_refined.json`
- includes algorithm-only comparison modal

#### `MaskEditor.tsx`

- paints/erases mask strokes in page coordinates
- saves `pXX_mask_refined.png`
- can immediately re-run inpainting for that page

#### `RenderEditor.tsx`

Per-dialogue render overrides:

- `text_translated`
- `font_style`
- `font_size_override`
- `tone`
- `skip`

Saves `pXX_render_overrides.json` and can re-render a single page.

---

## 10. Configuration & Fonts

### Main config file

Path:

```text
~/.yomeru/config.json
```

Store implementation: `src/yomeru/core/config.py`

Default structure:

```json
{
  "providers": {
    "anthropic": { "api_key": "" },
    "openai": { "api_key": "" },
    "google": { "api_key": "" },
    "custom": { "base_url": "", "api_key": "" }
  },
  "defaults": {
    "model": "google/gemini-3.1-flash-image-preview",
    "format": "auto",
    "provider": "custom",
    "source_language": "auto",
    "target_language": "Spanish"
  },
  "translation": {
    "enabled": false,
    "model": "",
    "provider": "",
    "base_url": "",
    "api_key": ""
  },
  "phases": {
    "detection": { "backend": "auto", "threshold": 0.4 },
    "matching": {
      "backend": "hungarian",
      "ocr_weight": 0.4,
      "spatial_weight": 0.4,
      "position_weight": 0.2,
      "min_score": 0.05
    },
    "inpainting": { "backend": "auto" },
    "rendering": {
      "backend": "pil",
      "use_translation": true,
      "skip_sfx": true,
      "skip_narration": false,
      "padding": 12,
      "min_font_size": 9,
      "max_font_size": 30
    }
  }
}
```

### Provider model mapping

`build_litellm_model(provider, model)` converts UI/provider config into LiteLLM input:

- `anthropic` -> model unchanged, sets `ANTHROPIC_API_KEY`
- `openai` -> model unchanged, sets `OPENAI_API_KEY`
- `google` -> prefixes `gemini/`, sets `GEMINI_API_KEY`
- `custom` -> prefixes `openai/`, appends `/v1` to base URL, sets `OPENAI_API_KEY`

### Fonts

#### Renderer font root

```text
src/yomeru/assets/fonts/
```

#### API management

- `GET /api/fonts`
- `POST /api/fonts/upload`
- `DELETE /api/fonts/{filename}`

Uploads are stored in `src/yomeru/assets/fonts/` and `pil._font_cache` is cleared immediately.

### Font priority system

For a given style and size, `_get_font(style, size)` resolves fonts in this order:

1. style-specific built-in list from `_FONT_STYLES`
2. all discovered custom fonts in `_FONTS_DIR`
3. system fallbacks like Carlito / FreeSans / DejaVu / Liberation
4. `ImageFont.load_default()` as last fallback

Style buckets are seeded with comic-specific fonts first, so the renderer prefers those before generic system fonts.

---

## 11. Data Flow

### End-to-end file flow

#### Run creation

`POST /api/runs`

- creates `~/.yomeru/runs/<id>/`
- writes `meta.json`
- stores uploaded images in `pages/`
- optionally starts the pipeline in background

#### Phase 1 -> `page_detections.json`

Detection outputs all geometric regions.
These are the source of truth for:

- VLM numbering overlay in analysis
- region geometry in matching
- mask generation in inpainting

#### Phase 2 -> `page_analyses.json` + `context.json`

Analysis consumes page images + detections and produces:

- page semantic data (`dialogues`, `characters_seen`, `scene`)
- model-space image dimensions (`analysis_image_w/h`)
- region IDs for direct matching
- cumulative context for future pages

#### Phase 3 -> `pXX_render_log.json`

Matching transforms detections + analyses into **typesetting-ready assignments**.
The per-page render log becomes the central artifact for later phases.

Current sections written incrementally:

1. `s2_detection` (copied from detection)
2. `s3_matching`
3. `s4_inpainting`
4. `s5_rendering`

#### Phase 4 -> `pXX_s4_inpainted.jpg`

Inpainting reads `s3_matching.matches` from the render log, generates masks, removes original text, and records mask coverage statistics back into the same log.

#### Phase 5 -> final page image

Rendering reads:

- `pXX_s4_inpainted.jpg`
- `pXX_render_log.json`
- `page_analyses.json` / `page_analyses_refined.json` / `edits.json`
- `pXX_render_overrides.json` if present

and writes:

- final page image to `output/typeset/<filename>`
- debug copy to `pXX_s5_final.jpg`
- `s5_rendering` back into the log

### Active-file precedence rules

From `Run.active_*_file()` and `AnnotationStore`:

1. `page_detections_refined.json` overrides `page_detections.json`
2. `page_analyses_refined.json` overrides `page_analyses.json`
3. `edits.json` is merged on top of whichever analysis file is active
4. `pXX_mask_refined.png` overrides auto-generated masks
5. `pXX_render_overrides.json` overrides render inputs per dialogue

### Render log as shared state bus

Conceptually, `pXX_render_log.json` is the handoff object between Phase 3, 4, and 5.
It carries:

- page-level geometry summary
- final dialogue->region assignments
- inpainting coverage stats
- rendering outcomes

This is the most important downstream debug artifact in the current system.

---

## 12. Known Issues & Technical Debt

### 1) Duplicate backend trees

There are two parallel implementations/concepts:

- `src/yomeru/lib/*` (used by live phases)
- `src/yomeru/core/typesetting/stages/*` (older/parallel tree, plus shims)

This creates drift risk.
Example: `build_text_mask()` exists in both trees with different behavior.

### 2) `skip_sfx` exists in config/UI but is not enforced in rendering

`src/yomeru/phases/rendering.py` reads `skip_sfx`, but the render loop never branches on it.
SFX handling is controlled instead by `bubble_type == "sfx"` -> `_render_sfx_subtitle()`.

### 3) `line_break_hint` is modeled but not wired through the rendering phase

`Dialogue.line_break_hint` exists.
`render_text_in_bubble()` even accepts `line_break_hint`.
But `phases/rendering.py` never passes it to the renderer.

### 4) Shape-aware fitting exists but stable production render does not use it

`shape_fit.py` and `find_usable_rect()` exist, and `pil.py` imports it, but the stable renderer currently uses a simple padded bbox.
The scanline preview is the only real shape-aware path.

### 5) Saved match overrides are written but not consumed

`MatchingEditor` saves `output/typeset/debug/pXX_matches_refined.json`.
No live phase reads this file.
So manual matching edits are currently **persisted but not actually applied downstream**.

### 6) Hungarian fallback candidate filtering is object-identity based

In `phases/matching.py`, used direct-match regions are filtered with `id(m.region)` against newly-created `TextRegion` objects.
Because fallback candidates are fresh objects, already-used regions can still be reconsidered by Hungarian fallback.

### 7) Position scoring is likely mostly inactive

`HungarianMatcher` uses `dlg.get("text_position")`.
But `Dialogue` in `core/models.py` does not define `text_position`, so Pydantic-normalized analysis data will usually drop it.
That makes the `position_weight` term much less useful than intended.

### 8) Capability/setup references are stale

`/api/config/capabilities` still references:

- `typesetting_status.json`
- `setup_typesetting.py`

Those are not present in this repository.
This API appears to reflect an older setup flow.

### 9) Model path expectations are inconsistent

Detection/old stage code expects repo-root model files like:

- `models/ctd/comictextdetector.pt`
- `models/lama/big-lama.pt`

But this repository currently has bundled package data under `src/yomeru/models/`, while repo-root `models/` is mostly empty.
That can make availability checks misleading.

### 10) Frontend bundle is large

Verified `npm run build` emits a Vite warning because the main JS chunk is ~982 kB before gzip.
Code-splitting is a future optimization target.

### 11) No automated tests were found

Searches found no `pytest`, `unittest`, `jest`, `vitest`, Playwright, or dedicated test files.
Current verified validation paths are build-oriented, not test-oriented.

### 12) Algorithm-only modal uses different dimension keys

The diagnostic endpoint reads `image_width` / `image_height`, while saved analysis pages actually store `analysis_image_w` / `analysis_image_h`.
If bbox values are in model-space pixels rather than normalized fractions, comparison scaling can drift.

### 13) Analysis editing is split across two storage mechanisms

There are two separate analysis-edit paths:

- `page_analyses_refined.json`
- `edits.json`

This works, but it complicates reasoning about which file is the canonical human-edited source.

---

## 13. Build & Run Commands

### Python/package setup

```bash
bash setup.sh
```

What it does:

- checks Python 3.12+
- runs `pip install -e .`
- creates `.env` from `.env.example` if missing

### Start app (production-style)

```bash
bash start.sh
```

Equivalent core command:

```bash
python3 -m yomeru
```

### Start app in development

```bash
bash dev.sh
```

This runs:

- backend: `python3 -m uvicorn yomeru.app:app --host 0.0.0.0 --port 7788 --reload`
- frontend: `npm run dev` in `ui/`

### Frontend commands

`ui/package.json` scripts:

```json
{
  "dev": "vite",
  "build": "tsc && vite build",
  "preview": "vite preview"
}
```

Run manually:

```bash
cd ui
npm install
npm run build
```

Build output is written into:

```text
src/yomeru/static/
```

### Verified validation commands

These were successfully run against the current repository:

```bash
python3 -m compileall src/yomeru
cd ui && npm run build
```

### Declared Python dependencies (`pyproject.toml`)

Direct dependencies:

- `fastapi`
- `uvicorn[standard]`
- `python-multipart`
- `httpx`
- `litellm`
- `Pillow`
- `json-repair`
- `pydantic`

### Important lazy/optional imports used by code

Notably, the code also imports these at runtime when relevant:

- `torch`
- `transformers`
- `torchvision`
- `opencv-python` / `cv2`
- `numpy`
- `scipy`
- `easyocr`
- `manga_ocr`
- `simple-lama-inpainting`
- `pyphen`

These are architecturally important even though they are not all declared in `pyproject.toml`.

### Frontend stack (`ui/package.json`)

Key packages:

- React 18
- React Router
- TanStack Query
- Konva / react-konva
- Radix UI
- Tailwind CSS 4
- Vite 5
- TypeScript 5

---

## Appendix: Most Important Source Files

If you need to continue development quickly, start here in this order:

1. `src/yomeru/phases/runner.py`
2. `src/yomeru/phases/detection.py`
3. `src/yomeru/phases/analysis.py`
4. `src/yomeru/phases/matching.py`
5. `src/yomeru/phases/inpainting.py`
6. `src/yomeru/phases/rendering.py`
7. `src/yomeru/core/models.py`
8. `src/yomeru/core/analyzer.py`
9. `src/yomeru/lib/*`
10. `src/yomeru/core/typesetting/stages/rendering/*`
11. `src/yomeru/api/routes/*`
12. `ui/src/lib/api.ts`
13. `ui/src/features/phases/*`
14. `ui/src/features/editors/*`
