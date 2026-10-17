# Conventions

## Code
- Python 3.12, `uv`. Backend in `src/yomeru/`; every pipeline technique lives in `lib/`,
  phases only orchestrate, backends never touch `Run`, paths, `meta.json` or progress.
- File names and edit resolution only through `core/artifacts.py`; labels through
  `core/labels.py`; language rules through `core/languages.py`; model calls through `core/llm.py`.
- Region ids (the detection `id`) are the cross-phase key — never list indexes.
- Writes are atomic with per-writer temp names (`artifacts.tmp_path`).
- Prefer simple code; no comments that repeat the code. Comments explain *why*, generically:
  never reference specific comics, chapters, pages, characters, run ids or quoted lines
  (the repo is public; case evidence goes in the commit message). Same for test docstrings and fixtures.
- Remove dead code and dead settings instead of exposing them.

## Settings
- Every visible setting must be read by the pipeline.
- Changing a plugin's options model incompatibly = bump `schema_version` + `migrate` + test.
- Options forms are generated from the JSON schema (`BackendPicker`) — don't hand-write controls.

## Tests
- `uv run pytest -q` (shared `client` fixture in `tests/conftest.py`; stub OCR/models, never download in tests).
- **Bug fix = regression test that fails on the old code** (check it: restore the old file, run, restore).
- Test public entry points, not private helpers, when the bug can sit in between.

## Goldens (only where `data/goldens/` exists)
- `scripts/golden.py check` — detection→rendering on frozen runs, pixel-exact.
- `scripts/analysis_golden.py check` — prompts sent + parsed output with a replaying fake model.
- Refactors: goldens identical. Intentional output changes: own commit, visual review
  of the changed page, then recapture and name the runs/pages that changed.

## Render / quality work
- Judge by how the page reads; review ONE page per image (never side-by-side for vision).
- Don't fix audit hypotheses without a real failing page.

## Git
- Conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`) with a body
  explaining why and what was verified.
- Workers: branch `agent/NNN-short-name`, no pushes to `main`.

## UI
- React + Vite + shadcn/ui + Tailwind; `npx tsc --noEmit -p . && npm test && npm run build` before
  committing; the build output `src/yomeru/static/` is generated and never committed. Pure logic in
  `ui/src/lib` gets vitest tests next to it (`*.test.ts`).
- Images only through `components/ui/Img` (never a raw full-size `<img>`, never `no-store`).
- Phase views compose `usePhaseView` + `PhaseShell`.
