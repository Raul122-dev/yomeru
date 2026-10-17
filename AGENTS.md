# AGENTS.md — yomeru

Instructions for AI coding agents (Codex, Copilot, Claude Code, OpenCode, Cursor…).
Humans: see README.md and CONTRIBUTING.md.

yomeru translates and typesets manga/manhwa/comics: **detection → read & translate (vision LLM) → matching → inpainting → rendering**, FastAPI backend (`src/yomeru/`) + React/Vite UI (`ui/`), with an editor for every phase. Target: v1.0 that anyone can run locally from the repo.

## Read before working
1. `.agents/README.md` — how work is split between agents and the two orchestrators.
2. `.agents/context/project.md` — goals, product rules (what NOT to change).
3. `.agents/context/architecture.md` — phases, plugins, contracts, files. (Root `ARCHITECTURE.md` is only a short overview pointing here.)
4. `.agents/context/conventions.md` — code, tests, goldens, commits.
5. Your task file in `.agents/tasks/` if you were given one (task files are not versioned and live only in the MAIN checkout — from another worktree open it at `$(git worktree list | head -1 | cut -d' ' -f1)/.agents/tasks/`), and any skill in `.agents/skills/` that matches the work.

## Hard rules
- Work only inside the scope and files listed in your task. Ask (write it in the task file) instead of widening it.
- Never commit to `main` or push unless the task says so. Work on the branch named in the task.
- Never touch `data/` (runs, config with API keys, goldens, model weights) — it is local and git-ignored.
- No new dependency, setting, phase or UI screen without it being in the task.
- Every bug fix has a test that fails on the old code. Refactors keep the goldens identical.
- `uv run pytest -q` and `uv run ruff check --select F src tests` must pass; UI changes: `cd ui && npx tsc --noEmit -p . && npm run build`.
- Report what you verified and what you could not (no claims without output).

## Commands
```bash
uv sync                                   # install (torch, OCR, LaMa); first use downloads weights to data/models/
uv run pytest -q                          # tests
uv run ruff check --select F src tests    # lint
uv run python scripts/golden.py check     # render/inpaint/matching goldens (only if data/goldens exists)
uv run python scripts/analysis_golden.py check   # prompt/analysis goldens (idem)
bash dev.sh                               # backend :7788 + UI :3000 with hot reload
cd ui && npm run build                    # UI build → src/yomeru/static (committed)
```
