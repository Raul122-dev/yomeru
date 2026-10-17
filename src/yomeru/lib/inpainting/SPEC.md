# Inpainting

Erase the source lettering of every matched text region.

## Contract
- Phase: `phases/inpainting.py` → backend `classic` (`plugins/inpainting.py`).
- Request/result: `core/contracts.InpaintRequest` (original page, targets from
  the effective matches, the user's mask edit) → `InpaintResult` (page, final
  mask, stats, debug images). Output `typeset/debug/pNN_s4_inpainted.png`.

## `classic`
Per region, by label (`core/labels`):
- `text_bubble` → `build_text_mask`: Otsu inside the box minus components that
  touch the border, filled with OpenCV (`lib/inpainting/opencv.py`, NS or Telea
  by masked area).
- `text_free` → the whole box, filled with LaMa (`lib/inpainting/lama.py`,
  big-lama TorchScript, weights downloaded to `data/models/lama/` on first use;
  pages above 2048 px go through the downscale path). OpenCV if LaMa is not
  available or the option says so.
Then the mask editor's RGBA delta is applied on top.

`lib/inpainting.build_inpainter("lama" | "opencv" | "auto")` builds the two
techniques for the plugin.
