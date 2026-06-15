"""
Backward-compatibility shim. The canonical location is: core.typesetting.stages.inpainting
"""
from .stages.inpainting import (  # noqa: F401
    build_inpainter, lama_available, build_text_mask, BaseInpainter,
)
from .stages.inpainting.lama import LamaInpainter, LAMA_MODEL_PATH  # noqa: F401
from .stages.inpainting.opencv import OpenCVInpainter  # noqa: F401

# legacy function alias used by old pipeline.py
def inpaint(image, mask):
    return build_inpainter("auto").inpaint(image, mask)