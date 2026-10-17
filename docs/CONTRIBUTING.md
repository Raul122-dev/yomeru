# Contributing to yomeru

> Working with an AI coding agent? Start at `AGENTS.md` and `.agents/README.md`.

## Layout
- `backend/` — Python 3.12 + uv. Package `backend/yomeru/`, one folder per pipeline stage in
  `stages/` (detection → analysis/read & translate → matching → inpainting → rendering).
  Map of the code: [.agents/context/architecture.md](../.agents/context/architecture.md);
  each stage has a `SPEC.md`.
- `frontend/` — React + Vite + TypeScript + Tailwind; built into `backend/yomeru/static/`.
- `data/` (repo root, git-ignored) — runs, config with API keys, model weights, goldens.

## Commands
```bash
bash dev.sh                          # backend :7788 (reload) + UI :3000 (HMR)

cd backend
uv sync                              # install (torch, OCR, LaMa)
uv run pytest -q                     # tests
uv run ruff check --select F yomeru tests scripts
uv run python scripts/golden.py check            # render goldens (needs data/goldens)
uv run python scripts/analysis_golden.py check   # prompt goldens

cd frontend
npx tsc --noEmit -p . && npm test    # types + unit tests
npm run build                        # → backend/yomeru/static (generated, never committed)
```
CI (`.github/workflows/ci.yml`) runs tests, lint, types, UI tests and the build on every push/PR.

## Rules
- A new technique is a backend registered in its stage (`stages/<stage>/plugins.py`) behind the
  typed contracts in `pipeline/contracts.py`; phases only orchestrate.
- File names and user edits only through `runs/artifacts.py`; region labels through
  `config/labels.py`; language rules through `config/languages.py`.
- Every bug fix comes with a test that fails on the old code; refactors keep the goldens identical.
- Code comments stay generic (no references to specific test chapters).
- Conventions in detail: [.agents/context/conventions.md](../.agents/context/conventions.md).
