# Yomeru architecture

Yomeru translates and typesets comics. A FastAPI backend (`backend/yomeru/`, one package per stage in `stages/`) serves
a React/Vite UI (built into `backend/yomeru/static/`) and runs a file-based
pipeline per run under `data/runs/<id>/`:

    pages ─► detection ─► read & translate ─► matching ─► inpainting ─► rendering ─► typeset pages / CBZ

- Each phase is a thin orchestrator (`stages/<stage>/phase.py`) that calls a backend
  registered in its `stages/<stage>/plugins.py` through the typed contracts of `pipeline/contracts.py`.
- `runs/artifacts.py` is the only place that knows file names and applies user
  edits (page edits, refined detections and matches, mask and render overrides).
- Region labels (`config/labels.py`) and language profiles (`config/languages.py`)
  are single sources of truth; the UI reads languages from `GET /api/config/languages`.
- One job per run at a time (`pipeline/runner.py`); GPU work is serialized.

The current, maintained map is **[.agents/context/architecture.md](../.agents/context/architecture.md)**;
per-stage details are in `backend/yomeru/stages/{detection,inpainting,matching,rendering}/SPEC.md`.
