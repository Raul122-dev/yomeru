"""Image-edit rendering backend: provider chain, scanline fallback, cache, cost cap."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from yomeru.core.contracts import EditRefused, EditResult, EditUnavailable
from yomeru.lib.rendering.edit_prompt import build_prompt, rewrap
from yomeru.plugins.rendering import ImageEditOptions

GOLDEN = Path(__file__).resolve().parents[1] / "data" / "goldens" / "d4c17c9bf8f5" / "input"
RED = (255, 0, 0)


@pytest.fixture()
def run(tmp_path, monkeypatch):
    if not GOLDEN.exists():
        pytest.skip("golden run not captured (scripts/golden.py capture d4c17c9bf8f5)")
    import yomeru.core.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    shutil.copytree(GOLDEN, tmp_path / "d4c17c9bf8f5")
    r = runs.Run.load("d4c17c9bf8f5")
    from yomeru.api.routes.phases import _phase_options
    from yomeru.phases.runner import _get_phase_fn
    for phase in ("matching", "inpainting"):
        assert _get_phase_fn(phase)(r, _phase_options(r, phase)).status == "done"
    return r


class Fake:
    """Paints a red block in the middle of the crop; or raises `error`."""
    local = False

    def __init__(self, error=None, cost=0.01, shift=0, same=False, pad=0):
        self.error, self.cost, self.shift, self.same, self.pad, self.calls = error, cost, shift, same, pad, []

    def edit(self, req):
        self.calls.append(req)
        if self.error:
            raise self.error
        img = req.image.copy()
        w, h = img.size
        if self.same:    # gave the lettering back untouched (re-encoded at another size)
            return EditResult(image=img.resize((w * 2, h * 2)), model="fake", cost_usd=self.cost)
        if self.shift:   # the whole picture moved: alignment cannot save it
            img = Image.new("RGB", (w, h), (0, 0, 255))
        ImageDraw.Draw(img).rectangle((w * 0.42, h * 0.42, w * 0.58, h * 0.58), fill=RED)
        if self.pad:     # answered in another aspect ratio: content kept, margin added on one side
            framed = Image.new("RGB", (w + self.pad, h), (128, 128, 128))
            framed.paste(img, (self.pad, 0))
            return EditResult(image=framed, model="fake", cost_usd=self.cost)
        return EditResult(image=img.resize((w + 64, h)), model="fake", cost_usd=self.cost, seconds=0.1)


def providers(*fakes, tag="fake"):
    from yomeru.lib.rendering.image_edit import Provider
    return [Provider(label=f"{tag}{i}", key=f"{tag}{i}", impl=f) for i, f in enumerate(fakes)]


def render(run, opts, provs, calls=True):
    from yomeru.lib.rendering.image_edit import render_page
    from yomeru.lib.rendering.scanline_engine import build_request
    req = build_request(run, 1, edit_calls=calls)
    return render_page(req, ImageEditOptions(**opts), provs)


def scanline(run):
    from yomeru.lib.rendering.scanline_engine import build_request, layout_and_draw
    return layout_and_draw(build_request(run, 1))


def red_pixels(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    return int(((a[..., 0] > 240) & (a[..., 1] < 20) & (a[..., 2] < 20)).sum())


def test_without_providers_it_draws_exactly_like_scanline(run):
    out = render(run, {"scope": "all"}, [])
    base = scanline(run)
    assert np.array_equal(np.asarray(out.image), np.asarray(base.image))
    assert all(e.get("engine") != "ai" for e in out.events)


def test_edits_are_pasted_and_scanline_draws_the_rest(run):
    fake = Fake()
    out = render(run, {"scope": "all"}, providers(fake))
    ai = [e for e in out.events if e.get("engine") == "ai"]
    rejected = [e for e in out.events if e.get("fallback")]
    assert ai and len(fake.calls) == len(ai) + len(rejected)
    assert all(e["status"] == "ok" and e["provider"] == "fake0" and e["cost_usd"] == 0.01 for e in ai)
    assert red_pixels(out.image) > 0 and red_pixels(scanline(run).image) == 0
    # the edit prompt carries the drawn text and language
    assert all('Spanish text "' in r.prompt for r in fake.calls)
    # one event per match, as with scanline
    assert sorted(e["dialogue_index"] for e in out.events) == sorted(e["dialogue_index"] for e in scanline(run).events)


def test_refusal_falls_to_the_next_provider_and_total_failure_to_scanline(run):
    refused, ok = Fake(EditRefused("blocked")), Fake()
    out = render(run, {"scope": "all"}, providers(refused, ok))
    ai = [e for e in out.events if e.get("engine") == "ai"]
    assert ai and all(e["provider"] == "fake1" and "refused" in e["fallback"][0] for e in ai)
    n = len(refused.calls)
    render(run, {"scope": "all"}, providers(refused, ok))     # a refusal is remembered for that crop and seed
    assert len(refused.calls) == n

    out = render(run, {"scope": "all"}, providers(Fake(EditRefused("x")), Fake(EditUnavailable("down")), tag="other"))
    assert np.array_equal(np.asarray(out.image), np.asarray(scanline(run).image))
    tried = [e for e in out.events if e.get("fallback")]
    assert tried and all(e["fallback"][-1] == "all providers failed" for e in tried)


def test_an_edit_that_moved_the_art_is_rejected(run):
    out = render(run, {"scope": "all"}, providers(Fake(shift=1)))
    assert red_pixels(out.image) == 0
    assert any("drift" in f for e in out.events for f in e.get("fallback", []))


def test_lettering_given_back_unchanged_is_rejected(run):
    out = render(run, {"scope": "all"}, providers(Fake(same=True)))
    assert not any(e.get("engine") == "ai" for e in out.events)
    assert any("unchanged" in f for e in out.events for f in e.get("fallback", []))


def test_an_answer_in_another_aspect_ratio_is_registered_back():
    """Some models answer 4:3 for a 16:9 request and pad or crop instead of
    stretching: keypoints find the crop again, the margin is not pasted."""
    from yomeru.lib.rendering.image_edit import align
    rng = np.random.default_rng(0)
    tex = (rng.random((72, 128)) * 255).astype(np.uint8).repeat(8, 0).repeat(8, 1)
    ref = Image.fromarray(tex).convert("RGB").filter(ImageFilter.GaussianBlur(3))
    mask = np.zeros((576, 1024), bool)
    mask[250:320, 300:700] = True
    edited = ref.copy()
    ImageDraw.Draw(edited).rectangle((320, 260, 680, 310), fill=RED)
    framed = Image.new("RGB", (1024, 768), (128, 128, 128))
    framed.paste(edited.crop((40, 0, 1024, 576)), (0, 96))     # shifted down, left edge cut off
    al, drift = align(ref, framed, mask, (320, 260, 680, 310))
    assert drift < 3
    a = np.asarray(al)
    assert a[285, 500, :3].tolist() == list(RED) and a[285, 500, 3] == 255
    assert a[300, 10, 3] == 0                                   # the cut-off strip is marked as not answered
    # if the cut reaches the source lettering, the answer is refused
    framed = Image.new("RGB", (1024, 768), (128, 128, 128))
    framed.paste(edited.crop((400, 0, 1024, 576)), (0, 96))
    assert align(ref, framed, mask, (320, 260, 680, 310))[1] > 10


def test_cost_cap_stops_calling(run):
    fake = Fake()
    out = render(run, {"scope": "all", "max_cost_per_run_usd": 0}, providers(fake))
    assert not fake.calls and red_pixels(out.image) == 0
    assert any("cost cap" in f for e in out.events for f in e.get("fallback", []))


def test_cached_edits_are_not_paid_twice_and_a_new_seed_calls_again(run):
    from yomeru.core import artifacts
    fake = Fake()
    first = render(run, {"scope": "all"}, providers(fake))
    n = len(fake.calls)
    again = render(run, {"scope": "all"}, providers(fake))
    assert len(fake.calls) == n
    assert np.array_equal(np.asarray(first.image), np.asarray(again.image))
    assert all(e["cache_hit"] for e in again.events if e.get("engine") == "ai")
    assert artifacts.PageEditCache(run, 1).spent_usd() == pytest.approx(0.01 * n)

    i = next(e["dialogue_index"] for e in first.events if e.get("engine") == "ai")
    artifacts.page_artifact(run, 1, artifacts.RENDER_OVERRIDES).write_text(json.dumps([{"dialogue_index": i, "seed": 1}]))
    render(run, {"scope": "all"}, providers(fake))
    assert len(fake.calls) == n + 1


def test_previews_never_call_a_model(run):
    """The preview endpoints re-render stale pages when they are viewed: they
    reuse stored edits and draw the rest with scanline, never paying."""
    fake = Fake()
    out = render(run, {"scope": "all"}, providers(fake), calls=False)
    assert not fake.calls and red_pixels(out.image) == 0
    assert all("not sent" in e["fallback"][0] for e in out.events if e.get("fallback"))
    paid = render(run, {"scope": "all"}, providers(fake))
    n = len(fake.calls)
    again = render(run, {"scope": "all"}, providers(fake), calls=False)
    assert len(fake.calls) == n
    assert np.array_equal(np.asarray(paid.image), np.asarray(again.image))


def test_engine_override_beats_the_scope(run):
    from yomeru.core import artifacts
    base = scanline(run)
    i, j = [e["dialogue_index"] for e in base.events if e["status"] == "ok"][:2]
    artifacts.page_artifact(run, 1, artifacts.RENDER_OVERRIDES).write_text(json.dumps(
        [{"dialogue_index": i, "engine": "ai"}, {"dialogue_index": j, "engine": "scanline"}]))
    out = render(run, {"scope": "manual"}, providers(Fake()))
    assert [e["dialogue_index"] for e in out.events if e.get("engine") == "ai"] == [i]
    out = render(run, {"scope": "all"}, providers(Fake()))
    assert j not in [e["dialogue_index"] for e in out.events if e.get("engine") == "ai"]


def test_backend_is_selectable_and_resolves_connections(run, tmp_path, monkeypatch):
    """Through the facade, as the phase calls it: the adapter is found by name
    and gets the connection's url and key."""
    import yomeru.core.settings as settings
    from yomeru.lib.rendering import edit_providers
    from yomeru.lib.rendering.scanline_engine import render_page
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "config.json")
    settings.store.save(settings.AppConfig(connections=[settings.Connection(
        id="or", name="OpenRouter", base_url="https://example.invalid/v1", api_key="k")]))
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return Fake()

    monkeypatch.setitem(edit_providers._PROVIDERS, "_fake", factory)
    out = render_page(run, 1, backend="image_edit", edit_calls=True, backend_options={
        "scope": "all", "providers": [{"connection_id": "or", "adapter": "_fake", "model": "m"}]})
    assert seen["api_key"] == "k" and seen["model"] == "m"
    assert any(e.get("engine") == "ai" for e in out.events)
    # a deleted connection is skipped → scanline
    out = render_page(run, 1, backend="image_edit", edit_calls=True, backend_options={
        "scope": "all", "providers": [{"connection_id": "gone", "adapter": "_fake", "model": "m2"}]})
    assert not any(e.get("engine") == "ai" for e in out.events)


def test_rerender_endpoint_bumps_seeds(client, monkeypatch):
    """Re-render asks again with a new seed: listed dialogues are also marked for the model."""
    import yomeru.api.routes.phases as ph
    from yomeru.core import artifacts
    from yomeru.core.runs import Run
    from yomeru.core.settings import PipelineSettings
    run = Run.create("t", PipelineSettings())
    monkeypatch.setattr(Run, "get_phase_status", lambda self, p: "done")
    monkeypatch.setattr(ph, "_launch", lambda *a, **k: None)
    artifacts.debug_dir(run, create=True)
    artifacts.write_render_log(run, 1, {"s5_rendering": {"renders": [
        {"dialogue_index": 0, "engine": "ai"}, {"dialogue_index": 1}, {"dialogue_index": 2, "fallback": ["x"]}]}})
    assert client.post(f"/api/phases/{run.id}/rendering/rerender/1", json={}).json()["dialogues"] == [0, 2]
    r = client.post(f"/api/phases/{run.id}/rendering/rerender/1", json={"dialogues": [1, 0]})
    assert r.status_code == 200
    ov = artifacts.load_render_overrides(run, 1)
    assert ov[0]["seed"] == 2 and ov[2]["seed"] == 1 and ov[1] == {"dialogue_index": 1, "seed": 1, "engine": "ai"}


def test_prompt_rejoins_hyphenated_words_and_spells_vertical_columns():
    assert rewrap(["NORMAL-", "MENTE LA", "GENTE COMPRA"], "NORMALMENTE LA GENTE COMPRA") == \
        ["NORMALMENTE LA", "GENTE COMPRA"]
    assert rewrap(["Kanazawa-", "hakkei"], "Kanazawa-hakkei") == ["Kanazawa-", "hakkei"]   # a real hyphen stays
    p = build_prompt("ABC", "¡GY!", ["¡", "G", "Y", "!"], "Spanish")
    assert "vertical column" in p and "no word split" not in p
    p = build_prompt("a b", "uno dos tres", ["uno", "dos", "tres", "cuatro", "cinco", "seis", "siete"], "Spanish")
    assert "with these line breaks:\nuno\ndos" in p


def test_openrouter_classifies_errors(monkeypatch):
    from yomeru.core.contracts import EditRateLimited, EditRequest
    from yomeru.lib.rendering.edit_providers import openrouter as orr
    monkeypatch.setattr(orr, "RATE_LIMIT_WAIT", 0)
    p = orr.OpenRouter(base_url="", api_key="k", model="vendor/model")
    req = EditRequest(image=Image.new("RGB", (64, 32)), prompt="x", size=(64, 32))
    sent = []

    def answer(*replies):
        it = iter(replies)

        def post(path, body):
            sent.append((path, body))
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(p, "_post", post)

    ok = {"data": [{"b64_json": orr._data_url(Image.new("RGB", (80, 40))).split(",", 1)[1]}], "usage": {"cost": 0.02}}
    answer(orr._HTTPError(400, "size not supported"), ok)
    res = p.edit(req)
    assert res.image.size == (80, 40) and res.cost_usd == 0.02
    assert sent[0][1]["size"] == "64x32" and sent[1][1]["aspect_ratio"] == "auto"

    answer(orr._HTTPError(400, '{"error":{"message":"blocked this request through content moderation."}}'))
    with pytest.raises(EditRefused):
        p.edit(req)
    answer(*[orr._HTTPError(429, "slow down")] * (orr.RATE_LIMIT_RETRIES + 1))
    with pytest.raises(EditRateLimited):
        p.edit(req)
    answer(orr._HTTPError(401, "bad key"))
    with pytest.raises(EditUnavailable):
        p.edit(req)

    g = orr.OpenRouter(base_url="", api_key="k", model="google/some-image-model")
    sent.clear()
    monkeypatch.setattr(g, "_post", lambda path, body: sent.append(path) or {"choices": [{"message": {
        "images": [{"image_url": {"url": orr._data_url(Image.new("RGB", (64, 32)))}}]}}]})
    assert g.edit(req).image.size == (64, 32) and sent == ["/chat/completions"]


def test_comfyui_runs_a_workflow_template(tmp_path, monkeypatch):
    """Placeholders are filled (numbers stay numbers), the crop is uploaded,
    the first saved image is the answer; an execution error is 'unavailable'."""
    import io
    from yomeru.core.contracts import EditRequest
    from yomeru.lib.rendering.edit_providers import comfyui
    import yomeru.core.paths as paths

    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "wf.json").write_text(json.dumps({
        "_yomeru": {"description": "x"},
        "1": {"class_type": "LoadImage", "inputs": {"image": "{{image}}"}},
        "2": {"class_type": "Enc", "inputs": {"prompt": "{{prompt}}", "seed": "{{seed}}", "note": "w={{width}}"}}}))
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    assert comfyui.find_workflow("qwen-image-2.1-edit") is not None      # shipped example
    with pytest.raises(EditUnavailable):
        comfyui.ComfyUI(base_url="", api_key="", model="nope", quality="")
    c = comfyui.ComfyUI(base_url="http://x", api_key="", model="wf", quality="")
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), RED).save(buf, "PNG")
    seen, state = {}, {"error": False}

    def request(path, data=None, headers=None, timeout=60.0):
        if path == "/upload/image":
            return json.dumps({"name": "up.png", "subfolder": ""}).encode()
        if path == "/prompt":
            seen["graph"] = json.loads(data)["prompt"]
            return json.dumps({"prompt_id": "p1", "node_errors": {}}).encode()
        if path.startswith("/history/"):
            if state["error"]:
                return json.dumps({"p1": {"status": {"status_str": "error", "messages": [
                    ["execution_error", {"exception_message": "out of memory"}]]}}}).encode()
            return json.dumps({"p1": {"status": {"status_str": "success", "completed": True}, "outputs": {
                "9": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}}}).encode()
        if path.startswith("/view?"):
            return buf.getvalue()
        if path == "/free":
            seen["free"] = True
            return b"{}"
        raise AssertionError(path)

    monkeypatch.setattr(c, "_request", request)
    res = c.edit(EditRequest(image=Image.new("RGB", (64, 32)), prompt='say "hi"', size=(64, 32), seed=7))
    assert res.image.size == (40, 20) and res.cost_usd == 0.0
    g = seen["graph"]
    assert "_yomeru" not in g and g["1"]["inputs"]["image"] == "up.png"
    assert g["2"]["inputs"] == {"prompt": 'say "hi"', "seed": 7, "note": "w=64"}
    state["error"] = True
    with pytest.raises(EditUnavailable, match="out of memory"):
        c.edit(EditRequest(image=Image.new("RGB", (64, 32)), prompt="x", size=(64, 32)))
    c.release()
    assert seen["free"]


def test_local_providers_are_released_after_the_page(run):
    class Local(Fake):
        local = True
        released = 0

        def release(self):
            Local.released += 1

    render(run, {"scope": "all"}, providers(Local(), tag="local"))
    assert Local.released == 1
