---
id: 001
title: Rendering backend with image-edit models (API providers + local ComfyUI, scanline fallback)
status: doing
owner: claude-code
branch: agent/001-qwen-edit-render
created: 2026-10-14
---

## Goal
An optional `rendering` backend `image_edit` that letters dialogues with an image-edit
model reached through pluggable providers (OpenRouter API, OpenAI-compatible images API,
ComfyUI workflow), and falls back to the scanline engine per dialogue for everything that
is not edited (out of scope, provider error, moderation block, bad alignment, cost cap).
Scanline stays the default backend and the always-present last fallback.

## Context
- `.agents/context/architecture.md` (rendering plugin, `RenderRequest`/`RenderResult`).
- Product rule: self-contained. Providers are external services the user connects
  (API keys in `connections`, ComfyUI as an optional local server like Ollama). No model
  weights, diffusers or model-specific graphs in yomeru: Qwen is a ComfyUI workflow JSON.
- Design approved by the owner on 2026-10-15 (notes kept outside the repo).

### Pre-development results (2026-10-14/15, outside the repo)
Test set: 22 regions from 3 real runs (Kaguya, Gintama, Bocchi): 16 hard (SFX, shouts,
vertical, free text, text over art) + 6 normal bubbles, 2 seeds each. Input = crop of the
ORIGINAL page (with source text), model replaces the lettering, result composited inside
the bubble contour.
- **Prompt "F5"** (best of 5 rounds): one paragraph, quoted source and target text,
  affirmative wording, no "erase"; lines re-wrapped so no word is split with a hyphen;
  quoted list of lines for < 7 lines, newline-separated for ≥ 7; clause "no word split
  across lines" except in vertical one-char-per-line mode; no style hints.
- **Qwen-Image 2.1 local (ComfyUI, RTX 5070 12 GB):** 7/12 perfect normal bubbles, ~22 s
  per edit, one-letter errors are stochastic. Best free option.
- **APIs via OpenRouter (same F5 prompt):** 12/12 normal bubbles on all of them.
  | Model | USD/edit | s/edit | Notes |
  |---|---|---|---|
  | microsoft/mai-image-2.6-flash | 0.017 | 16 | best quality/price → default |
  | meta/muse-image | 0.010 | 22 | cheapest, letters a bit small |
  | openai/gpt-image-2.5-flare (quality high) | 0.043 | 20 | most faithful, exact size → premium |
  | microsoft/mai-image-2.6 | 0.035 | 20 | worse than Flash |
  | google/gemini-nano-banana-2.1 | 0.038 | — | upstream rate limits, untested |
- Findings that shape the code:
  - API outputs come back resized/reframed → **ECC affine alignment** on the area outside
    the dilated paste mask before compositing (drift 16–26 → 1–6). Flare returns exact size.
  - **Moderation blocks** some crops (MAI/Flare on an "Undress" SFX, Muse on another) →
    provider chain + scanline fallback.
  - Some models invent extra text (vertical Japanese) outside the target area → paste only
    inside the mask.
  - Seedream returns square reframed images → not usable.
  - Validator (OCR + retry) deferred: adds latency; hook point kept.

## Design (approved)
- `image_edit` backend, per page:
  1. pick dialogues by `scope` + per-dialogue editor override `engine: auto|ai|scanline`;
  2. per dialogue: crop (paste box + 40 % margin, long side ≤ 1024, ×32), paste mask
     (bubble contour eroded 5 px via `extract_bubble_contour`; free text: box grown 15 %),
     F5 prompt;
  3. edit cache lookup → else walk the provider chain;
  4. align (resize + ECC affine) + cheap check (`max_drift`); fail → next provider;
  5. `layout_and_draw(req)` with `skipped ∪ ai_ok` on the inpainted page;
  6. paste aligned crops inside their masks (feathered);
  7. events gain `engine, provider, model, cost_usd, seconds, cache_hit, fallback[]`.
- Providers: own contract `EditRequest/EditResult` + `EditRefused / EditRateLimited /
  EditUnavailable`; adapters by protocol (`openrouter`, `openai_images`, `comfyui`) with a
  small registry + Python entry points `yomeru.edit_providers` for third parties.
- Options (`extra="forbid"`): `providers: list[EditModelRef{connection_id, adapter, model,
  quality}]`, `scope: "hard" | "all" | "manual"` (**default `hard`**), `max_cost_per_run_usd`
  (default 5.0), `max_parallel`, `max_drift`. `hard` = SFX, shouts, vertical, free text, text
  over art. `manual` = only regions the user marks. `all` must make the cost explicit
  (it grows with dialogues × pages: ~0.17 USD per 10-dialogue page with MAI-Flash) — the
  UI asks for confirmation before enabling it (UI task).
- Without any configured/reachable provider the backend renders exactly like scanline.
- Edit cache (needed: preview endpoints re-render whole pages on any input change):
  key = hash(original crop, prompt, prompt version, adapter, model, quality, seed); stored by
  the facade under `typeset/debug/ai/`; exposed to the backend as an optional
  `RenderRequest.edit_cache` (additive, `PLUGIN_API` stays 1). Re-render = new seed.
- GPU: APIs no lock, parallel up to `max_parallel`, 429 retried with backoff. ComfyUI
  adapter is `local=True` → serial, under `gpu_lock`, `POST /free` after the page.
- Re-render on demand: per region or whole page with a new seed (bypasses the cache):
  `POST /api/runs/{id}/rendering/ai/{page}` `{dialogues: [..] | null}`.

## Scope
- In: backend, prompt builder, provider registry + `openrouter` adapter, edit cache,
  override fields `engine`/`seed`, re-render endpoint, tests with a fake provider.
- Next (separate tasks): `comfyui` adapter + example Qwen workflow; UI (provider picker in
  Settings, "all" cost confirmation, per-region AI toggle and re-render in the render
  phase view/editor, cost per dialogue); later: cost estimate when picking a model, OCR
  validator.
- Out: `layout_and_draw` / `scanline.py` / `text_layout.py` behaviour, UI, settings models
  other than the backend's options.

## Files owned
- `src/yomeru/lib/rendering/image_edit.py`, `edit_prompt.py`, `edit_providers/` (new)
- `src/yomeru/core/contracts.py` (additive: edit contract, `RenderRequest.edit_cache`)
- `src/yomeru/lib/rendering/scanline_engine.py` — only `build_request`/`render_page` (create the cache)
- `src/yomeru/plugins/rendering.py` (registration + `title=` for scanline)
- `src/yomeru/api/routes/editing.py` (`RenderOverrideItem.engine/seed`), `phases.py` (re-render endpoint)
- `tests/test_render_image_edit*.py` (new)

## Acceptance
- [x] Owner-approved design before code (2026-10-15)
- [x] scanline goldens identical; `image_edit` optional, off by default
- [x] With no provider, `image_edit` output == scanline output (test)
- [x] Fake provider tests: refused → next provider; all fail → scanline; cost cap → scanline;
      cache hit makes no call; re-render changes seed and calls again
- [x] `uv run pytest -q` + ruff clean

## Questions (worker → orchestrator)

## Log (worker)
- 2026-10-14: research + experiments outside the repo (no code changes).
- 2026-10-15 (yoru): plugins can now declare a human `title=` in @register (shown in Settings). Please add `title="Scanline (programmatic)"` to the scanline registration in plugins/rendering.py (your file) and a title for the new backend.
- 2026-10-15: API round (OpenRouter) done; design approved by the owner; task goal/scope rewritten from the results (doc only, no code).
- 2026-10-15: core implemented (contracts, `edit_prompt`, `image_edit`, provider registry +
  `openrouter`, `PageEditCache`, override `engine`/`seed`, re-render endpoint, scanline `title`).
  Added after a real page run: answers that give the lettering back unchanged are rejected;
  answers in another aspect ratio are registered by keypoints (ORB + RANSAC affine, then ECC);
  drift is measured only where the answer has pixels, the source lettering must be covered and
  the uncovered part is not pasted (alpha in the cached PNG).
  Verified: 160 tests pass (13 new), ruff clean, `scripts/golden.py check` all 4 identical (run
  with YOMERU_DATA pointing at a scratch dir that links the goldens). Real run on one page of a
  test chapter (copy outside `data/`), scope `hard`, chain MAI-2.6-Flash → Muse: 5 dialogues by
  the model, one moderation block fell to Muse, page reviewed visually; ~0.15 USD in total.
  Not verified: UI (none in scope), ComfyUI (next task), cancel mid-page.
  Proposed context changes: architecture.md rendering row → `scanline`, `image_edit`
  (+ `lib/rendering/edit_providers/`); `lib/rendering/SPEC.md` backends table is outdated.
  UI note for the Fase 4 task: the render editor must keep `engine`/`seed` when it re-saves
  the overrides list.
