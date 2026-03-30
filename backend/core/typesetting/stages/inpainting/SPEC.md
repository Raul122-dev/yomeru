# Stage 3 — Inpainting

Remove source text from the page image, leaving clean background for re-typesetting.

## Input

| Field   | Type              | Description                                                            |
| ------- | ----------------- | ---------------------------------------------------------------------- |
| `image` | `PIL.Image.Image` | Full page image                                                        |
| `mask`  | `np.ndarray`      | Binary uint8 mask (same HxW as image). 255 = pixels to erase, 0 = keep |

## Output

`PIL.Image.Image` — inpainted image, same size as input. Masked pixels filled with
reconstructed background.

## Backends

| Key        | Class             | Notes                                                                                                                                                                                                 |
| ---------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `"lama"`   | `LamaInpainter`   | Deep learning model (big-lama.pt). Best quality, especially for complex backgrounds. Requires `models/lama/big-lama.pt`. Download via `python setup_typesetting.py --download-lama`. GPU recommended. |
| `"opencv"` | `OpenCVInpainter` | OpenCV NS/Telea. Always available, no GPU needed. Good for clean manga with simple backgrounds. Uses NS for large areas, Telea for small details.                                                     |
| `"auto"`   | —                 | Uses LaMa if checkpoint present, else OpenCV                                                                                                                                                          |

## Text mask generation

The `build_text_mask(image, region_bbox, region_mask)` helper (also in this module)
creates a binary mask of text pixels within a detected region using Otsu thresholding:

1. Convert region to grayscale
2. Sample region brightness to determine text color (dark on white vs white on dark)
3. Apply Otsu threshold to separate text from background
4. Dilate slightly to cover anti-aliasing artifacts

## Adding a new backend

1. Implement `BaseInpainter` protocol (see `__init__.py`)
2. Register in `build_inpainter()`
3. Update the backends table above

## Notes

- LaMa requires input dimensions divisible by 8 (padded internally with reflect mode)
- For pages with no matched regions, inpainting is skipped entirely
- Inpainting is applied to a **combined mask** of all matched regions at once,
  which is more efficient and avoids running the model multiple times per page
