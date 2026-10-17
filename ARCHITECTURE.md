# Yomeru architecture

Yomeru translates and typesets comics. A FastAPI backend (`src/yomeru/`) serves
a React/Vite UI (built into `src/yomeru/static/`) and runs a file-based
pipeline per run under `data/runs/<id>/`:

    pages ─► detection ─► read & translate ─► matching ─► inpainting ─► rendering ─► typeset pages / CBZ

- Each phase is a thin orchestrator (`phases/<phase>.py`) that calls a backend
  registered in `plugins/` through the typed contracts of `core/contracts.py`.
- `core/artifacts.py` is the only place that knows file names and applies user
  edits (page edits, refined detections and matches, mask and render overrides).
- Region labels (`core/labels.py`) and language profiles (`core/languages.py`)
  are single sources of truth; the UI reads languages from `GET /api/config/languages`.
- One job per run at a time (`phases/runner.py`); GPU work is serialized.

The current, maintained map is **[.agents/context/architecture.md](.agents/context/architecture.md)**;
per-stage details are in `src/yomeru/lib/{detection,inpainting,matching,rendering}/SPEC.md`.
