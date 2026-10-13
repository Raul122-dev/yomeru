"""Separate translation (Read & translate in two steps)."""
import json

from tests.test_phase1_critical import client  # noqa: F401  (fixture)
from yomeru.lib.translation import ChapterInput, collect_lines, translate_chapter

PAGES = [
    {"page_number": 1, "scene": {"location": "street", "mood": "tense", "narrative_beat": "debt"},
     "characters_seen": [{"id": "denji", "description": "boy", "speech_register": "rough, casual"}],
     "dialogues": [
         {"text": "300 GRAND.", "speaker_id": "denji", "addressee": "pochita", "tone": "flat",
          "intent": "listing what he sold", "bubble_type": "speech", "text_translated": "300 MIL."},
         {"text": "LOGO", "skip": True, "bubble_type": "narration"},
         {"text": "", "bubble_type": "speech"},
     ]},
    {"page_number": 2, "scene": {}, "characters_seen": [],
     "dialogues": [{"text": "YOU KNOW THE DRILL!", "speaker_id": "denji", "bubble_type": "speech"}]},
]


def _fake(calls, drop_first=False):
    def ask(system, user, schema):
        calls.append((system, user, schema))
        if "synopsis" in schema["properties"]:
            return json.dumps({"synopsis": "s", "voices": [{"id": "denji", "voice": "rough"}],
                               "glossary": [{"source": "grand", "target": "mil"}], "honorifics": "drop", "notes": ""})
        keys = schema["properties"]["translations"]["items"]["properties"]["key"]["enum"]
        if drop_first and len(calls) == 2:
            keys = keys[1:]   # the model forgets a line → retried alone
        return json.dumps({"translations": [{"key": k, "text": f"T[{k}]"} for k in keys],
                           "review": [{"key": keys[0], "reason": "ambiguous"}]})
    return ask


def test_lines_skip_empty_and_skipped_and_carry_context():
    lines = collect_lines(PAGES)
    assert [ln.key for ln in lines] == ["p1.d0", "p2.d0"]
    assert lines[0].addressee == "pochita" and lines[0].intent == "listing what he sold"


def test_two_passes_with_style_guide_context_and_retry_of_dropped_keys():
    calls = []
    res = translate_chapter(ChapterInput("English", "Spanish", PAGES), _fake(calls, drop_first=True))
    assert res.lines == {"p1.d0": "T[p1.d0]", "p2.d0": "T[p2.d0]"}
    assert res.style["glossary"][0]["target"] == "mil"
    style_user, block_user = calls[0][1], calls[1][1]
    # the style guide sees the whole chapter + character register
    assert "300 GRAND." in style_user and "YOU KNOW THE DRILL!" in style_user and "rough, casual" in style_user
    # each line carries who → whom, tone, intent and the guide
    assert "denji → pochita" in block_user and "listing what he sold" in block_user and "grand → mil" in block_user
    # the dropped line was asked again, alone
    assert len(calls) == 3 and calls[2][2]["properties"]["translations"]["items"]["properties"]["key"]["enum"] == ["p1.d0"]
    assert res.review


def test_final_text_priority(tmp_path, monkeypatch):
    """user edit > separate translation > reading's text_translated."""
    from yomeru.core import artifacts
    from yomeru.core.annotations import AnnotationStore

    class R:
        def output_dir(self):
            return tmp_path

        def active_analyses_file(self):
            return tmp_path / "page_analyses.json"
    run = R()
    (tmp_path / "page_analyses.json").write_text(json.dumps(PAGES))
    assert artifacts.load_analyses(run)[0]["dialogues"][0]["text_translated"] == "300 MIL."
    (tmp_path / artifacts.TRANSLATIONS).write_text(json.dumps({"lines": {"p1.d0": "TRESCIENTOS MIL.", "p2.d0": "¡YA SABES!"}}))
    a = artifacts.load_analyses(run)
    assert a[0]["dialogues"][0]["text_translated"] == "TRESCIENTOS MIL."
    assert a[1]["dialogues"][0]["text_translated"] == "¡YA SABES!"
    edited = json.loads(json.dumps(a[1]))
    edited["dialogues"][0]["text_translated"] = "MIO"
    AnnotationStore(tmp_path).save_edit(2, edited)
    assert artifacts.load_analyses(run)[1]["dialogues"][0]["text_translated"] == "MIO"


def test_reading_drops_entries_without_text():
    from types import SimpleNamespace
    from yomeru.core.analyzer import parse_reply
    raw = json.dumps({"panel_count": 1, "dialogues": [
        {"region_id": 1, "text": "HI", "bubble_type": "speech"},
        {"region_id": 2, "text": "  ", "bubble_type": "speech"}],
        "characters_seen": [], "scene": {}, "page_summary": ""})
    a = parse_reply(raw, SimpleNamespace(page_number=1, regions=[], image=None), "fake")
    assert [d.text for d in a.dialogues] == ["HI"]


def test_read_only_request_uses_reading_prompt_without_translation():
    from PIL import Image
    from yomeru.core.analyzer import prepare
    from yomeru.core.contracts import AnalysisRequest
    from yomeru.plugins.analysis import _reply_schema
    p = prepare(AnalysisRequest(image=Image.new("RGB", (64, 64)), page_number=1, regions=[],
                                target_language="Spanish", read_only=True))
    assert "Do not translate" in p.system and "Do not translate" in p.user_text
    assert "text_translated" not in p.user_text
    d = _reply_schema(True)["properties"]["dialogues"]["items"]
    assert "text_translated" not in d["properties"] and {"addressee", "intent"} <= set(d["required"])
    full = prepare(AnalysisRequest(image=Image.new("RGB", (64, 64)), page_number=1, regions=[],
                                   target_language="Spanish"))
    assert "text_translated" in full.user_text


def test_run_gate_for_separate_translation(client):
    from tests.test_settings import _png
    files = [("files", ("a.png", _png(), "image/png"))]
    on = {"analysis": {"separate_translation": {"enabled": True}}, "translation_model": {"model": ""}}
    r = client.post("/api/runs", data={"name": "x", "auto_start": "false", "settings": json.dumps(on)}, files=files)
    assert r.status_code == 400 and "separate translation" in r.json()["detail"]
    on["analysis"]["separate_translation"]["local"] = True
    r = client.post("/api/runs", data={"name": "x", "auto_start": "false", "settings": json.dumps(on)},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 201, r.text
