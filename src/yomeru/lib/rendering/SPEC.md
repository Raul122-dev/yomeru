# Stage 4 — Rendering

Draw translated text into the clean (inpainted) bubble regions.

## Input

| Field             | Type                     | Description                                                      |
| ----------------- | ------------------------ | ---------------------------------------------------------------- |
| `image`           | `PIL.Image.Image`        | Inpainted page image                                             |
| `bbox`            | `tuple[int,int,int,int]` | `(x1, y1, x2, y2)` of the bubble in image pixel coords           |
| `text`            | `str`                    | Text to render. May contain `\n` as semantic break hints.        |
| `tone`            | `str`                    | Dialogue tone: `"neutral"`, `"shouting"`, `"whispering"`, etc.   |
| `bubble_type`     | `str`                    | `"speech"`, `"thought"`, `"narration"`, `"sfx"`, `"internal"`    |
| `font_style`      | `str \| None`            | Override: `"bold"`, `"regular"`, `"thought"`, `"narration"`      |
| `source_language` | `str`                    | Language for pyphen hyphenation (e.g. `"Spanish"`, `"Japanese"`) |
| `padding`         | `int`                    | Minimum padding inside bubble (px). Adapts for small bubbles.    |
| `min_font_size`   | `int`                    | Smallest font size to try (default 8).                           |
| `max_font_size`   | `int`                    | Largest font size to try first (default 30).                     |

## Output

`tuple[PIL.Image.Image, RenderResult]`

| Field                | Type              | Description                                     |
| -------------------- | ----------------- | ----------------------------------------------- |
| `image`              | `PIL.Image.Image` | Image with text drawn (or unchanged if skipped) |
| `result.status`      | `str`             | `"ok"` or `"skip"`                              |
| `result.skip_reason` | `str`             | Why it was skipped (if `status == "skip"`)      |
| `result.lines`       | `list[str]`       | Lines actually drawn                            |
| `result.font_size`   | `int`             | Font size used (px)                             |
| `result.font_style`  | `str`             | Style selected                                  |
| `result.line_source` | `str`             | How lines were chosen: `"embedded"`, `"hyphen"` |
| `result.bbox`        | `tuple`           | Clamped bbox used                               |
| `result.box_size`    | `tuple`           | `(box_w, box_h)` after padding                  |

## Font resolution

Font candidates are tried in order:

1. `backend/assets/fonts/{name}.ttf` — custom/user-uploaded fonts (see font slot names)
2. Noto Sans — multilingual coverage (Latin, Greek, Cyrillic, Arabic partial)
3. IPA Gothic — Japanese (hiragana, katakana, kanji)
4. System fallbacks (DejaVu, Liberation, Carlito)

Recommended custom fonts (place in `backend/assets/fonts/`):

- `AnimeAce.ttf` — regular/thought/narration styles
- `Bangers-Regular.ttf` — bold style (action, SFX)

## Line-break algorithm

1. **Embedded `\n`** — if `text_translated` has `\n`, use as semantic break points.
   Each segment is treated as a preferred visual unit; segments may be further wrapped
   with hyphenation if they are too wide.
2. **pyphen hyphenation** — wraps at word boundaries first; splits long words at
   syllable boundaries with a trailing hyphen if needed. Punctuation (¿, ¡, ?, !)
   is stripped before pyphen to prevent wrong split positions.
3. **Clean-first preference** — among valid fits, the largest font size with zero
   hyphens is preferred over a larger size with hyphens.

## Vertical text (Japanese)

When `bubble_h > bubble_w * 2.0`, the renderer switches to vertical mode:
characters are drawn individually, stacked top-to-bottom in right-to-left columns.

## Backends

| Key                 | Class         | Notes                                                        |
| ------------------- | ------------- | ------------------------------------------------------------ |
| `"pil"`             | `PILRenderer` | PIL + pyphen (current default). Pure Python, no GPU.         |
| `"stablediffusion"` | _(future)_    | SD + ControlNet for style-matched text. Not yet implemented. |

## Adding a new backend

1. Implement `BaseRenderer` protocol (see `__init__.py`)
2. Register in `build_renderer()`
3. Add to the backends table above
