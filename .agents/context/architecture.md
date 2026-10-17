# Architecture — current map

(Root `ARCHITECTURE.md` is a short overview that points here. This file is the
source of truth for agents.)

## Data chain
```
pages ─► detection ─► read & translate ─► matching ─► inpainting ─► rendering ─► typeset pages / CBZ
          regions       dialogues            dialogue→region   text erased      translation drawn
```
Each phase is a thin **orchestrator** (`src/yomeru/phases/<phase>.py`): it loads the
run's effective inputs, calls a **backend** with a typed request, saves outputs, reports
progress. The internal id of "Read & translate" is `analysis`.

| Phase | Backend(s) (`plugins/`) | Technique code (`lib/`) | Main outputs (`data/runs/<id>/output/`) |
|---|---|---|---|
| detection | `ogkalu` | `lib/detection/ogkalu.py` | `page_detections.json` |
| analysis | `vlm` (API, default), `local` (Ollama, experimental) | `core/analyzer.py`, `lib/local_models.py`, `lib/translation.py` | `page_analyses.json`, `context.json`, `translations.json` |
| matching | `cascade` | `lib/matching/{cascade,hungarian,ocr,reading_order}.py` | render log `s3_matching` |
| inpainting | `classic` (OpenCV bubbles + LaMa free text) | `lib/inpainting/` | `pNN_s4_inpainted.png` |
| rendering | `scanline` | `lib/rendering/{scanline_engine,scanline,text_layout,pil}.py` | `pNN_scanline_production.png`, typeset pages |

## Key modules (`src/yomeru/`)
| Module | Role |
|---|---|
| `core/contracts.py` | Typed requests/results per phase (`AnalysisRequest`, `MatchRequest`/`PageMatch`, `RenderRequest`/`RenderResult`, `Region`). Backends see only these. |
| `plugins/__init__.py` | Registry: `register(phase, name, options=..., needs_gpu=..., schema_version=, migrate=, api=)`, `get_backend`, `list_backends`. |
| `core/settings.py` | Pydantic settings, versioned + migrations. Each phase is `{backend, options}` (`PhaseBackend`); run snapshots freeze settings. Merge: global → preset → run overrides. |
| `core/artifacts.py` | The only place that knows file names and resolves user edits (edits.json, refined detections/matches, render overrides, separate translation). `load_analyses` = `page_analyses.json` + `translations.json` + `edits.json`. |
| `core/edits.py` | `PageEdits`: the user's edited page analyses (`edits.json`): save, revert, merge. |
| `core/labels.py` | Region labels and their roles (`bubble`, `text_bubble`, `text_free`). The detection editor offers only these and the save route rejects others. |
| `core/languages.py` | Language profiles: `profile(setting)` (OCR, reading direction, hyphenation) and `text_rules(text)` (vertical, stacking, turning, caps). `language_options()` feeds `GET /config/languages` — the UI's only language list; targets need `has_font` (Latin only for now). |
| `core/llm.py` | All remote model calls (OpenAI- and Anthropic-compatible). |
| `core/gpu.py` | `gpu_lock` — GPU work is serialized. |
| `core/images.py` | Image delivery: `?w=` WebP variants, ETag/304; `overlay_font` for debug overlays (shipped font). |
| `phases/runner.py` | One job per run, cancel, 409 when busy, recovery after restart. |
| `api/routes/` | `runs` (+ page edits PUT/DELETE `/runs/{id}/edits/{page}`), `phases` (start/start-all/cancel/status, previews), `editing`, `outputs`, `config` (+ `/languages`), `fonts`. |
| `prompts/` | `system.md` (API models), `system_compact.md` (local), `system_read.md` (reading only), `format_*.md`. |

## UI (`ui/src/`)
`pages/` (Dashboard, NewRun, RunDetail, Settings) · `features/phases/` (PhaseShell, usePhaseView) ·
`features/editors/` (Detection, Mask, Matching, Render editors) · `features/run/PageDetail` (page edits:
translations, skips, "Revert page edits") · `features/settings/` (BackendPicker renders plugin
options from JSON schema, LocalModelPanel) · `components/ui/Img` (blur placeholder + srcset).
The built UI is committed in `src/yomeru/static/`.

## Run layout (`data/runs/<id>/`)
`meta.json` (status, `created_at`/`finished_at`, settings snapshot) · `pages/` · `output/` (phase outputs, `edits.json`,
`typeset/debug/pNN_*` intermediates and render logs) · `cache/img/` (WebP variants).

## Per-module specs
`lib/{detection,inpainting,matching,rendering}/SPEC.md`.
