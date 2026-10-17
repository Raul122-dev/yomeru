# Contributing to Yomeru — Quick Reference

> Working with an AI coding agent? Start at `AGENTS.md` and `.agents/README.md`.

## Architecture Overview

Yomeru is a manga/comic translation pipeline: **detection → analysis → matching → inpainting → rendering**.

- **Backend**: FastAPI (`src/yomeru/app.py`) on port 7788
- **Frontend**: React/Vite (`ui/`) on port 3000 (dev) or served from `src/yomeru/static/`
- **Pipeline**: `src/yomeru/phases/` — one module per phase
- **Rendering engine**: Scanline-based (`src/yomeru/lib/rendering/scanline_engine.py` — `render_page`)

## Key Files

| Purpose | File |
|---------|------|
| Scanline renderer (PRIMARY) | `src/yomeru/lib/rendering/scanline_engine.py` (render_page) |
| Bubble contour + scanlines | `src/yomeru/lib/rendering/scanline.py` |
| Fonts + text drawing | `src/yomeru/lib/rendering/pil.py` |
| Text wrapping | `src/yomeru/lib/rendering/text_layout.py` |
| Settings schema + migrations | `src/yomeru/core/settings.py` |
| Model calls (OpenAI/Anthropic) | `src/yomeru/core/llm.py` |
| Job control (409, cancel, recovery) | `src/yomeru/phases/runner.py` |
| GPU lock | `src/yomeru/core/gpu.py` |
| Inpainting masks | `src/yomeru/lib/inpainting/__init__.py` |
| LaMa backend | `src/yomeru/lib/inpainting/lama.py` |
| VLM prompts | `src/yomeru/prompts/system.md` |
| Run model | `src/yomeru/core/runs.py` |
| Rendering phase (orchestrator) | `src/yomeru/phases/rendering.py` |

## Development Commands

```bash
# Start dev server (backend + frontend)
bash dev.sh

# Backend only
uv run uvicorn yomeru.app:app --app-dir src --port 7788 --reload

# Tests + lint (Python)
uv run pytest -q
uv run ruff check --select F src/

# Type check + unit tests (Frontend)
cd ui && npx tsc --noEmit -p . && npm test

# Build frontend (generated into src/yomeru/static, not committed)
cd ui && npm run build
```

## Important Design Decisions

### Rendering: Scanline is PRIMARY
- The "stable" PIL renderer is deprecated — scanline is the only production renderer
- All rendering logic lives in `get_scanline_preview()` in `phases.py`
- The rendering phase (`phases/rendering.py`) calls scanline, copies output, writes logs
- Both `scanline-preview` (with green contours) and `scanline-production` (clean) are generated

### Inpainting Strategy
- **text_bubble** → Otsu threshold mask → OpenCV (Navier-Stokes/Telea)
- **text_free** → Full bbox mask → LaMa (full page context, content-aware)
- LaMa auto-downscales images > 2048px for performance

### Free Text vs Bubble Text
- Free text: black + white outline, bold, letter spacing, bbox expansion, angle detection
- Bubble text: color from background detection, no outline, scanline contour layout

### Anti-Collision System
- 2-pass: compute all → resolve collisions → render
- Proximity-based: MIN_GAP between texts of different regions (not just overlap)
- Direction-aware: horizontal/vertical nudge based on minimum movement
- Bubble-bounds-aware: won't push text outside its bubble

### Vertical Text
- Only for short text (≤12 chars, ≤3 words) in narrow vertical bubbles
- Per-char `getbbox()` spacing — dots/punctuation get tighter spacing than letters
- Excluded from page font normalization
- Trigger: `vert_potential_font > horiz_max_font * 1.5`

### Skip System
- VLM marks decorative/credits/title text with `skip: true`
- Matching, inpainting, rendering all respect skip
- Data preserved (text + translation) for manual override

### Cache Invalidation
- Scanline images: `Cache-Control: no-store` headers
- Rendering phase deletes cached scanline files
- mtime-based invalidation as backup
- Frontend uses `Date.now()` nonce for image URLs

## Common Pitfalls

1. **Server not reloading**: `uvicorn --reload` may miss deeply nested files. Touch `app.py` to force.
2. **Stable vs scanline**: ALL rendering changes go in `get_scanline_preview()` in phases.py, NOT in pil.py (unless it's a shared utility).
3. **Font normalization**: Can override vertical/special layouts. Check `all(len(pl.text)==1 ...)` guard.
4. **Bubble regions filter**: Must include BOTH `"bubble"` and `"text_bubble"` labels.
5. **edits.json merge**: every reader must go through `artifacts.load_analyses()` (user edits, separate translation).
6. **LaMa on large images**: Always goes through downscale path (>2048px). Don't bypass.

## Pending Work

- [ ] R10 vertical text not triggering (containing bubble detection issue)
- [ ] Further tuning of vertical text spacing for different languages
- [ ] Scanline performance optimization for very large images (24MP+)
- [ ] Code splitting for UI bundle (currently ~982KB)
