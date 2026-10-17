# Rendering

Draw the translation into the inpainted page.

## Contract
- Phase: `stages/rendering/phase.py` → backend `scanline` (default) or `image_edit`
  (experimental) in `stages/rendering/plugins.py`.
- Request/result: `pipeline/contracts.RenderRequest` (inpainted + original page,
  effective matches, dialogues with edits merged, render editor overrides,
  skipped dialogues, hyphenation language) → `RenderResult` (page, one event per
  match for the render log). Output `typeset/debug/pNN_scanline_production.png`
  and the typeset pages.

## `scanline` (`stages/rendering/scanline_engine.py`)
- Bubble contour from the page (`scanline.py`), eroded for padding; the
  available width per line is the scanline intersection, so text follows round
  and irregular bubbles. Box fallback when no contour is found.
- Wrapping (`text_layout.py`): centre-first balanced wrap, embedded `\n` hints
  from the translation, pyphen syllable splits for the target language
  (`config/languages`), character breaks for CJK; the largest size that fits wins,
  clean breaks preferred over hyphenated ones.
- Page pass: sizes harmonised across bubbles, colliding lines nudged apart.
- Vertical columns only for scripts whose profile is `vertical_native` (CJK,
  Hangul) in tall narrow bubbles when that gives a clearly larger size; vertical
  CJK free text translated to Latin is turned 90°.
- Drawing (`pil.py`): style from tone/bubble type (`regular`, `bold`,
  `thought`, `narration`); sound effects (`bubble_type` sfx) use the `sfx`
  font with the same layout rules; free text gets an outline. One font file
  per style: the run's choice (`rendering.fonts`) or the default of the drawn
  language's script (`config/languages.SCRIPT_FONTS`), looked up in
  `<data>/fonts` (user) then `assets/fonts` (shipped, licences in
  `assets/fonts/licenses/`). `build_request` resolves them into
  `RenderRequest.fonts`; `layout_and_draw` activates them for the render.
  Symbols (♥ ★ ♪ arrows…) fall back per character to the shipped Noto CJK.
  Only scripts with default fonts are offered as targets (Latin for now:
  `GET /config/languages`, `has_font`).

## `image_edit` (`stages/rendering/image_edit.py`)
Scanline lays out every dialogue; the chosen ones are cropped from the original
page and re-lettered by an image-edit model through a provider chain
(`edit_providers/`: ComfyUI, OpenRouter). Answers are aligned, checked and
pasted inside the bubble only; scanline draws everything else and is the
fallback for any rejected answer.
