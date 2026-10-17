"""OpenRouter image models (MAI, Muse, GPT Image, Gemini…), one key for all.

Two endpoints: most image models take the crop as an input reference on
`/images`; Gemini image models only accept input images on
`/chat/completions` with image output enabled.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request

from PIL import Image

from yomeru.core.contracts import EditRateLimited, EditRefused, EditRequest, EditResult, EditUnavailable
from yomeru.lib.rendering.edit_providers import register_provider

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT = 300.0
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT = 20.0          # seconds between retries of a 429
CHAT_PREFIXES = ("google/",)    # image models that only edit through chat/completions
_REFUSAL = re.compile(r"moderation|safety|content (management )?policy|filtered|blocked", re.I)
_RATIOS = {"1:1": 1, "2:3": 2 / 3, "3:2": 3 / 2, "3:4": 3 / 4, "4:3": 4 / 3, "4:5": 4 / 5, "5:4": 5 / 4,
           "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9}


class _HTTPError(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f"HTTP {code}: {body[:300]}")
        self.code, self.body = code, body


def _data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _decode(url_or_b64: str) -> Image.Image:
    data = url_or_b64.split(",", 1)[1] if url_or_b64.startswith("data:") else url_or_b64
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")


@register_provider("openrouter")
class OpenRouter:
    local = False

    def __init__(self, base_url: str, api_key: str, model: str, quality: str = ""):
        if not api_key:
            raise EditUnavailable("OpenRouter connection has no API key")
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key, self.model, self.quality = api_key, model, quality

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.base_url + path, json.dumps(body).encode(), {
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise _HTTPError(e.code, e.read().decode(errors="replace")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise EditUnavailable(f"{self.model}: {e}") from None

    def _call(self, path: str, bodies: list[dict]) -> dict:
        """POST the first body; an HTTP 400 that is not a refusal tries the next
        variant (e.g. a size the model does not take); 429 waits and retries."""
        i, tries = 0, 0
        while True:
            try:
                return self._post(path, bodies[i])
            except _HTTPError as e:
                if e.code == 429 and tries < RATE_LIMIT_RETRIES:
                    tries += 1
                    time.sleep(RATE_LIMIT_WAIT)
                    continue
                if e.code == 429:
                    raise EditRateLimited(f"{self.model}: {e}") from None
                if e.code == 400 and _REFUSAL.search(e.body):
                    raise EditRefused(f"{self.model}: {e}") from None
                if e.code == 400 and i + 1 < len(bodies):
                    i += 1
                    continue
                raise EditUnavailable(f"{self.model}: {e}") from None

    def edit(self, req: EditRequest) -> EditResult:
        t0 = time.time()
        if self.model.startswith(CHAT_PREFIXES):
            img, cost = self._chat(req)
        else:
            img, cost = self._images(req)
        return EditResult(image=img, model=self.model, cost_usd=cost, seconds=round(time.time() - t0, 1))

    def _images(self, req: EditRequest) -> tuple[Image.Image, float | None]:
        body = {"model": self.model, "prompt": req.prompt, "seed": req.seed, "output_format": "png",
                "input_references": [{"type": "image_url", "image_url": {"url": _data_url(req.image)}}]}
        if self.quality:
            body["quality"] = self.quality
        w, h = req.size
        r = self._call("/images", [body | {"size": f"{w}x{h}"}, body | {"aspect_ratio": "auto"}])
        if not r.get("data"):
            raise EditUnavailable(f"{self.model}: no image in the answer: {json.dumps(r)[:200]}")
        return _decode(r["data"][0]["b64_json"]), (r.get("usage") or {}).get("cost")

    def _chat(self, req: EditRequest) -> tuple[Image.Image, float | None]:
        w, h = req.size
        ratio = min(_RATIOS, key=lambda k: abs(_RATIOS[k] - w / h))
        body = {"model": self.model, "modalities": ["image", "text"], "seed": req.seed,
                "image_config": {"aspect_ratio": ratio, "image_size": "1K"},
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": _data_url(req.image)}},
                    {"type": "text", "text": req.prompt}]}]}
        r = self._call("/chat/completions", [body])
        msg = (r.get("choices") or [{}])[0].get("message") or {}
        if not msg.get("images"):
            text = (msg.get("content") or "")[:200]
            # a chat model that answers in words instead of an image declined the edit
            raise (EditRefused if text else EditUnavailable)(f"{self.model}: no image in the answer: {text}")
        return _decode(msg["images"][0]["image_url"]["url"]), (r.get("usage") or {}).get("cost")
