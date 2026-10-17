---
name: render-quality-fix
description: Use when fixing how translated text is laid out or drawn on the page.
---

# Fix a rendering / typesetting problem

Rendering is judged by how the page reads. Work from a REAL failing page.

1. Reproduce: find the event in the run's render log (`output/typeset/debug/pNN_render_log.json`,
   `s5_rendering.renders`: status, skip_reason, font_size, bbox) and the matched region
   (`s3_matching.matches`, check the region label).
2. Locate the decision in `stages/rendering/scanline_engine.py` (`layout_and_draw` is a pure function
   of a `RenderRequest`). Language/script-dependent decisions go through `config/languages.py`
   (`text_rules(text)`), never a new `if lang ...`.
3. Write a regression test with a synthetic `RenderRequest` (white page, original with dark
   strokes where text was, so the region counts as erased) that fails on the old code.
4. Fix narrowly. Rules already in place you must keep:
   - an erased region is never left empty (min size included, last-resort overflow flagged);
   - never draw over text the user's mask edit kept (`_was_erased`);
   - container = first box holding the text centre unless it cuts the text and another holds it whole;
   - nothing taller than its box in the bbox fallback; free text grows evenly around its spot;
   - hyphenated words break at their own hyphen; names and short words are not split;
   - all-caps source → uppercase translation; one-word caps shouts in tall bubbles are stacked;
   - vertical CJK free text translated to Latin is turned 90°.
5. Verify: tests, `scripts/golden.py check` (if goldens exist). If a golden page changes on
   purpose, describe the change for the orchestrator — do not recapture goldens yourself.
6. Report with before/after numbers from the render log and which pages you looked at.
