"""Phase 2C: settings schema, migration, connections, presets, run snapshots."""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from tests.test_phase1_critical import client  # noqa: F401  (fixture)

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
    from yomeru.core.settings import AppConfig, migrate
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
    assert (s.detection.backend, s.detection.threshold) == ("ctd", 0.3)
    assert s.matching.ocr_weight == 0.5


def test_store_migrates_file_and_keeps_backup(tmp_path, monkeypatch):
    import yomeru.core.settings as st
    monkeypatch.setattr(st, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps(V1))
    cfg = st.ConfigStore().load()
    assert cfg.schema_version == 2
    assert json.loads((tmp_path / "config.v1.bak.json").read_text()) == V1
    assert json.loads((tmp_path / "config.json").read_text())["schema_version"] == 2


def test_resolution_order(client):
    from yomeru.core.settings import resolve_settings
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
    client.patch("/api/config/settings", json={"analysis_model": {"model": ""}})
    r = client.post("/api/runs", data={"name": "x", "auto_start": "false"},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 400


def test_invalid_settings_rejected(client):
    r = client.patch("/api/config/settings", json={"detection": {"threshold": 5}})
    assert r.status_code == 422


def test_legacy_run_meta_still_resolves(client):
    from yomeru.core.settings import run_settings
    s = run_settings({"model": "old-model", "provider": "custom", "detector_threshold": 0.35,
                      "target_language": "Spanish", "comic_format": "manga"})
    assert s.analysis_model.model == "old-model"
    assert s.detection.threshold == 0.35


def test_deleting_connection_clears_references(client):
    cfg = client.get("/api/config").json()
    cid = cfg["settings"]["analysis_model"]["connection_id"]
    cfg = client.delete(f"/api/config/connections/{cid}").json()
    assert cfg["settings"]["analysis_model"]["connection_id"] == ""
