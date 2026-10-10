"""Region-id integrity between detection → analysis → matching (B-ARQ-2, B-ARQ-3)."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import yomeru.core.paths as paths
    import yomeru.core.runs as runs
    import yomeru.core.settings as settings

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "runs").mkdir()
    from yomeru.app import app
    c = TestClient(app)
    c.post("/api/config/connections", json={"name": "Local", "protocol": "openai",
                                            "base_url": "http://127.0.0.1:9/v1"})
    c.patch("/api/config/settings", json={"analysis_model": {"model": "test-model"}})
    return c


def test_badge_number_is_region_id_not_list_index(monkeypatch):
    """After deleting box 1 in the editor, ids are [2, 5]: badges must read 2 and 5."""
    from yomeru.core import annotator

    drawn: list[str] = []
    real_text = ImageDraw.ImageDraw.text

    def text(self, xy, txt, *a, **k):
        drawn.append(str(txt))
        return real_text(self, xy, txt, *a, **k)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    regions = [
        {"id": 2, "x1": 10, "y1": 10, "x2": 60, "y2": 60, "label": "text_bubble"},
        {"id": 5, "x1": 100, "y1": 100, "x2": 160, "y2": 160, "label": "text_free"},
    ]
    annotator.annotate_from_detections(Image.new("RGB", (200, 200), "white"), regions)
    assert drawn == ["2", "5"]


def test_hungarian_never_reuses_a_region_claimed_by_region_id(client, monkeypatch):
    """Dialogue 0 claims region 1 directly; dialogue 1 has no region_id and a
    hint right on top of region 1. The fallback must only consider region 2."""
    from yomeru.core.runs import Run
    from yomeru.lib import matching as libm
    from yomeru.phases import matching

    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, "PNG")
    r = client.post("/api/runs", data={"name": "t", "auto_start": "false"},
                    files=[("files", ("p.png", buf.getvalue(), "image/png"))])
    run = Run.load(r.json()["id"])
    assert run is not None
    out = run.output_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "page_detections.json").write_text(json.dumps([{
        "page_number": 1, "original_w": 300, "original_h": 400,
        "regions": [
            {"id": 1, "x1": 10, "y1": 10, "x2": 140, "y2": 120, "label": "text_bubble", "score": 0.9},
            {"id": 2, "x1": 160, "y1": 250, "x2": 290, "y2": 390, "label": "text_bubble", "score": 0.9},
        ],
    }]))
    (out / "page_analyses.json").write_text(json.dumps([{
        "page_number": 1, "analysis_image_w": 300, "analysis_image_h": 400,
        "source_language": "English",
        "dialogues": [
            {"text": "A", "text_translated": "a", "region_id": 1, "bbox": [10, 10, 140, 120]},
            {"text": "B", "text_translated": "b", "region_id": None, "bbox": [12, 12, 138, 118]},
        ],
    }]))

    seen: list[list[tuple]] = []
    real_build = libm.build_matcher

    def build(*a, **k):
        m = real_build(*a, **k)
        real_match = m.match

        def match(**kw):
            seen.append([(rg.x1, rg.y1, rg.x2, rg.y2) for rg in kw["regions"]])
            return real_match(**kw)

        m.match = match
        return m

    monkeypatch.setattr(libm, "build_matcher", build)
    # No OCR models in tests
    monkeypatch.setattr("yomeru.lib.matching.hungarian.ocr_region", lambda *a, **k: "")
    monkeypatch.setattr("yomeru.lib.matching.ocr.ocr_region", lambda *a, **k: "")

    matching.run(run, options={})

    assert seen, "fallback matcher was not called"
    assert (10, 10, 140, 120) not in seen[0], "claimed region offered to the fallback"
    log = json.loads((out / "typeset" / "debug" / "p01_render_log.json").read_text())
    rids = [m["region_id"] for m in log["s3_matching"]["matches"]]
    assert len(rids) == len(set(rids)), f"a region was assigned twice: {rids}"
