---
id: 002
title: Fase 4 W4 — settings cleanup
status: done
owner: yoru
branch: main (orchestrator)
created: 2026-10-14
---

## Goal
Every visible setting does something and says what it does.

## Scope
- Remove `ui_language` (backend + UI types, `UI_LANGUAGES`); descriptions keep following the target language.
- Render-editor tone control reduced to what has an effect (neutral / shouting).
- Matching "compare algorithm-only" uses the run's cascade weights.
- Local translation model/server editable (separate translation, local).
- Run metadata shows the model actually used (local vs API).

## Files owned
`src/yomeru/core/{runs,analyzer,contracts}.py`, `src/yomeru/phases/analysis.py`, `src/yomeru/api/routes/{phases,runs}.py` (compare + ui_language only),
`ui/src/features/settings/{PipelineSettingsForm,LocalModelPanel}.tsx`, `ui/src/features/editors/RenderEditor.tsx`,
`ui/src/lib/{types,languages}.ts`, tests touching these.

## Log
- 2026-10-14: done. ui_language removed (descriptions = target language); tone control neutral/shouting; algorithm-only compare uses the run's cascade weights; local translation model/server editable + 'auto' falls back to an installed model; run metadata shows the model that reads (existing local run meta fixed). Tests 143, goldens + analysis golden identical, UI build ok.
