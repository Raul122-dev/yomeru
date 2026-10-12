"""Backend registry + inpainting as the first registered backend."""
import pytest

from yomeru.core.settings import InpaintingSettings
from yomeru.plugins import UnknownBackend, get_backend, list_backends


def test_classic_inpainting_is_registered_with_options_schema():
    names = [b["name"] for b in list_backends("inpainting")]
    assert "classic" in names
    classic = next(b for b in list_backends("inpainting") if b["name"] == "classic")
    assert classic["options"]["properties"]["free_text"]["enum"] == ["lama", "opencv"]


@pytest.mark.parametrize("legacy,free_text", [("auto", "lama"), ("lama", "lama"), ("opencv", "opencv")])
def test_legacy_engine_names_map_to_classic(legacy, free_text):
    s = InpaintingSettings.model_validate({"backend": legacy})
    assert s.backend == "classic" and s.options == {"free_text": free_text}


def test_unknown_backend_or_option_is_rejected():
    with pytest.raises(ValueError):
        InpaintingSettings.model_validate({"backend": "nope"})
    with pytest.raises(ValueError):
        InpaintingSettings.model_validate({"backend": "classic", "options": {"free_text": "magic"}})
    with pytest.raises(UnknownBackend):
        get_backend("inpainting", "nope")


def test_backend_instances_are_cached_per_options():
    _, a = get_backend("inpainting", "classic", {"free_text": "opencv"})
    _, b = get_backend("inpainting", "classic", {"free_text": "opencv"})
    assert a is b


def test_detection_threshold_reaches_the_model(monkeypatch):
    """B-ARQ-1: the setting was applied after ogkalu's own 0.5 cut, so anything
    below 0.5 never had an effect. The threshold must be passed to the model."""
    from yomeru.lib.detection import TextRegion
    from yomeru.lib.detection.ogkalu import OgkaluDetector

    seen = {}

    def fake_detect(self, image, threshold=0.5):
        seen["threshold"] = threshold
        return [TextRegion(1, 1, 5, 5, "text_free", 0.45)] if threshold <= 0.45 else []

    monkeypatch.setattr(OgkaluDetector, "detect", fake_detect)
    from PIL import Image
    _, backend = get_backend("detection", "ogkalu")
    out = backend.detect(Image.new("RGB", (10, 10)), threshold=0.4)
    assert seen["threshold"] == 0.4
    assert [r["score"] for r in out] == [0.45]
