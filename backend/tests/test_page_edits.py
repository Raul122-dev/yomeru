"""Edit routes. Page edits (edits.json): saving one shadows the model's analysis of that
page, reverting it brings the model's reading back."""
import io
import json

from PIL import Image


def _run(client) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, "PNG")
    r = client.post("/api/runs", data={"name": "Edits", "auto_start": "false"},
                    files=[("files", ("a.png", buf.getvalue(), "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_revert_page_edits_restores_the_model_reading(client):
    from yomeru.runs.run import Run
    rid = _run(client)
    model = [{"page_number": 1, "dialogues": [{"text": "Hi", "text_translated": "Hola"}]},
             {"page_number": 2, "dialogues": [{"text": "Bye", "text_translated": "Adiós"}]}]
    Run.load(rid).analyses_file().write_text(json.dumps(model))

    edited = {"page_number": 1, "dialogues": [{"text": "Hi", "text_translated": "Buenas"}]}
    assert client.put(f"/api/runs/{rid}/edits/1", json=edited).status_code == 200
    got = client.get(f"/api/runs/{rid}/analyses").json()
    assert got[0]["dialogues"][0]["text_translated"] == "Buenas" and got[0]["_edited_at"]

    assert client.delete(f"/api/runs/{rid}/edits/1").status_code == 204
    got = client.get(f"/api/runs/{rid}/analyses").json()
    assert got[0]["dialogues"][0]["text_translated"] == "Hola" and "_edited_at" not in got[0]
    assert got[1]["dialogues"][0]["text_translated"] == "Adiós"
    assert client.delete(f"/api/runs/{rid}/edits/1").status_code == 204    # nothing left: no-op


def test_detections_save_rejects_labels_the_pipeline_ignores(client):
    rid = _run(client)
    box = {"id": 0, "score": 1.0, "x1": 1, "y1": 1, "x2": 9, "y2": 9}
    body = {"original_w": 40, "original_h": 60, "regions": [{**box, "label": "sfx"}]}
    r = client.put(f"/api/runs/{rid}/detections/1", json=body)
    assert r.status_code == 400 and "sfx" in r.text
    body["regions"] = [{**box, "label": "text_free"}]
    assert client.put(f"/api/runs/{rid}/detections/1", json=body).status_code == 200
