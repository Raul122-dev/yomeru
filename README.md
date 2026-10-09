# yomeru

AI-assisted manga/manhwa translation and typesetting. One workflow from raw pages to translated pages:

**detection → analysis (vision LLM) → matching → inpainting → rendering**, with an editor for every phase.

---

## Install (Linux / macOS / WSL)

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you). Node is only needed for UI development.

```bash
git clone https://github.com/Raul122-dev/yomeru
cd yomeru
bash setup.sh          # full install (torch, detection, OCR, LaMa) — same as `uv sync`
# bash setup.sh --core # analysis only, no torch
bash start.sh
# → http://localhost:7788/ui
```

Model weights (detector, OCR, LaMa) are **not** bundled — each one downloads automatically the first time a phase needs it, into `data/models/`.

By default the server binds to `127.0.0.1` (local only). Set `HOST`/`PORT` in `.env` to change it.

---

## Usage

1. Open `http://localhost:7788/ui`
2. Go to **Settings** → configure your model provider
3. Click **New Run** → upload images → pick model and format → start

---

## Data

Everything yomeru writes lives in one folder:

| Path | Content |
|---|---|
| `data/runs/<id>/` | one folder per run (pages, phase outputs, edits) |
| `data/config.json` | settings and provider API keys |
| `data/models/` | downloaded model weights (HuggingFace, EasyOCR, CTD, LaMa) |

`data/` is created inside the repo and is git-ignored. Override with `YOMERU_DATA=/some/path`. When installed with pip (no repo checkout), it defaults to `~/.yomeru`.

---

## Models

yomeru talks to models through two protocols. Add a **connection** in Settings for each place you get models from:

| Protocol | Works with | Base URL example |
|---|---|---|
| OpenAI-compatible | OpenAI, OpenRouter, Ollama, LM Studio, vLLM, DeepSeek, Groq, Google (OpenAI endpoint) | `https://openrouter.ai/api/v1` · `http://localhost:11434/v1` |
| Anthropic-compatible | Anthropic, or any proxy that speaks the Messages API | `https://api.anthropic.com` |

The analysis model must accept images. Settings can be saved as **presets**, and every run keeps a copy of the settings it was created with.

---

## Comic formats

| Key | Direction | For |
|---|---|---|
| `auto` | auto-detect | default |
| `manga` | right-to-left | Japanese manga |
| `manhwa` | left-to-right | Korean webtoons |
| `manhua` | left-to-right | Chinese comics |
| `comic` | left-to-right | Western comics |

---

## For contributors (hot reload)

Requires Node 20+:
```bash
bash dev.sh
# ui      → http://localhost:3000/ui  (vite HMR)
# backend → http://localhost:7788     (uvicorn --reload)
```

After changing UI code:
```bash
cd ui && npm run build
```
This writes the build to `src/yomeru/static/` — commit it so end users get the update without needing npm.

---

## Project structure

```
yomeru/
├── setup.sh / start.sh / dev.sh
├── pyproject.toml              ← uv sync [--extra typesetting]
├── data/                       ← runs, config, model weights (git-ignored)
├── src/yomeru/                 ← Python package
│   ├── __main__.py             ← entry point (python -m yomeru)
│   ├── app.py                  ← FastAPI app, serves UI at /ui
│   ├── phases/                 ← phase orchestration
│   │   ├── __init__.py         ← PhaseResult, registry, types
│   │   ├── runner.py           ← RunExecutor (locks, deps, run-all)
│   │   ├── detection.py        ← Phase 1: text region detection
│   │   ├── analysis.py         ← Phase 2: VLM analysis
│   │   ├── matching.py         ← Phase 3: region↔dialogue matching
│   │   ├── inpainting.py       ← Phase 4: text removal
│   │   └── rendering.py        ← Phase 5: text rendering
│   ├── lib/                    ← Reusable backends/algorithms
│   │   ├── detection/          ← CTD, Ogkalu detectors
│   │   ├── matching/           ← Hungarian matcher + OCR
│   │   ├── inpainting/         ← LaMa, OpenCV inpainters
│   │   └── rendering/          ← PIL text renderer
│   ├── core/
│   │   ├── paths.py            ← data dir layout
│   │   ├── weights.py          ← download-on-first-use weights
│   │   ├── config.py           ← JSON config store
│   │   ├── runs.py             ← Run model + phase status
│   │   ├── models.py           ← data models (dialogues, scenes, etc.)
│   │   └── analyzer.py         ← VLM prompt building + LLM calls
│   ├── api/
│   │   ├── routes/phases.py    ← phase API
│   │   ├── routes/runs.py      ← run CRUD, uploads
│   │   ├── routes/config.py    ← provider config
│   │   └── ws.py               ← WebSocket progress handler
│   ├── prompts/                ← system/format prompt templates
│   └── static/                 ← pre-built React UI (committed)
└── ui/                          ← React/Vite/TS source (dev only)
    └── src/
        ├── pages/              ← Dashboard, NewRun, RunDetail, Settings
        ├── hooks/              ← usePhaseRunner, useRunDetailData
        ├── features/           ← PhaseBar, phase views, editors
        └── lib/api.ts          ← API client (phases + legacy)
```
