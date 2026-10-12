"""The render engine's own records + the rendering settings that used to be dead."""
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

GOLDEN = Path(__file__).resolve().parents[1] / "data" / "goldens" / "d4c17c9bf8f5" / "input"


@pytest.fixture()
def run(tmp_path, monkeypatch):
    if not GOLDEN.exists():
        pytest.skip("golden run not captured (scripts/golden.py capture d4c17c9bf8f5)")
    import yomeru.core.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    shutil.copytree(GOLDEN, tmp_path / "d4c17c9bf8f5")
    r = runs.Run.load("d4c17c9bf8f5")
    assert r is not None
    from yomeru.phases.runner import _get_phase_fn
    from yomeru.api.routes.phases import _phase_options
    for phase in ("matching", "inpainting"):
        assert _get_phase_fn(phase)(r, _phase_options(r, phase)).status == "done"
    return r


def test_render_log_is_what_the_engine_drew(run):
    from yomeru.lib.rendering.scanline_engine import render_page
    out = render_page(run, 1)
    ok = [e for e in out.events if e["status"] == "ok"]
    assert len(ok) == out.layouts > 0
    for e in ok:
        assert e["font_size"] > 0 and e["lines"] and len(e["bbox"]) == 4
        # the drawn lines are the used text (layout only re-wraps it)
        squash = lambda t: "".join(ch for ch in t if ch.isalnum())  # noqa: E731
        assert squash("".join(e["lines"])) == squash(e["text"])


def test_use_translation_false_renders_the_original_text(run):
    from yomeru.lib.rendering.scanline_engine import render_page
    tr = {e["dialogue_index"]: e for e in render_page(run, 1, use_translation=True).events if e["status"] == "ok"}
    og = {e["dialogue_index"]: e for e in render_page(run, 1, use_translation=False).events if e["status"] == "ok"}
    assert set(tr) == set(og)
    assert any(tr[i]["text"] != og[i]["text"] for i in tr)
    from yomeru.core import artifacts
    dlgs = artifacts.page_analysis(artifacts.load_analyses(run), 1)["dialogues"]
    assert all(og[i]["text"] == dlgs[i]["text"] for i in og)


def test_font_size_override_caps_the_size_and_survives_normalisation(run):
    import json
    from yomeru.core import artifacts
    from yomeru.lib.rendering.scanline_engine import render_page
    base = {e["dialogue_index"]: e for e in render_page(run, 1).events if e["status"] == "ok"}
    i, ev = max(base.items(), key=lambda kv: kv[1]["font_size"])
    fixed = max(9, ev["font_size"] // 2)
    artifacts.page_artifact(run, 1, artifacts.RENDER_OVERRIDES).write_text(
        json.dumps([{"dialogue_index": i, "font_size_override": fixed}]))
    after = {e["dialogue_index"]: e for e in render_page(run, 1).events if e["status"] == "ok"}
    assert after[i]["font_size"] <= fixed and after[i]["size_fixed"]
    prod = artifacts.page_artifact(run, 1, artifacts.SCANLINE_PRODUCTION)
    assert np.asarray(Image.open(prod)).any()
