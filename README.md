# yomeru

AI-assisted manga/manhwa translation and typesetting. One workflow from raw pages to translated pages:

**detection → analysis (vision LLM) → matching → inpainting → rendering**, with an editor for every phase.

---

## Install (Linux / macOS / WSL)

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you). Node is only needed for UI development.

```bash
git clone https://github.com/rauldev-yoru/yomeru
cd yomeru
bash setup.sh          # full install (torch, detection, OCR, LaMa) — runs `uv sync` in `backend/` and builds the UI
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
| `data/models/` | downloaded model weights (HuggingFace ogkalu, EasyOCR, LaMa) |

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

`bash start.sh` serves the built UI from `backend/yomeru/static/` (built by `setup.sh`; rebuild with
`cd frontend && npm run build`). The build is generated, never committed. Checks before a commit
(CI runs the same on every push/PR): in `backend/` `uv run pytest -q` and `uv run ruff check --select F yomeru tests scripts`,
`cd frontend && npx tsc --noEmit -p . && npm test && npm run build`.

---

## Project structure

```
yomeru/
├── setup.sh / start.sh / dev.sh   ← install, run, develop (from the repo root)
├── data/                          ← runs, config, model weights (git-ignored)
├── backend/                       ← Python (uv): pyproject.toml, tests/, scripts/ (goldens)
│   └── yomeru/                    ← the package
│       ├── app.py, __main__.py    ← FastAPI app (serves the UI at /ui), entry point
│       ├── api/                   ← HTTP routes + WebSocket
│       ├── stages/                ← one package per pipeline stage
│       │   ├── detection/         ←   phase.py · plugins.py · ogkalu detector · SPEC.md
│       │   ├── analysis/          ←   read & translate: analyzer, translation, local models, prompts/
│       │   ├── matching/          ←   dialogue ↔ region (cascade, Hungarian, OCR)
│       │   ├── inpainting/        ←   text removal (OpenCV, LaMa)
│       │   └── rendering/         ←   scanline engine, fonts, image-edit backend
│       ├── pipeline/              ← runner, backend registry, contracts, GPU lock
│       ├── runs/                  ← Run record, per-page artifacts, user edits
│       ├── config/                ← paths, settings, language profiles, labels
│       ├── infra/                 ← LLM client, images, logging, weights
│       ├── assets/                ← fonts (+ licences), ComfyUI workflows
│       └── static/                ← built UI (generated, not committed)
├── frontend/                      ← React/Vite/TS: src/{pages,features,components,hooks,lib}
└── docs/                          ← ARCHITECTURE.md, CONTRIBUTING.md
```
