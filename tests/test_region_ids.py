"""Region-id integrity between detection → analysis → matching (B-ARQ-2, B-ARQ-3)."""
from __future__ import annotations

import io
import json

from PIL import Image, ImageDraw


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
    from yomeru.plugins import get_backend
    _, backend = get_backend("matching", "cascade")
    real_match = backend.matcher.match

    def match(**kw):
        seen.append([(rg.x1, rg.y1, rg.x2, rg.y2) for rg in kw["regions"]])
        return real_match(**kw)

    monkeypatch.setattr(backend.matcher, "match", match)
    # No OCR models in tests
    monkeypatch.setattr("yomeru.lib.matching.hungarian.ocr_region", lambda *a, **k: "")
    monkeypatch.setattr("yomeru.lib.matching.ocr.ocr_region", lambda *a, **k: "")

    matching.run(run, options={})

    assert seen, "fallback matcher was not called"
    assert (10, 10, 140, 120) not in seen[0], "claimed region offered to the fallback"
    log = json.loads((out / "typeset" / "debug" / "p01_render_log.json").read_text())
    rids = [m["region_id"] for m in log["s3_matching"]["matches"]]
    assert len(rids) == len(set(rids)), f"a region was assigned twice: {rids}"



def test_near_and_reading_direction():
    from yomeru.lib.detection import TextRegion
    from yomeru.phases.matching import _near, _right_to_left
    r = TextRegion(100, 100, 200, 160, "text_free")
    assert _near(r, (110, 110, 190, 150), 1000, 1400)          # overlap
    assert _near(r, (230, 100, 300, 160), 1000, 1400)          # close by
    assert not _near(r, (600, 1000, 900, 1300), 1000, 1400)    # far away
    assert not _near(r, (0, 0, 0, 0), 1000, 1400)              # no bbox
    assert _right_to_left("manga", "English") is True
    assert _right_to_left("manhwa", "auto") is False            # was RTL (source 'auto')
    assert _right_to_left("auto", "Japanese") is True


def test_reading_order_fallback_does_not_grab_far_regions(client, monkeypatch):
    """A dialogue with no region_id whose bbox is far from every free region
    stays unmatched (and its region is not erased), instead of taking the
    next region in reading order."""
    from yomeru.core.runs import Run
    from yomeru.phases import matching

    buf = io.BytesIO()
    Image.new("RGB", (1000, 1400), "white").save(buf, "PNG")
    r = client.post("/api/runs", data={"name": "t", "auto_start": "false"},
                    files=[("files", ("p.png", buf.getvalue(), "image/png"))])
    run = Run.load(r.json()["id"])
    assert run is not None
    out = run.output_dir(); out.mkdir(parents=True, exist_ok=True)
    (out / "page_detections.json").write_text(json.dumps([{
        "page_number": 1, "original_w": 1000, "original_h": 1400,
        "regions": [{"id": 1, "x1": 50, "y1": 50, "x2": 200, "y2": 100, "label": "text_free", "score": 0.9}],
    }]))
    (out / "page_analyses.json").write_text(json.dumps([{
        "page_number": 1, "analysis_image_w": 1000, "analysis_image_h": 1400, "source_language": "English",
        "dialogues": [{"text": "BOOM", "text_translated": "BUM", "region_id": None, "bbox": [600, 1000, 900, 1300]}],
    }]))
    monkeypatch.setattr("yomeru.lib.matching.hungarian.ocr_region", lambda *a, **k: "")
    monkeypatch.setattr("yomeru.lib.matching.ocr.ocr_region", lambda *a, **k: "")
    matching.run(run, options={})
    log = json.loads((out / "typeset" / "debug" / "p01_render_log.json").read_text())
    assert log["s3_matching"]["matches"] == []
    assert [o["region_id"] for o in log["s3_matching"]["orphaned"]] == [1]



def test_region_id_pointing_at_a_bubble_maps_to_its_text_region():
    """The VLM sometimes answers with the container's id. The dialogue must
    land on the text_bubble inside, never on the container (overlapping text)."""
    from yomeru.phases.matching import _text_region_of
    dets = {
        9: {"id": 9, "label": "bubble", "x1": 612, "y1": 579, "x2": 756, "y2": 760},
        17: {"id": 17, "label": "text_bubble", "x1": 612, "y1": 623, "x2": 742, "y2": 720},
        3: {"id": 3, "label": "text_bubble", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
        5: {"id": 5, "label": "bubble", "x1": 900, "y1": 900, "x2": 950, "y2": 950},
    }
    assert _text_region_of(9, dets) == 17
    assert _text_region_of(3, dets) == 3
    assert _text_region_of(5, dets) is None   # empty container → fallback path



def test_ocr_corrects_region_ids_shifted_along_a_chain(monkeypatch):
    """The VLM can point each dialogue at the NEXT one's bubble (qwen3.5:9b on
    Chainsaw Man p1; Gemini on Bocchi p2: the drummer's text was drawn in the
    bassist's box and the drummer's box kept its English). OCR of the claimed
    regions contradicts the ids → dialogues are reassigned by text. When OCR
    agrees, nothing moves."""
    from PIL import Image
    from yomeru.core.contracts import MatchRequest
    from yomeru.lib.matching import build_matcher
    from yomeru.lib.matching.cascade import match_page

    regions = {
        1: {"id": 1, "x1": 0, "y1": 0, "x2": 100, "y2": 50, "label": "text_bubble", "score": 1},
        2: {"id": 2, "x1": 0, "y1": 100, "x2": 100, "y2": 150, "label": "text_bubble", "score": 1},
        3: {"id": 3, "x1": 0, "y1": 200, "x2": 100, "y2": 250, "label": "text_bubble", "score": 1},
    }
    printed = {(0, 0, 100, 50): "I SOLD ONE OF MY BALLS TOO.",
               (0, 100, 100, 150): "HOW MUCH WAS THAT AGAIN?",
               (0, 200, 100, 250): "100 GRAND WASN'T IT?"}
    monkeypatch.setattr("yomeru.lib.matching.ocr.ocr_region", lambda img, bb, lang="auto": printed[tuple(bb)])
    monkeypatch.setattr("yomeru.lib.matching.hungarian.ocr_region", lambda img, bb, *a, **k: printed[tuple(bb)])

    def run(ids):
        dlgs = [{"text": t, "region_id": r} for t, r in zip(
            ["I SOLD ONE OF MY BALLS TOO.", "HOW MUCH WAS THAT AGAIN?", "100 GRAND WASN'T IT?"], ids)]
        res = match_page(MatchRequest(image=Image.new("RGB", (100, 300)), detections=regions, dialogues=dlgs,
                                      source_language="English", comic_format="manga"),
                         build_matcher("hungarian"), 0.4, 0.4, 0.05)
        return {i: (m.region.y1 // 100) + 1 for i, m in res.matches.items()}, [o["id"] for o in res.orphaned]

    # shifted chain: D0 has no claim of its own region, D1→R1, D2→R2 ; R3 left orphaned
    got, orphans = run([None, 1, 2])
    assert got == {0: 1, 1: 2, 2: 3} and orphans == []
    # VLM right → untouched
    assert run([1, 2, 3]) == ({0: 1, 1: 2, 2: 3}, [])



def test_locate_finds_text_the_detector_missed(monkeypatch):
    """Set de pruebas: 'SFX: GRR', 'SFX: SKID', 'Yay!' had no detected region,
    so they were neither erased nor translated. Page OCR finds the words
    outside every detected text region -> a new text_free region."""
    from PIL import Image
    import yomeru.lib.matching.ocr as ocr
    from yomeru.lib.matching.cascade import _locate_undetected
    monkeypatch.setattr(ocr, "ocr_lines", lambda img, *a: [
        ((225, 421, 289, 437), "SFx: GRR"),          # OCR noise: case, prefix
        ((100, 100, 160, 120), "HELLO"),             # inside a detected region -> not free
        ((663, 671, 693, 685), "Skid")])
    dets = {1: {"id": 1, "x1": 90, "y1": 90, "x2": 200, "y2": 130, "label": "text_bubble"}}
    dialogues = [{"text": "HELLO", "region_id": 1}, {"text": "SFX: GRR"}, {"text": "SFX: SKID"},
                 {"text": "SFX: WHOOSH"}, {"text": "LOGO", "skip": True}]
    got = dict(_locate_undetected({}, dialogues, dets, Image.new("RGB", (697, 1100)), "English", 0, 0))
    assert set(got) == {1, 2} and got[1]["label"] == "text_free" and got[1]["id"] == 2 and got[2]["id"] == 3
    assert got[1]["x1"] == 222 and got[2]["y2"] == 688
    # Japanese/Korean sources: no box OCR -> nothing invented
    assert _locate_undetected({}, dialogues, dets, Image.new("RGB", (697, 1100)), "Japanese", 0, 0) == []


def test_free_text_expands_evenly_so_it_stays_in_place():
    """'Plas' (bocchi ch10 p5) slid into the white page margin: only the margin
    side was uniform, so the box grew one way and the text moved off its spot."""
    import numpy as np
    from PIL import Image
    from yomeru.lib.rendering.scanline_engine import _expand_free_text_bbox
    arr = np.full((400, 400, 3), 255, np.uint8)
    rng = np.random.default_rng(0)
    arr[:, 200:] = rng.integers(0, 255, (400, 200, 3))     # busy art on the right
    x1, y1, x2, y2 = _expand_free_text_bbox(Image.fromarray(arr), (150, 100, 200, 130))
    assert (x1 + x2) / 2 == 175
