"""Regression tests for the Phase 1 critical fixes. Run: uv run pytest -q"""
from __future__ import annotations

import io
import json

import numpy as np
from PIL import Image


def _png(color=255) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), (color, color, color)).save(buf, "PNG")
    return buf.getvalue()


def _create(client, names):
    files = [("files", (n, _png(), "image/png")) for n in names]
    r = client.post("/api/runs", data={"name": "t", "auto_start": "false"}, files=files)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── uploads ──────────────────────────────────────────────────────────────────

def test_upload_traversal_is_contained(client, tmp_path):
    rid = _create(client, ["../../../evil.png"])
    assert not (tmp_path / "evil.png").exists()
    assert not (tmp_path.parent / "evil.png").exists()
    pages = client.get(f"/api/runs/{rid}/pages").json()
    assert [p["filename"] for p in pages] == ["001_evil.png"]


def test_upload_order_is_kept_and_duplicates_survive(client):
    rid = _create(client, ["10.png", "2.png", "cover.png", "2.png"])
    names = [p["filename"] for p in client.get(f"/api/runs/{rid}/pages").json()]
    assert names == ["001_10.png", "002_2.png", "003_cover.png", "004_2.png"]


def test_upload_rejects_non_images(client):
    files = [("files", ("x.sh", b"rm -rf /", "text/plain"))]
    r = client.post("/api/runs", data={"name": "t", "auto_start": "false"}, files=files)
    assert r.status_code == 400


def test_natural_sort_for_legacy_runs(tmp_path):
    from yomeru.core.paths import list_page_files
    for n in ["10.jpg", "2.jpg", "1.jpg"]:
        (tmp_path / n).write_bytes(b"x")
    assert [p.name for p in list_page_files(tmp_path)] == ["1.jpg", "2.jpg", "10.jpg"]


def test_file_routes_reject_traversal(client):
    rid = _create(client, ["a.png"])
    for url in (f"/api/runs/{rid}/pages/..%2Fmeta.json",
                f"/api/runs/{rid}/typeset/debug/..%2F..%2Fmeta.json"):
        assert client.get(url).status_code in (400, 404)


# ── config secrets ───────────────────────────────────────────────────────────

def test_api_keys_are_masked_and_preserved(client):
    secret = "sk-test-1234567890abcdef"
    cfg = client.post("/api/config/connections",
                      json={"name": "OpenAI", "protocol": "openai", "api_key": secret}).json()
    cid = next(c["id"] for c in cfg["connections"] if c["name"] == "OpenAI")
    body = client.get("/api/config").json()
    assert secret not in json.dumps(body)
    masked = next(c for c in body["connections"] if c["id"] == cid)["api_key"]
    assert masked.endswith("cdef")
    # UI echoes the mask back, or omits the key → stored key must survive
    client.put(f"/api/config/connections/{cid}", json={"name": "OpenAI", "api_key": masked})
    client.put(f"/api/config/connections/{cid}", json={"name": "OpenAI 2", "base_url": "http://x"})
    from yomeru.core.settings import store
    assert store.load().connection(cid).api_key == secret


def test_corrupt_config_is_backed_up_not_wiped(client, tmp_path):
    (tmp_path / "config.json").write_text("{ broken")
    client.get("/api/config")
    assert list(tmp_path.glob("config.corrupt-*.json"))


# ── refined detections ───────────────────────────────────────────────────────

def test_editing_one_page_keeps_other_pages(client, tmp_path):
    rid = _create(client, ["a.png", "b.png", "c.png"])
    out = tmp_path / "runs" / rid / "output"
    dets = [{"page_number": p, "original_w": 40, "original_h": 60,
             "regions": [{"id": 1, "x1": 0, "y1": 0, "x2": 5, "y2": 5, "label": "bubble", "score": 1}]}
            for p in (1, 2, 3)]
    (out / "page_detections.json").write_text(json.dumps(dets))
    client.put(f"/api/runs/{rid}/detections/2", json={"regions": [], "original_w": 40, "original_h": 60})
    refined = {d["page_number"]: d for d in json.loads((out / "page_detections_refined.json").read_text())}
    assert set(refined) == {1, 2, 3}
    assert refined[2]["regions"] == [] and len(refined[1]["regions"]) == 1


# ── analysis re-run ──────────────────────────────────────────────────────────

def test_scoped_reanalysis_only_touches_its_pages(tmp_path):
    from yomeru.phases.analysis import _save_analyses
    from yomeru.core.models import PageAnalysis
    out = tmp_path
    (out / "page_analyses.json").write_text(json.dumps([{"page_number": p, "dialogues": []} for p in (1, 2, 3)]))
    (out / "edits.json").write_text(json.dumps({"1": {"x": 1}, "2": {"x": 2}, "3": {"x": 3}}))
    fresh = [PageAnalysis(page_number=2)]
    _save_analyses(fresh, out, [], "auto", is_scoped=True)
    edits = json.loads((out / "edits.json").read_text())
    assert set(edits) == {"1", "3"}
    saved = {e["page_number"] for e in json.loads((out / "page_analyses.json").read_text())}
    assert saved == {1, 2, 3}


# ── manual matches ───────────────────────────────────────────────────────────

def test_override_to_orphan_region_is_used():
    from yomeru.core.matches import build_matches_from_refined
    log = {
        "s2_detection": {"regions": [
            {"id": 1, "label": "text_bubble", "score": 0.9, "bbox": [0, 0, 10, 10]},
            {"id": 7, "label": "text_bubble", "score": 0.9, "bbox": [50, 50, 90, 90]},
        ]},
        "s3_matching": {
            "matches": [{"dialogue_index": 0, "region_id": 1,
                         "region": {"x1": 0, "y1": 0, "x2": 10, "y2": 10, "label": "text_bubble"}}],
            "orphaned": [{"region_id": 7, "label": "text_bubble", "bbox": [50, 50, 90, 90]}],
        },
    }
    res = build_matches_from_refined([{"dialogue_index": 0, "region_id": 7}], log)
    assert res[0]["region_id"] == 7 and res[0]["region"]["x1"] == 50


# ── mask edits ───────────────────────────────────────────────────────────────

def test_mask_edit_is_a_delta(tmp_path):
    from yomeru.plugins.inpainting import apply_mask_delta, load_mask_edit
    auto = np.zeros((20, 20), np.uint8); auto[0:10, :] = 255
    bubble = auto.copy(); free = np.zeros_like(auto)
    edit = np.zeros((20, 20, 4), np.uint8)
    edit[0:5, 0:5] = (0, 0, 0, 255)          # remove a corner of the auto mask
    edit[15:20, 15:20] = (255, 255, 255, 255)  # add a new area
    p = tmp_path / "m.png"; Image.fromarray(edit, "RGBA").save(p)
    comb, b, f = apply_mask_delta(load_mask_edit(p, (20, 20)), auto, bubble, free)
    assert comb[7, 7] == 255          # untouched auto mask kept
    assert comb[2, 2] == 0 and b[2, 2] == 0
    assert comb[17, 17] == 255 and f[17, 17] == 255


# ── weights / CTD ────────────────────────────────────────────────────────────

def test_weights_live_in_data_models():
    from yomeru.core.paths import MODELS_DIR
    from yomeru.core.weights import WEIGHTS
    assert set(WEIGHTS) == {"lama"}
    assert all(w.path.is_relative_to(MODELS_DIR) for w in WEIGHTS.values())
