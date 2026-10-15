"""Translation review (glossary edits re-translate only what they touch),
run metadata edits and the ComicInfo.xml of the .cbz."""
import io
import json
import zipfile

from PIL import Image

from yomeru.lib.translation import Line, affected_keys


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, "PNG")
    return buf.getvalue()


def test_glossary_edit_touches_only_the_lines_that_use_it():
    lines = [Line("p1.d0", 1, 0, "We reach North Camp tonight."),
             Line("p1.d1", 1, 1, "Hello."),
             Line("p2.d0", 2, 0, "The camp was empty.")]
    current = {"p1.d0": "Llegamos al Campamento Norte esta noche.", "p1.d1": "Hola.",
               "p2.d0": "El campamento estaba vacío."}
    old = {"North Camp": "Campamento Norte"}
    assert affected_keys(lines, current, old, {"North Camp": "Campamento del Norte"}) == ["p1.d0"]
    assert affected_keys(lines, current, old, dict(old)) == []                       # unchanged
    assert affected_keys(lines, current, old, {**old, "camp": "base"}) == ["p1.d0", "p2.d0"]   # new term


def _run(client, **form):
    r = client.post("/api/runs", data={"name": "My chapter", "auto_start": "false", **form},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_editing_the_chapter_context_marks_reading_outdated(client):
    from yomeru.core.runs import Run
    rid = _run(client, global_context="old notes")
    run = Run.load(rid)
    for p in ("detection", "analysis", "matching"):
        run.set_phase_status(p, "done")
    m = client.patch(f"/api/runs/{rid}", json={"name": "Renamed"}).json()
    assert m["phase_status"]["analysis"] == "done"                     # name only: nothing outdated
    m = client.patch(f"/api/runs/{rid}", json={"global_context": "new notes"}).json()
    assert m["phase_status"]["analysis"] == "stale" and m["phase_status"]["matching"] == "stale"
    assert m["global_context"] == "new notes" and m["phase_status"]["detection"] == "done"


def test_cbz_carries_comic_info(client):
    from yomeru.core import artifacts
    from yomeru.core.runs import Run
    rid = _run(client, series="Some Series", chapter="12",
               settings=json.dumps({"language": {"target": "Spanish", "comic_format": "manga"}}))
    run = Run.load(rid)
    td = artifacts.typeset_dir(run)
    td.mkdir(parents=True, exist_ok=True)
    for p in run.pages_dir().iterdir():
        (td / p.name).write_bytes(p.read_bytes())
    run.analyses_file().write_text(json.dumps([{"page_number": 1, "page_summary": "Two friends meet.",
                                                "characters_seen": [{"id": "tall_girl"}], "dialogues": []}]))
    client.patch(f"/api/runs/{rid}", json={"character_names": {"tall_girl": "Ana"}})
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{rid}/export?format=cbz").content))
    xml = z.read("ComicInfo.xml").decode()
    for want in ("<Series>Some Series</Series>", "<Number>12</Number>", "<LanguageISO>es</LanguageISO>",
                 "<Manga>YesAndRightToLeft</Manga>", "<Summary>Two friends meet.</Summary>",
                 "<Characters>Ana</Characters>", "<PageCount>1</PageCount>", 'Type="FrontCover"'):
        assert want in xml, want
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{rid}/export?format=zip").content))
    assert "ComicInfo.xml" not in z.namelist()
