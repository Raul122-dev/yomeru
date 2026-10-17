"""Phase 2A: job control, cancellation, stale marking, startup recovery, WS fan-out."""
from __future__ import annotations

import io
import threading
import time

import pytest
from PIL import Image



def _png() -> bytes:
    buf = io.BytesIO(); Image.new("RGB", (8, 8)).save(buf, "PNG"); return buf.getvalue()


def _run(client) -> str:
    r = client.post("/api/runs", data={"name": "t", "auto_start": "false"},
                    files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def slow_detection(monkeypatch):
    """Replace detection with a phase that waits on an event, page by page."""
    import yomeru.phases.runner as runner
    from yomeru.phases import PhaseResult
    gate = threading.Event()

    def fake(run, options, on_progress, page_scope):
        for p in range(1, 50):
            on_progress({"type": "page_start", "phase": "detection", "page": p})
            gate.wait(0.05)
            on_progress({"type": "page_done", "phase": "detection", "page": p})
            if gate.is_set():
                break
        return PhaseResult(phase="detection", status="done", processed_pages=1)

    real = runner._get_phase_fn
    monkeypatch.setattr(runner, "_get_phase_fn", lambda ph: fake if ph == "detection" else real(ph))
    return gate


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_second_start_is_409_not_silent(client, slow_detection):
    rid = _run(client)
    assert client.post(f"/api/phases/{rid}/detection/start", json={}).status_code == 200
    r = client.post(f"/api/phases/{rid}/detection/start", json={})
    assert r.status_code == 409 and "already running" in r.json()["detail"]
    slow_detection.set()
    assert _wait(lambda: client.get(f"/api/runs/{rid}").json()["phase_status"]["detection"] == "done")
    # free again
    assert _wait(lambda: client.get(f"/api/phases/{rid}/status").json()["running"] is None)


def test_unmet_dependencies_is_400(client):
    rid = _run(client)
    r = client.post(f"/api/phases/{rid}/matching/start", json={})
    assert r.status_code == 400 and "must be completed first" in r.json()["detail"]


def test_cancel_stops_after_current_page(client, slow_detection):
    rid = _run(client)
    client.post(f"/api/phases/{rid}/detection/start", json={})
    assert _wait(lambda: client.get(f"/api/phases/{rid}/status").json()["running"] == "detection")
    assert client.post(f"/api/phases/{rid}/cancel").status_code == 200
    assert _wait(lambda: client.get(f"/api/runs/{rid}").json()["phase_status"]["detection"] == "cancelled")
    assert client.post(f"/api/phases/{rid}/cancel").status_code == 409  # nothing running now


def test_rerun_marks_downstream_stale(tmp_path, monkeypatch):
    import yomeru.core.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    from yomeru.core.runs import Run
    run = Run("r1"); run.dir.mkdir()
    run._write_meta({"id": "r1", "phase_status": {
        "detection": "done", "analysis": "done", "matching": "done", "inpainting": "partial", "rendering": "pending"}})
    assert run.mark_downstream_stale("analysis") == ["matching", "inpainting"]
    ps = run.meta()["phase_status"]
    assert (ps["detection"], ps["analysis"], ps["matching"], ps["inpainting"], ps["rendering"]) == \
           ("done", "done", "stale", "stale", "pending")


def test_startup_recovers_hung_runs(tmp_path, monkeypatch):
    import yomeru.core.paths as paths
    import yomeru.core.runs as runs
    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    from yomeru.core.runs import Run
    from yomeru.phases.runner import recover_interrupted_runs
    run = Run("r2"); run.dir.mkdir()
    run._write_meta({"id": "r2", "status": "running", "phase_status": {"detection": "done", "analysis": "running"}})
    assert recover_interrupted_runs() == 1
    m = run.meta()
    assert m["phase_status"]["analysis"] == "failed" and m["status"] == "failed" and "Interrupted" in m["error"]
    assert m["finished_at"]


def test_run_all_stamps_finished_at(tmp_path, monkeypatch):
    import yomeru.core.runs as runs
    import yomeru.phases.runner as runner
    from yomeru.phases import PhaseResult
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    outcome = {"analysis": "done"}
    monkeypatch.setattr(runner, "run_phase", lambda run, phase, **kw: PhaseResult(
        phase=phase, status=outcome.get(phase, "done")))
    run = runs.Run("r4"); run.dir.mkdir(); run._write_meta({"id": "r4", "finished_at": None})
    runner.run_all(run)
    m = run.meta()
    assert m["status"] == "done" and m["finished_at"]
    outcome["analysis"] = "failed"
    runner.run_all(run, start_from="analysis")
    m2 = run.meta()
    assert m2["status"] == "failed" and m2["finished_at"] and m2["finished_at"] >= m["finished_at"]


def test_concurrent_meta_writes_lose_nothing(tmp_path, monkeypatch):
    import yomeru.core.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    from yomeru.core.runs import Run
    run = Run("r3"); run.dir.mkdir(); run._write_meta({"id": "r3"})
    def w(i):
        for j in range(20):
            run.update(**{f"k{i}_{j}": j})
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(run.meta()) == 1 + 8 * 20
    assert not list(run.dir.glob("*.tmp"))


def test_ws_every_client_gets_every_event(client):
    rid = _run(client)
    from yomeru.api.ws import publish
    with client.websocket_connect(f"/api/phases/{rid}/ws") as a, \
         client.websocket_connect(f"/api/phases/{rid}/ws") as b:
        assert _wait(lambda: __import__("yomeru.api.ws", fromlist=["x"]).client_count(rid) == 2)
        # Published from a non-loop thread, like a phase worker
        t = threading.Thread(target=lambda: [publish(rid, {"type": "page_done", "page": i}) for i in range(3)])
        t.start(); t.join()
        got_a = [a.receive_json()["page"] for _ in range(3)]
        got_b = [b.receive_json()["page"] for _ in range(3)]
    assert got_a == got_b == [0, 1, 2]


def test_ws_late_client_gets_replay(client):
    rid = _run(client)
    from yomeru.api.ws import publish
    publish(rid, {"type": "phase_start", "phase": "detection"})
    publish(rid, {"type": "token", "token": "x"})          # tokens are not replayed
    publish(rid, {"type": "page_done", "page": 1})
    with client.websocket_connect(f"/api/phases/{rid}/ws") as ws:
        first, second = ws.receive_json(), ws.receive_json()
    assert (first["type"], second["type"]) == ("phase_start", "page_done")
    assert first["replay"] and second["replay"]
