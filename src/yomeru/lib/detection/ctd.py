"""
CTD (Comic Text Detector) detection backend.

Model: comictextdetector.pt (dmMaze / zyddnys)
- Provides pixel-level segmentation masks (useful for irregular bubble shapes)
- Requires manual download to: models/ctd/comictextdetector.pt
  Source: https://github.com/zyddnys/manga-image-translator/releases/tag/beta-0.2.1

See SPEC.md for the full input/output contract.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import TextRegion

_MODEL_PATH = Path(__file__).parent.parent.parent.parent.parent / "models" / "ctd" / "comictextdetector.pt"


class CTDDetector:
    """Comic Text Detector with pixel-level segmentation masks."""

    DEFAULT_MODEL_PATH = _MODEL_PATH

    def __init__(self, model_path: Path | None = None) -> None:
        self._model_path = model_path or self.DEFAULT_MODEL_PATH
        self._model: Any = None

    @property
    def name(self) -> str:
        return "ctd"

    @classmethod
    def is_available(cls) -> bool:
        return cls.DEFAULT_MODEL_PATH.exists()

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"comictextdetector.pt not found at {self._model_path}\n"
                "Download from: https://github.com/zyddnys/manga-image-translator/releases/tag/beta-0.2.1"
            )
        import torch
        print("  [detector] loading CTD…", file=sys.stderr)

        import io as _io

        def _try_extract_model(obj: object, depth: int = 0) -> "object | None":
            """Recursively try to find or reconstruct a usable model."""
            if obj is None:
                return None
            if hasattr(obj, "eval"):
                return obj
            if isinstance(obj, (bytes, bytearray)):
                try:
                    return torch.jit.load(_io.BytesIO(obj), map_location="cpu")
                except Exception:
                    return None
            if isinstance(obj, dict) and depth < 3:
                # If the dict looks like a state dict (all values are tensors),
                # try loading it into the CTDBlkDet architecture
                values = list(obj.values())
                # Check if this looks like a state dict (values are tensors or nested dicts)
                key_types = {k: type(v).__name__ for k, v in obj.items()}
                print(f"  [detector] CTD: sub-dict has {len(values)} keys, types={key_types}", file=sys.stderr)

                # Pattern 1: {'weights': OrderedDict, 'cfg': dict} — standard CTD blk_det format
                if "weights" in obj and "cfg" in obj:
                    weights = obj["weights"]
                    cfg     = obj["cfg"]
                    nc = int(cfg.get("nc", 2))
                    gw = float(cfg.get("width_multiple", 0.5))
                    gd = float(cfg.get("depth_multiple", 0.33))
                    print(f"  [detector] CTD: weights+cfg — nc={nc} gw={gw} gd={gd}", file=sys.stderr)
                    if hasattr(weights, "items"):
                        try:
                            from .ctd_arch import CTDBlkDet
                            mdl = CTDBlkDet(nc=nc)
                            missing, unexpected = mdl.load_state_dict(weights, strict=False)
                            if missing:
                                print(f"  [detector] CTD: {len(missing)} missing keys", file=sys.stderr)
                            if unexpected:
                                print(f"  [detector] CTD: {len(unexpected)} unexpected keys", file=sys.stderr)
                            print("  [detector] CTD: state dict loaded OK", file=sys.stderr)
                            return mdl
                        except Exception as e:
                            import traceback as _ctb
                            print(f"  [detector] CTD weights load failed: {e}", file=sys.stderr)
                            print(_ctb.format_exc(), file=sys.stderr)

                # Pattern 2: direct state dict (all values are tensors)
                is_state_dict = bool(values) and all(
                    isinstance(v, torch.Tensor) for v in values[:5]
                )
                if is_state_dict:
                    try:
                        from .ctd_arch import CTDBlkDet
                        for nc in (4, 2, 1, 80):
                            try:
                                mdl = CTDBlkDet(nc=nc)
                                mdl.load_state_dict(obj, strict=False)
                                print(f"  [detector] CTD: loaded state dict nc={nc}", file=sys.stderr)
                                return mdl
                            except Exception as inner_e:
                                print(f"  [detector] CTD nc={nc} failed: {inner_e}", file=sys.stderr)
                    except Exception as e:
                        print(f"  [detector] CTD state dict error: {e}", file=sys.stderr)

                # try known keys recursively
                for key in ("blk_det", "model", "net", "detector"):
                    if key in obj:
                        result = _try_extract_model(obj[key], depth + 1)
                        if result is not None:
                            print(f"  [detector] CTD: extracted from key '{key}'", file=sys.stderr)
                            return result
            return None

        model = None
        try:
            model = torch.jit.load(str(self._model_path), map_location="cpu")
        except Exception:
            try:
                raw = torch.load(str(self._model_path), map_location="cpu", weights_only=False)
                print(
                    f"  [detector] CTD checkpoint type: {type(raw).__name__}"
                    + (f", keys: {list(raw.keys())}" if isinstance(raw, dict) else ""),
                    file=sys.stderr,
                )
                model = _try_extract_model(raw)
            except Exception as load_err:
                raise RuntimeError(f"CTD: failed to load checkpoint: {load_err}") from load_err

        if model is None or not hasattr(model, "eval"):
            raise RuntimeError(
                "CTD: could not extract a usable model from the checkpoint. "
                "This CTD file format requires the model architecture to load state dicts, "
                "which yomeru does not include. "
                "Use ogkalu instead, or download the TorchScript version of comictextdetector.pt."
            )

        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()

        self._model = model
        print("  [detector] CTD ready", file=sys.stderr)

    def detect(self, image: Image.Image, threshold: float = 0.5) -> list[TextRegion]:
        self._load()
        assert self._model is not None
        import cv2
        import torch
        import torchvision.transforms.functional as TF

        img_w, img_h = image.size
        tensor = TF.to_tensor(image.resize((1024, 1024))).unsqueeze(0)
        # ScriptModules may not expose .parameters() — use a safer device check
        try:
            device = next(self._model.parameters()).device  # type: ignore[union-attr]
        except (StopIteration, AttributeError):
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        tensor = tensor.to(device)

        with torch.no_grad():
            output = self._model(tensor)

        regions: list[TextRegion] = []

        # Handle two output formats:
        # 1. YOLO format from CTDBlkDet: (predictions_tensor, layer_list)
        # 2. Segmentation format from TorchScript CTD: probs tensor [classes, H, W]
        if isinstance(output, tuple) and len(output) == 2 and isinstance(output[0], torch.Tensor):
            # YOLO format: output[0] is [batch, n_boxes, 5+nc]
            preds = output[0][0]  # first batch item
            label_names = ["bubble", "text_free", "text_bubble", "sfx"]
            conf_thresh = max(threshold, 0.25)
            for det in preds:
                conf = float(det[4])
                if conf < conf_thresh:
                    continue
                class_scores = det[5:]
                class_id = int(class_scores.argmax())
                # scale boxes from 1024x1024 back to original image size
                cx, cy, w, h = det[:4].tolist()
                sx, sy = img_w / 1024, img_h / 1024
                x1 = int((cx - w / 2) * sx)
                y1 = int((cy - h / 2) * sy)
                x2 = int((cx + w / 2) * sx)
                y2 = int((cy + h / 2) * sy)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img_w, x2), min(img_h, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                label = label_names[class_id] if class_id < len(label_names) else "bubble"
                regions.append(TextRegion(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    label=label, score=conf * float(class_scores[class_id]),
                ))
        else:
            # Segmentation format: output[0] is [classes, H, W]
            probs = output[0] if isinstance(output, (list, tuple)) else output
            for class_idx, label in enumerate(["text", "bubble"], start=1):
                if class_idx >= probs.shape[0]:
                    continue
                mask_prob = probs[class_idx].cpu().numpy()
                binary = (mask_prob > 0.5).astype(np.uint8) * 255
                mask_full = cv2.resize(binary, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
                n, labels_im, stats, _ = cv2.connectedComponentsWithStats(mask_full)
                for i in range(1, n):
                    x, y, w, h, area = stats[i]
                    if area < 200:
                        continue
                    region_mask = np.zeros((img_h, img_w), dtype=np.uint8)
                    region_mask[labels_im == i] = 255
                    regions.append(TextRegion(
                        x1=x, y1=y, x2=x+w, y2=y+h,
                        label=label, score=1.0, mask=region_mask,
                    ))

        print(f"  [detector] CTD: {len(regions)} regions", file=sys.stderr)
        return regions