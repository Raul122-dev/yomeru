# yomeru

Context builder for manga/manhwa. Extracts narrative flow, characters, and dialogue from comic pages using local or cloud vision models.

---

## Install (Linux / macOS)

**Option A — git clone (recommended)**
```bash
git clone https://github.com/your-user/yomeru
cd yomeru
bash setup.sh
bash start.sh
# → http://localhost:7788/ui
```

**Option B — pip install**
```bash
pip install git+https://github.com/your-user/yomeru
yomeru
```

Both options require only **Python 3.12+**. Node/npm is never needed by end users.

---

## Usage

1. Open `http://localhost:7788/ui`
2. Go to **Settings** → configure your model provider
3. Click **New Run** → upload images → pick model and format → start

---

## Configuration

Everything is configurable from the **Settings** page. Alternatively edit `~/.yomeru/config.json`:

```json
{
  "providers": {
    "anthropic": { "api_key": "sk-ant-..." },
    "openai":    { "api_key": "sk-..." },
    "google":    { "api_key": "AIza..." },
    "ollama":    { "base_url": "http://localhost:11434" }
  },
  "defaults": {
    "model": "ollama/qwen2.5vl",
    "format": "auto"
  }
}
```

Data (runs, context files) is stored in `~/.yomeru/runs/`.

---

## Supported models

Model is a free text field — any [LiteLLM-compatible](https://docs.litellm.ai/docs/providers) model string works:

| Provider | Example model strings |
|---|---|
| Ollama (local) | `ollama/qwen2.5vl` · `ollama/llama3.2-vision` · `ollama/minicpm-v` |
| Anthropic | `claude-sonnet-4-5` · `claude-opus-4-5` |
| OpenAI | `gpt-4o` · `gpt-4o-mini` |
| Google | `gemini/gemini-1.5-flash` · `gemini/gemini-2.0-flash` |

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

Requires Node 18+:
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
├── pyproject.toml              ← pip install . / pip install -e .
├── src/yomeru/                 ← Python package
│   ├── __main__.py             ← entry point (python -m yomeru)
│   ├── app.py                  ← FastAPI app, serves UI at /ui
│   ├── phases/                 ← 🆕 Unified phase orchestration
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
│   │   ├── config.py           ← JSON config store
│   │   ├── runs.py             ← Run model + phase status
│   │   ├── models.py           ← data models (dialogues, scenes, etc.)
│   │   └── analyzer.py         ← VLM prompt building + LLM calls
│   ├── api/
│   │   ├── routes/phases.py    ← 🆕 unified phase API
│   │   ├── routes/runs.py      ← run CRUD + legacy phase triggers
│   │   ├── routes/config.py    ← provider config
│   │   └── ws.py               ← WebSocket progress handler
│   ├── prompts/                ← system/format prompt templates
│   └── static/                 ← pre-built React UI (committed)
└── ui/                          ← React/Vite/TS source (dev only)
    └── src/
        ├── pages/              ← Dashboard, NewRun, RunDetail, Settings
        ├── hooks/              ← usePhaseRunner, useRunData
        ├── components/         ← PhaseBar, phase views, editors
        └── lib/api.ts          ← API client (phases + legacy)
```
