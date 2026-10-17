# AGENTS.md — yomeru

Instructions for AI coding agents (Codex, Copilot, Claude Code, OpenCode, Cursor…).
Humans: see README.md and docs/CONTRIBUTING.md.

yomeru translates and typesets manga/manhwa/comics: **detection → read & translate (vision LLM) → matching → inpainting → rendering**, FastAPI backend (`backend/`: package `backend/yomeru/`, organised by pipeline stage in `stages/`) + React/Vite UI (`frontend/`), with an editor for every phase. Target: v1.0 that anyone can run locally from the repo.

## Read before working
1. `.agents/README.md` — how work is split between agents and the two orchestrators.
2. `.agents/context/project.md` — goals, product rules (what NOT to change).
3. `.agents/context/architecture.md` — phases, plugins, contracts, files. (`docs/ARCHITECTURE.md` is only a short overview pointing here.)
4. `.agents/context/conventions.md` — code, tests, goldens, commits.
5. Your task file in `.agents/tasks/` if you were given one (task files are not versioned and live only in the MAIN checkout — from another worktree open it at `$(git worktree list | head -1 | cut -d' ' -f1)/.agents/tasks/`), and any skill in `.agents/skills/` that matches the work.

## Hard rules
- Work only inside the scope and files listed in your task. Ask (write it in the task file) instead of widening it.
- Never commit to `main` or push unless the task says so. Work on the branch named in the task.
- Never touch `data/` (runs, config with API keys, goldens, model weights) — it is local and git-ignored.
- No new dependency, setting, phase or UI screen without it being in the task.
- Every bug fix has a test that fails on the old code. Refactors keep the goldens identical.
- In `backend/`: `uv run pytest -q` and `uv run ruff check --select F yomeru tests scripts` must pass; UI changes: `cd frontend && npx tsc --noEmit -p . && npm test && npm run build`. CI (`.github/workflows/ci.yml`) runs all of this on every push/PR.
- Report what you verified and what you could not (no claims without output).

## Commands
```bash
cd backend
uv sync                                          # install (torch, OCR, LaMa); first use downloads weights to data/models/
uv run pytest -q                                 # tests
uv run ruff check --select F yomeru tests scripts   # lint
uv run python scripts/golden.py check            # render/inpaint/matching goldens (only if data/goldens exists)
uv run python scripts/analysis_golden.py check   # prompt/analysis goldens (idem)
cd ../frontend && npm test && npm run build      # UI tests + build → backend/yomeru/static (generated, never committed)
bash dev.sh                                      # from the repo root: backend :7788 + UI :3000 with hot reload
```
`data/` (runs, config, model weights, goldens) stays at the repo root.
