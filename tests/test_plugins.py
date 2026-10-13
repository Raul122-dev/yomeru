"""Backend registry + inpainting as the first registered backend."""
import pytest
from tests.test_phase1_critical import client  # noqa: F401 (fixture)

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
    # an unknown backend loads flagged (old snapshots stay viewable) — see
    # test_unknown_backend_keeps_old_runs_loadable_but_not_new_defaults
    assert InpaintingSettings.model_validate({"backend": "nope"}).available is False
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
    assert RenderingSettings.model_validate({"backend": "nope"}).available is False

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



def test_options_are_versioned_and_migrated(monkeypatch):
    """A plugin bumps its options schema and ships a migration: stored settings
    and run snapshots with the old version are upgraded step by step; a newer
    stored version (downgrade) is refused instead of silently mis-read."""
    from pydantic import BaseModel
    from yomeru.core.settings import MatchingSettings
    from yomeru.plugins import _REGISTRY, register

    monkeypatch.setitem(_REGISTRY, "matching", dict(_REGISTRY.get("matching") or {}))

    class V3(BaseModel):
        strength: float = 0.5
        mode: str = "fast"

    def migrate(v, o):
        if v == 1:   # v1 called it "power", 0..100
            return {"strength": o.pop("power", 50) / 100}
        if v == 2:   # v2 had no mode
            return {**o, "mode": "fast"}
        raise AssertionError(v)

    @register("matching", "_m", options=V3, version="3.1.0", schema_version=3, migrate=migrate)
    class M:
        def __init__(self, o): pass

    s = MatchingSettings.model_validate({"backend": "_m", "schema_version": 1, "options": {"power": 80}})
    assert s.options == {"strength": 0.8, "mode": "fast"}
    assert (s.schema_version, s.plugin_version) == (3, "3.1.0")
    # unversioned (saved before versioning) = v1
    assert MatchingSettings.model_validate({"backend": "_m", "options": {"power": 20}}).options["strength"] == 0.2
    with pytest.raises(ValueError, match="newer version"):
        MatchingSettings.model_validate({"backend": "_m", "schema_version": 4, "options": {}})


def test_unknown_backend_keeps_old_runs_loadable_but_not_new_defaults(client):
    """A removed third-party plugin: its run snapshots still load (options kept
    untouched, flagged unavailable); defaults/presets cannot select it; running
    the phase says why."""
    from yomeru.core.settings import PipelineSettings, require_available
    s = PipelineSettings.model_validate({"matching": {"backend": "gone", "options": {"x": 1}}})
    assert s.matching.available is False and s.matching.options == {"x": 1}
    assert s.model_dump()["matching"]["backend"] == "gone"
    with pytest.raises(ValueError, match="not installed"):
        require_available(s)
    r = client.patch("/api/config/settings", json={"matching": {"backend": "gone"}})
    assert r.status_code == 422
    with pytest.raises(UnknownBackend):
        get_backend("matching", "gone")


def test_backend_listing_has_defaults_and_versions():
    b = next(x for x in list_backends("matching") if x["name"] == "cascade")
    assert b["defaults"] == {"ocr_weight": 0.4, "spatial_weight": 0.4, "min_score": 0.05}
    assert b["schema_version"] == 1 and b["compatible"] is True
    props = b["options"]["properties"]
    assert props["min_score"]["maximum"] == 0.5 and props["ocr_weight"]["type"] == "number"
