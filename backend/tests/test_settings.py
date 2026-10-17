"""Phase 2C: settings schema, migration, connections, presets, run snapshots."""
from __future__ import annotations

import io
import json

from PIL import Image


V1 = {
    "providers": {
        "anthropic": {"api_key": "sk-ant-xxxxxxxxxxxx", "base_url": ""},
        "openai": {"api_key": ""},
        "google": {"api_key": "AIza-ignored"},
        "custom": {"base_url": "https://openrouter.ai/api", "api_key": "sk-or-yyyyyyyyyyyy"},
    },
    "defaults": {"model": "google/gemini-3.1-pro-preview", "format": "manga", "provider": "",
                 "source_language": "auto", "target_language": "Spanish"},
    "translation": {"enabled": False, "model": "", "provider": "", "base_url": "", "api_key": ""},
    "phases": {"detection": {"backend": "ctd", "threshold": 0.3},
               "matching": {"backend": "hungarian", "ocr_weight": 0.5, "spatial_weight": 0.3,
                            "position_weight": 0.2, "min_score": 0.05},
               "inpainting": {"backend": "auto"},
               "rendering": {"backend": "pil", "use_translation": True, "skip_sfx": True}},
}


def test_migration_v1_to_v2():
    from yomeru.config.settings import AppConfig, migrate
    cfg = AppConfig.model_validate(migrate(json.loads(json.dumps(V1))))
    ids = {c.id: c for c in cfg.connections}
    assert set(ids) == {"custom", "anthropic"}          # google dropped, empty openai skipped
    assert ids["custom"].name == "OpenRouter"
    assert ids["custom"].base_url == "https://openrouter.ai/api/v1"
    assert ids["custom"].api_key == "sk-or-yyyyyyyyyyyy"
    assert ids["anthropic"].protocol == "anthropic"
    s = cfg.settings
    assert (s.analysis_model.connection_id, s.analysis_model.model) == ("custom", "google/gemini-3.1-pro-preview")
    assert not s.translation_model.is_set()
    assert s.language.comic_format == "manga"
    # CTD was retired: legacy "ctd" coerces to the only detector
    assert (s.detection.backend, s.detection.threshold) == ("ogkalu", 0.3)
    # flat matching knobs migrate into the cascade backend's options
    assert s.matching.backend == "cascade" and s.matching.options["ocr_weight"] == 0.5


def test_store_migrates_file_and_keeps_backup(tmp_path, monkeypatch):
    import yomeru.config.settings as st
    monkeypatch.setattr(st, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps(V1))
    cfg = st.ConfigStore().load()
    assert cfg.schema_version == 2
    assert json.loads((tmp_path / "config.v1.bak.json").read_text()) == V1
    assert json.loads((tmp_path / "config.json").read_text())["schema_version"] == 2


def test_resolution_order(client):
    from yomeru.config.settings import resolve_settings
    client.patch("/api/config/settings", json={"language": {"target": "English"}})
    cfg = client.post("/api/config/presets", json={"name": "jp-es"}).json()
    pid = cfg["presets"][0]["id"]
    preset = cfg["presets"][0]["settings"]
    preset["language"]["target"] = "Spanish"
    preset["detection"]["threshold"] = 0.25
    client.put(f"/api/config/presets/{pid}", json={"name": "jp-es", "settings": preset})
    s = resolve_settings(pid, {"detection": {"threshold": 0.6}})
    assert s.language.target == "Spanish"        # preset beats global
    assert s.detection.threshold == 0.6          # override beats preset
    assert resolve_settings().language.target == "English"


def _png() -> bytes:
    buf = io.BytesIO(); Image.new("RGB", (8, 8)).save(buf, "PNG"); return buf.getvalue()


def test_run_snapshot_is_frozen(client):
    r = client.post("/api/runs", data={"name": "snap", "auto_start": "false",
                                       "settings": json.dumps({"language": {"target": "French"}})},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["settings"]["language"]["target"] == "French"
    client.patch("/api/config/settings", json={"language": {"target": "German"}})
    meta2 = client.get(f"/api/runs/{meta['id']}").json()
    assert meta2["settings"]["language"]["target"] == "French"


def test_run_requires_a_model(client):
    """The API is the default: without a provider + model a run is refused,
    with a message that offers both ways out. The local mode is an explicit,
    experimental opt-in that needs no provider."""
    client.patch("/api/config/settings", json={"analysis_model": {"model": ""}})
    from yomeru.config.settings import PipelineSettings
    assert PipelineSettings().analysis.backend == "vlm"
    r = client.post("/api/runs", data={"name": "x", "auto_start": "false"},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 400 and "local mode" in r.json()["detail"]
    r = client.post("/api/runs", data={"name": "x", "auto_start": "false",
                                       "settings": json.dumps({"analysis": {"backend": "local"}})},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 201, r.text


def test_invalid_settings_rejected(client):
    r = client.patch("/api/config/settings", json={"detection": {"threshold": 5}})
    assert r.status_code == 422


def test_legacy_run_meta_still_resolves(client):
    from yomeru.config.settings import run_settings
    s = run_settings({"model": "old-model", "provider": "custom", "detector_threshold": 0.35,
                      "target_language": "Spanish", "comic_format": "manga"})
    assert s.analysis_model.model == "old-model"
    assert s.detection.threshold == 0.35


def test_deleting_connection_clears_references(client):
    cfg = client.get("/api/config").json()
    cid = cfg["settings"]["analysis_model"]["connection_id"]
    cfg = client.delete(f"/api/config/connections/{cid}").json()
    assert cfg["settings"]["analysis_model"]["connection_id"] == ""



def test_switching_technique_through_overrides_drops_the_old_options(client):
    """global=local (model/server/… options) + run override vlm must not carry
    the local options into VlmOptions (extra=forbid → 'invalid settings')."""
    from yomeru.config.settings import resolve_settings
    client.patch("/api/config/settings", json={"analysis": {"backend": "local", "options": {"model": "qwen3.5:9b"},
                                                            "separate_translation": {"enabled": True, "local": True}}})
    s = resolve_settings(overrides={"analysis": {"backend": "vlm"}})
    assert s.analysis.backend == "vlm" and s.analysis.options == {}
    assert s.analysis.separate_translation.enabled   # the rest of the phase settings are kept
    s = resolve_settings(overrides={"analysis": {"options": {"think": True}}})   # same technique: merge
    assert s.analysis.options["model"] == "qwen3.5:9b" and s.analysis.options["think"] is True



def test_run_metadata_names_the_model_that_actually_reads(client):
    """A run with the local technique listed the API model from the global settings."""
    files = [("files", ("a.png", _png(), "image/png"))]
    r = client.post("/api/runs", data={"name": "x", "auto_start": "false",
                                       "settings": json.dumps({"analysis": {"backend": "local", "options": {"model": "qwen3.5:9b"}}})},
                    files=files)
    m = client.get(f"/api/runs/{r.json()['id']}").json()
    assert m["model"] == "local · qwen3.5:9b" and m["connection_name"] == ""


def test_descriptions_follow_the_target_language():
    """The separate 'UI language' setting was never written nor shown; descriptions
    are written in the target language."""
    from PIL import Image
    from yomeru.stages.analysis.analyzer import prepare
    from yomeru.pipeline.contracts import AnalysisRequest
    import inspect
    import yomeru.stages.analysis.phase as pa
    assert "descriptions_language = target_language" in inspect.getsource(pa.run)
    p = prepare(AnalysisRequest(image=Image.new("RGB", (64, 64)), page_number=1, regions=[],
                                target_language="French", descriptions_language="French"))
    assert "Descriptions language: French" in p.user_text


def test_languages_endpoint_offers_targets_only_with_a_shipped_font(client):
    langs = {lang["name"]: lang for lang in client.get("/api/config/languages").json()}
    assert langs["auto"]["label"] == "Auto-detect"
    assert langs["Spanish"] == {"name": "Spanish", "label": "Spanish", "code": "es",
                                "script": "latin", "has_font": True}
    assert langs["Turkish"]["has_font"]
    assert not langs["Japanese"]["has_font"] and not langs["Vietnamese"]["has_font"]
    assert not langs["Russian"]["has_font"]


def test_shipped_font_letters_every_latin_target():
    """has_font for Latin rests on this: the shipped ComicNeue (with the default
    raqm layout, which composes İ) draws their letters, not .notdef boxes."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from yomeru.config.paths import FONTS_DIR
    for name in ("ComicNeue-Bold.ttf", "ComicNeue-Regular.ttf"):
        font = ImageFont.truetype(str(FONTS_DIR / name), 48)

        def draw(ch):
            im = Image.new("L", (90, 90))
            ImageDraw.Draw(im).text((10, 5), ch, font=font, fill=255)
            return np.asarray(im)
        tofu = draw("\u0e01")                      # Thai: not in the font
        for ch in "ñ¿¡çãõàèéêëîïœßäöüąćęłńśźżİığşÇĞŞ":
            assert not (draw(ch) == tofu).all(), f"{name} has no glyph for {ch!r}"
