"""
Typesetting implementations — detection, matching, inpainting, rendering.

The actual implementations live in stages/ subpackages.
Phase orchestration is handled by yomeru.phases.* modules.
"""
# Stage access — import directly from stages subpackages
from .stages import detection, matching, inpainting, rendering  # noqa: F401