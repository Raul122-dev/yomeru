# Yomeru — Technical Documentation

## Overview

Yomeru is a manga/manhwa/comic context builder that extracts narrative flow, characters, and dialogue from comic pages using vision language models (VLMs), then optionally typesets translated text back onto the pages.

**Stack:** Python 3.12+ (FastAPI + LiteLLM) · React + TypeScript (Vite) · PIL/NumPy for image processing

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  User (Browser)                                         │
│  http://localhost:7788/ui                                │
└────────────────┬────────────────────────────────────────┘
                 │ HTTP + WebSocket
┌────────────────▼────────────────────────────────────────┐
│  FastAPI App  (src/yomeru/app.py)                       │
│                                                         │
│  /api/phases/{run}/{phase}/start   ← unified phase API  │
│  /api/phases/{run}/ws              ← progress stream    │
│  /api/runs/...                     ← run CRUD + legacy  │
│  /api/config/...                   ← provider settings  │
│  /ui/...                           ← React SPA          │
└────────┬────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────┐
│  Phase Runner  (src/yomeru/phases/runner.py)            │
│                                                         │
│  Per-run locking · Dependency validation · Progress     │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐  ┌──────────┐
│  │Detection │→ │ Analysis │→ │Matching │→ │Inpaint │→ │Rendering │
│  └──────────┘  └──────────┘  └─────────┘  └────────┘  └──────────┘
│   phases/       phases/       phases/       phases/       phases/
│   detection.py  analysis.py   matching.py   inpainting.  rendering.
└────────┬────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────┐
│  Backends  (src/yomeru/lib/)                            │
│                                                         │
│  lib/detection/   CTD · Ogkalu RT-DETR                  │
│  lib/matching/    Hungarian + OCR                        │
│  lib/inpainting/  LaMa · OpenCV                         │
│  lib/rendering/   PIL text renderer                     │
└─────────────────────────────────────────────────────────┘
```

---

## Pipeline: 5 Phases

### Phase 1: Detection
**What:** Detects text regions (speech bubbles, SFX, captions) in each page image.  
**Input:** Source images in `run/pages/`  
**Output:** `output/page_detections.json`  
**Backends:** Ogkalu RT-DETR (default), CTD

### Phase 2: Analysis
**What:** Sends pages to a VLM to extract dialogues, characters, scenes, narrative context, and optionally translations.  
**Input:** Source images + `page_detections.json` (for annotated image sent to VLM)  
**Output:** `output/page_analyses.json` + `output/context.json`  
**Providers:** Anthropic, OpenAI, Google, Custom (Ollama, OpenRouter, etc.) via LiteLLM

### Phase 3: Matching
**What:** Maps detected regions ↔ analysis dialogues. Uses direct region_id matching first, then Hungarian algorithm for unresolved dialogues.  
**Input:** `page_detections.json` + `page_analyses.json` + source images  
**Output:** `output/typeset/debug/pXX_render_log.json` (s2_detection + s3_matching data)  
**Backends:** Hungarian matcher with OCR scoring

### Phase 4: Inpainting
**What:** Removes original text from matched regions using inpainting.  
**Input:** Source images + render_log.json (matching data)  
**Output:** `output/typeset/debug/pXX_s4_inpainted.jpg`  
**Backends:** LaMa (neural, higher quality), OpenCV (fast fallback)

### Phase 5: Rendering
**What:** Renders translated text into the cleaned bubble regions.  
**Input:** Inpainted images + render_log + analyses (for dialogue text)  
**Output:** `output/typeset/<filename>` (final pages) + debug images  
**Backends:** PIL renderer with auto font sizing

---

## Data Flow & Artifacts

Each run is stored at `~/.yomeru/runs/<id>/`:

```
runs/<id>/
├── meta.json                     ← run config + phase statuses
├── pages/                        ← uploaded source images
│   ├── 001.jpg
│   ├── 002.jpg
│   └── ...
└── output/
    ├── page_detections.json      ← Phase 1 output
    ├── page_detections_refined.json  ← manual edits (optional)
    ├── page_analyses.json        ← Phase 2 output
    ├── page_analyses_refined.json    ← manual edits (optional)
    ├── context.json              ← narrative context summary
    └── typeset/
        ├── 001.jpg               ← Phase 5 final output
        ├── 002.jpg
        └── debug/
            ├── p01_render_log.json   ← Phase 3-5 data per page
            ├── p01_s4_inpainted.jpg  ← Phase 4 output
            ├── p01_s5_final.jpg      ← Phase 5 debug copy
            ├── p01_mask_refined.png  ← manual mask edit (optional)
            └── p01_render_overrides.json  ← render overrides (optional)
```

**Refined files** take precedence: if `*_refined.json` exists, it's used instead of the original. This enables the edit-and-rerun workflow.

---

## API Reference

### Phases API (new, unified)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/phases/{run_id}/{phase}/start` | Start a phase |
| POST | `/api/phases/{run_id}/{phase}/retry` | Retry failed pages |
| GET | `/api/phases/{run_id}/{phase}/status` | Phase status + deps |
| POST | `/api/phases/{run_id}/start-all` | Run all phases sequentially |
| GET | `/api/phases/{run_id}/status` | All phases status |
| WS | `/api/phases/{run_id}/ws` | Real-time progress stream |

### Runs API (CRUD + legacy)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/runs` | List runs |
| GET | `/api/runs/{id}` | Get run details |
| POST | `/api/runs` | Create run (multipart form) |
| DELETE | `/api/runs/{id}` | Delete run |
| GET | `/api/runs/{id}/detections` | Get detections |
| GET | `/api/runs/{id}/analyses` | Get analyses |
| GET | `/api/runs/{id}/context` | Get context |

### Config API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Get full config |
| PUT | `/api/config/providers/{name}` | Update provider settings |
| GET | `/api/config/models` | List available models |

---

## Frontend Architecture

```
ui/src/
├── pages/              Dashboard, NewRun, RunDetail, Settings
├── features/
│   ├── phases/         5 phase components + PhaseBar
│   ├── editors/        Per-phase editors (detection, dialogue, mask, etc.)
│   └── run/            Run detail layout (header, content router, etc.)
├── components/         Generic reusable (UI primitives, ThemeToggle, etc.)
├── hooks/              usePhaseRunner, useRunDetailData, useRunPhaseNavigation
└── lib/                API client, types, utilities
```

**Phase UI pattern** (each phase follows the same structure):
1. Status badge (pending/running/done/failed)
2. "Run" button (disabled if dependencies not met)
3. Progress log (live via WebSocket)
4. Results grid (per-page output after completion)
5. Editor (corrections → re-run)

---

## Configuration

All config stored at `~/.yomeru/config.json`:

```json
{
  "providers": {
    "anthropic": { "api_key": "sk-ant-..." },
    "openai":    { "api_key": "sk-..." },
    "google":    { "api_key": "AIza..." },
    "custom":    { "base_url": "http://localhost:11434", "api_key": "" }
  },
  "defaults": {
    "model": "",
    "format": "auto",
    "provider": "",
    "ui_language": "English",
    "source_language": "auto"
  }
}
```

**Providers:**
- `anthropic` — Claude models (model as-is)
- `openai` — GPT models (model as-is)
- `google` — Gemini models (prefixed `gemini/`)
- `custom` — Any OpenAI-compatible endpoint (Ollama, OpenRouter, LM Studio, etc.)

---

## Development

```bash
# Setup
git clone <repo> && cd yomeru
bash setup.sh          # installs Python deps via pip install -e .

# Run (production mode)
bash start.sh          # → http://localhost:7788/ui

# Run (development with hot reload)
bash dev.sh            # backend :7788 + frontend :3000/ui

# Build frontend
cd ui && npm run build # outputs to src/yomeru/static/

# Type check frontend
cd ui && npx tsc --noEmit
```

---

## Key Design Decisions

1. **Phases are independent modules** — each reads from files, writes to files. No shared in-memory state between phases.

2. **File-based communication** — phases communicate via JSON files in the output directory. This enables: manual editing, re-running individual phases, and debugging.

3. **Refined files override originals** — `*_refined.json` and `*_mask_refined.png` allow manual corrections without losing the original output.

4. **Dependency chain is enforced** — the runner checks that required phases are complete before allowing a phase to start.

5. **Backends are pluggable** — each phase can use different backend implementations (e.g., LaMa vs OpenCV for inpainting).

6. **UI is served by the backend** — no separate frontend process needed in production. The React SPA is pre-built into `src/yomeru/static/`.
