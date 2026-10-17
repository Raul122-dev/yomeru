# Inpainting

Erase the source lettering of every matched text region.

## Contract
- Phase: `stages/inpainting/phase.py` → backend `classic` (`stages/inpainting/plugins.py`).
- Request/result: `pipeline/contracts.InpaintRequest` (original page, targets from
  the effective matches, the user's mask edit) → `InpaintResult` (page, final
  mask, stats, debug images). Output `typeset/debug/pNN_s4_inpainted.png`.

## `classic`
Per region, by label (`config/labels`):
- `text_bubble` → `build_text_mask`: Otsu inside the box minus components that
  touch the border, filled with OpenCV (`stages/inpainting/opencv.py`, NS or Telea
  by masked area).
- `text_free` → the whole box, filled with LaMa (`stages/inpainting/lama.py`,
  big-lama TorchScript, weights downloaded to `data/models/lama/` on first use;
  pages above 2048 px go through the downscale path). OpenCV if LaMa is not
  available or the option says so.
Then the mask editor's RGBA delta is applied on top.

`stages/inpainting.build_inpainter("lama" | "opencv" | "auto")` builds the two
techniques for the plugin.
