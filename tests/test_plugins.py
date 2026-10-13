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



def test_rendering_backend_is_swappable(tmp_path, monkeypatch):
    """Rendering is a registered backend: a new technique gets the same
    RenderRequest (edits resolved) and its RenderResult is what the phase
    writes — without touching the engine or the phase."""
    import shutil
    from pathlib import Path
    from PIL import Image
    from pydantic import BaseModel
    from yomeru.core.contracts import RenderRequest, RenderResult
    from yomeru.core.settings import RenderingSettings
    from yomeru.plugins import register
    import yomeru.core.runs as runs

    assert "scanline" in [b["name"] for b in list_backends("rendering")]
    assert RenderingSettings().backend == "scanline"
    with pytest.raises(ValueError):
        RenderingSettings.model_validate({"backend": "nope"})

    seen = {}

    class NoOpts(BaseModel):
        pass

    from yomeru.plugins import _REGISTRY
    monkeypatch.setitem(_REGISTRY, "rendering", dict(_REGISTRY.get("rendering") or {}))  # undone after the test

    @register("rendering", "_test_fill", options=NoOpts)
    class Fill:
        def __init__(self, options): pass

        def render_page(self, req: RenderRequest) -> RenderResult:
            seen["req"] = req
            return RenderResult(image=Image.new("RGB", req.inpainted.size, (1, 2, 3)),
                                events=[{"dialogue_index": 0, "status": "ok"}])

    src = Path(__file__).resolve().parents[1] / "data" / "goldens" / "d4c17c9bf8f5" / "input"
    if not src.exists():
        pytest.skip("golden d4c17c9bf8f5 not captured")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    shutil.copytree(src, tmp_path / "r")
    run = runs.Run.load("r")
    # matching + inpainting on the frozen detections/analysis (OCR stubbed: no models)
    import yomeru.lib.matching.hungarian as hung
    import yomeru.lib.matching.ocr as ocr
    monkeypatch.setattr(hung, "ocr_region", lambda *a, **k: "", raising=False)
    monkeypatch.setattr(ocr, "ocr_region", lambda *a, **k: "", raising=False)
    from yomeru.api.routes.phases import _phase_options
    from yomeru.phases.matching import run as match
    from yomeru.phases.inpainting import run as inpaint
    match(run, _phase_options(run, "matching"), page_scope=[1])
    inpaint(run, {"backend": "classic", "backend_options": {"free_text": "opencv"}}, page_scope=[1])
    from yomeru.phases.rendering import run as render
    res = render(run, {"backend": "_test_fill"}, page_scope=[1])
    assert res.status == "done"
    r = seen["req"]
    assert r.lang_code == "es" and r.matches and r.dialogues and r.containers
    from yomeru.core import artifacts
    out = Image.open(artifacts.page_artifact(run, 1, artifacts.SCANLINE_PRODUCTION))
    assert out.getpixel((0, 0)) == (1, 2, 3)
    assert artifacts.load_render_log(run, 1)["s5_rendering"]["renders"] == [{"dialogue_index": 0, "status": "ok"}]
