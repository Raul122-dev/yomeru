"""ComfyUI: any image-edit model the user has a workflow for (e.g. Qwen-Image).

yomeru knows nothing about the model: the connection points at a ComfyUI
server and the "model" is a workflow in API format whose string values may be
placeholders — "{{image}}" (uploaded crop), "{{prompt}}", "{{seed}}",
"{{width}}", "{{height}}". The first image any output node saves is the answer.

Workflows are looked up as: a path, `<data>/workflows/<name>.json`, then the
examples shipped in `assets/workflows/`.
"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

from yomeru.core.contracts import EditRequest, EditResult, EditUnavailable
from yomeru.core.paths import PACKAGE_DIR
from yomeru.lib.rendering.edit_providers import register_provider

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
EXAMPLES = PACKAGE_DIR / "assets" / "workflows"
TIMEOUT = 900.0       # first use loads the model (minutes on a cold disk)
POLL = 1.0


def find_workflow(name: str) -> Path | None:
    from yomeru.core.paths import DATA_DIR
    candidates = [Path(name).expanduser()] if name.endswith(".json") else []
    candidates += [DATA_DIR / "workflows" / f"{name}.json", EXAMPLES / f"{name}.json"]
    return next((p for p in candidates if p.is_file()), None)


def fill(graph: dict, values: dict) -> dict:
    """Replace placeholder strings; a value that is the whole placeholder keeps
    its type (seed and sizes stay numbers)."""
    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            for k, val in values.items():
                if v == "{{" + k + "}}":
                    return val
            for k, val in values.items():
                v = v.replace("{{" + k + "}}", str(val))
        return v
    return {k: walk(n) for k, n in graph.items() if not k.startswith("_")}


@register_provider("comfyui")
class ComfyUI:
    local = True     # the server shares this machine's GPU

    def __init__(self, base_url: str, api_key: str, model: str, quality: str = ""):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key, self.model = api_key, model
        path = find_workflow(model)
        if path is None:
            raise EditUnavailable(f"ComfyUI workflow {model!r} not found")
        try:
            self.graph = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise EditUnavailable(f"ComfyUI workflow {path.name}: {e}") from None

    def _request(self, path: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 60.0):
        h = dict(headers or {})
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise EditUnavailable(f"ComfyUI {path}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise EditUnavailable(f"ComfyUI at {self.base_url} not reachable: {e}") from None

    def _json(self, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        return json.loads(self._request(path, data, {"Content-Type": "application/json"}))

    def _upload(self, img: Image.Image) -> str:
        name = f"yomeru_{uuid.uuid4().hex[:12]}.png"
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
                f"Content-Type: image/png\r\n\r\n").encode() + buf.getvalue() + \
               (f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
                f"\r\n--{boundary}--\r\n").encode()
        r = json.loads(self._request("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
        return f"{r['subfolder']}/{r['name']}" if r.get("subfolder") else r["name"]

    def edit(self, req: EditRequest) -> EditResult:
        t0 = time.time()
        image = self._upload(req.image)
        w, h = req.size
        graph = fill(self.graph, {"image": image, "prompt": req.prompt, "seed": req.seed, "width": w, "height": h})
        r = self._json("/prompt", {"prompt": graph})
        if r.get("node_errors"):
            raise EditUnavailable(f"ComfyUI rejected the workflow: {json.dumps(r['node_errors'])[:300]}")
        pid = r["prompt_id"]
        while True:
            hist = self._json(f"/history/{pid}").get(pid)
            status = (hist or {}).get("status") or {}
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                raise EditUnavailable(f"ComfyUI: {(msgs[0][1].get('exception_message') if msgs else 'execution error')}"[:300])
            if hist and status.get("completed"):
                break
            if time.time() - t0 > TIMEOUT:
                raise EditUnavailable(f"ComfyUI: no answer after {int(TIMEOUT)} s")
            time.sleep(POLL)
        images = [i for out in hist.get("outputs", {}).values() for i in out.get("images", []) if i.get("type") == "output"]
        if not images:
            raise EditUnavailable("ComfyUI: the workflow saved no image")
        q = urllib.parse.urlencode({"filename": images[0]["filename"], "subfolder": images[0].get("subfolder", ""),
                                    "type": "output"})
        img = Image.open(io.BytesIO(self._request(f"/view?{q}"))).convert("RGB")
        return EditResult(image=img, model=self.model, cost_usd=0.0, seconds=round(time.time() - t0, 1))

    def release(self) -> None:
        """Unload the model and free VRAM once the page is done."""
        try:
            self._request("/free", json.dumps({"unload_models": True, "free_memory": True}).encode(),
                          {"Content-Type": "application/json"})
        except EditUnavailable:
            pass
