---
name: run-pipeline-locally
description: Use when you need to run yomeru end to end to verify a change.
---

# Run the pipeline locally

1. `cd backend && uv sync` (first run downloads weights into `data/models/`; needs a GPU for speed, CPU works).
2. `bash dev.sh` → UI on :3000 (hot reload), API on :7788. Or `bash start.sh` for the built UI.
3. Settings → add a connection (OpenAI/Anthropic-compatible) and pick a vision model.
   Use a cheap model for tests. Never commit `data/config.json`.
4. New run → upload 2-3 pages → auto mode. Or via API:
   `curl -X POST localhost:7788/api/runs -F name=t -F auto_start=true -F files=@p1.png`.
5. Re-run from a phase: `POST /api/phases/<id>/start-all {"start_from": "matching"}`;
   one phase: `POST /api/phases/<id>/<phase>/start`.
6. Look at every rendered page before claiming it works: `output/typeset/debug/pNN_scanline_production.png`
   and the render log. "All phases done" is not "correct".
7. Don't edit files under `backend/yomeru/` while a run is in progress with `--reload`: the server
   restarts and the job is marked interrupted.
