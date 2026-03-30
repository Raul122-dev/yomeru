"""
Backward-compatibility shim. Import from here or from stages.detection — both work.
The canonical location is: core.typesetting.stages.detection
"""
from .stages.detection import TextRegion, BaseDetector, build_detector, list_backends  # noqa: F401
from .stages.detection.ctd import CTDDetector   # noqa: F401
from .stages.detection.ogkalu import OgkaluDetector  # noqa: F401