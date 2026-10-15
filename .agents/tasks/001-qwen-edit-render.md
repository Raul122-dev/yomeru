---
id: 001
title: Rendering backend with Qwen-Image edit (research → plugin)
status: doing
owner: claude-code
branch: agent/001-qwen-edit-render
created: 2026-10-14
---

## Goal
A `rendering` backend that letters hard regions (SFX, shouts, vertical/rotated text,
text over art, special fonts) with an image-edit model, keeping the scanline backend
for normal dialogue. Research phase first; implementation after the owner approves a design.

## Context
- `.agents/context/architecture.md` (rendering plugin, `RenderRequest`/`RenderResult`).
- Product rule: yomeru must stay self-contained — an image-edit model server is an
  OPTIONAL external server it detects (like Ollama for the local reader), never required;
  the scanline backend stays the default.
- Research notes and decisions are kept by the owner outside the repo.

## Scope
- In: new backend module(s) under `src/yomeru/lib/rendering/` (new files), its registration
  in `src/yomeru/plugins/rendering.py`, its tests.
- Out: `scanline_engine.py` / `scanline.py` / `text_layout.py` behaviour (ask first — other
  work tunes them), UI (Fase 4 work owns it), settings models other than the backend's options.

## Files owned
- `src/yomeru/lib/rendering/qwen_*.py` (new)
- `src/yomeru/plugins/rendering.py` (registration only)
- `tests/test_render_qwen*.py` (new)

## Acceptance
- [ ] Owner-approved design before code
- [ ] scanline goldens identical; new backend optional and off by default
- [ ] `uv run pytest -q` + ruff clean

## Questions (worker → orchestrator)

## Log (worker)
- 2026-10-14: research + experiments outside the repo (no code changes).
- 2026-10-15 (yoru): plugins can now declare a human `title=` in @register (shown in Settings). Please add `title="Scanline (programmatic)"` to the scanline registration in plugins/rendering.py (your file) and a title for the new backend.
