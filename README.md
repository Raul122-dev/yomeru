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
# → http://localhost:7788
```

**Option B — pip install**
```bash
pip install git+https://github.com/your-user/yomeru
yomeru
```

Both options require only **Python 3.11+**. Node/npm is never needed by end users.

---

## Usage

1. Open `http://localhost:7788`
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
# frontend → http://localhost:3000
# backend  → http://localhost:7788
```

After changing frontend code:
```bash
cd frontend && npm run build
```
This writes the build to `backend/static/` — commit it so end users get the update without needing npm.

---

## Project structure

```
yomeru/
├── setup.sh / start.sh / dev.sh
├── pyproject.toml          ← makes pip install . work
├── backend/
│   ├── main.py             ← FastAPI + serves React SPA
│   ├── requirements.txt
│   ├── static/             ← pre-built React (committed)
│   ├── core/
│   │   ├── config.py       ← JSON config store (~/.yomeru/config.json)
│   │   ├── runs.py         ← run state as JSON files (~/.yomeru/runs/)
│   │   ├── analyzer.py     ← VLM analysis via litellm
│   │   ├── pipeline.py     ← sequential page processing
│   │   └── models.py       ← narrative context data models
│   └── api/routes/
│       ├── runs.py         ← REST + WebSocket
│       └── config.py       ← provider/model config
└── frontend/
    └── src/
        ├── pages/
        │   ├── Dashboard.tsx
        │   ├── NewRun.tsx   ← free model text input + Ollama quick-select
        │   ├── RunDetail.tsx
        │   └── Settings.tsx ← one api_key per cloud provider + Ollama URL
        └── lib/api.ts
```
