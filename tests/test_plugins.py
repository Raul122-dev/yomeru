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
