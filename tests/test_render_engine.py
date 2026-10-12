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


def test_hyphenation_uses_the_drawn_language(run):
    """Spanish translations were hyphenated with the SOURCE language's rules
    (auto → en_US): 'REP-RESENTACIÓN', 'MOTOSIER-RA'."""
    from yomeru.lib.rendering.text_layout import LANG_MAP
    import pyphen
    assert pyphen.Pyphen(lang=LANG_MAP["Spanish"]).inserted("representación") == "re-pre-sen-ta-ción"
    from yomeru.lib.rendering import scanline_engine as eng
    seen = []
    real = eng.scanline_layout
    def spy(*a, **k):
        seen.append(a[5] if len(a) > 5 else k.get("lang_code"))
        return real(*a, **k)
    import pytest as _p
    mp = _p.MonkeyPatch(); mp.setattr(eng, "scanline_layout", spy)
    try:
        eng.render_page(run, 1)
    finally:
        mp.undo()
    assert seen and set(seen) == {"es"}


def test_two_dialogues_never_share_a_bubble(tmp_path, monkeypatch):
    """Two matches resolving to the same container were drawn on top of each
    other (Bocchi p2: drummer + bassist text in one box; Chainsaw Man p2:
    'MATAR A UN DEMONIO' over 'GRRRR'). One per container; the other is
    reported as skipped 'same_container'."""
    src = GOLDEN.parent.parent / "zz_e2e_test" / "input"
    if not src.exists():
        pytest.skip("golden zz_e2e_test not captured")
    import yomeru.core.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    shutil.copytree(src, tmp_path / "zz_e2e_test")
    r = runs.Run.load("zz_e2e_test")
    assert r is not None
    from yomeru.phases.runner import _get_phase_fn
    from yomeru.api.routes.phases import _phase_options
    for phase in ("matching", "inpainting"):
        assert _get_phase_fn(phase)(r, _phase_options(r, phase)).status == "done"
    from yomeru.lib.rendering.scanline_engine import render_page
    ev = render_page(r, 2).events
    boxes = [tuple(e["bbox"]) for e in ev if e["status"] == "ok" and not e["free"]]
    assert len(boxes) == len(set(boxes))
    assert any(e.get("skip_reason") == "same_container" for e in ev)
