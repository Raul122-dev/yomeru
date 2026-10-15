"""Rendering with image-edit models, scanline as the fallback.

Per page:
  1. scanline lays out every dialogue (its lines guide the prompt, and it is the
     fallback for whatever is not edited);
  2. the dialogues picked by `scope` / the editor's `engine` override are cropped
     from the ORIGINAL page (source lettering still there) and sent through the
     provider chain with the image-edit prompt; the first usable answer wins;
  3. the answers are aligned to the crop (models return other sizes and slightly
     reframed images) and rejected if the area around the bubble still moved or
     the lettering came back unchanged;
  4. scanline draws the remaining dialogues on the inpainted page and every edit
     is pasted inside its bubble only (models sometimes add text elsewhere).
Edits are cached by content, so re-rendering a page does not pay twice.
"""
from __future__ import annotations

import hashlib
import io
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any

import cv2
import numpy as np
from PIL import Image

from yomeru.core.contracts import EditError, EditRequest, RenderRequest, RenderResult
from yomeru.core.labels import is_free
from yomeru.core.languages import text_rules
from yomeru.lib.rendering.edit_prompt import PROMPT_VERSION, build_prompt

SHOUT_TONES = {"shouting", "screaming", "yelling", "angry", "excited"}
SEED = 1234                  # base seed; the editor's re-render adds to it
MAX_SIDE, MIN_SIDE = 1024, 512


@dataclass
class Provider:
    label: str               # adapter · model (shown in the render log)
    key: str                 # identity in the edit cache
    impl: Any                # has .edit(EditRequest) -> EditResult and .local


@dataclass
class _Job:
    match: dict
    event: dict
    box: tuple[int, int, int, int]     # crop on the page
    mask: np.ndarray                   # paste mask, crop size at page scale (bool)
    crop: Image.Image                  # sent to the model (scaled)
    text_box: tuple[int, int, int, int]  # the source lettering, in crop coordinates
    prompt: str
    seed: int


def is_hard(dialogue: dict, region: dict, event: dict) -> bool:
    """Lettering the scanline engine draws worst: SFX, free text, shouts and
    source text written in vertical columns."""
    if is_free(region.get("label")) or event.get("free") or event.get("shout"):
        return True
    if dialogue.get("bubble_type") == "sfx" or (event.get("tone") or dialogue.get("tone")) in SHOUT_TONES:
        return True
    w, h = region["x2"] - region["x1"], region["y2"] - region["y1"]
    return text_rules(dialogue.get("text") or "").vertical_native and h >= 1.8 * w


def _round32(v: float) -> int:
    return max(32, int(round(v / 32)) * 32)


def _inside(box, outer) -> float:
    ix = max(0, min(box[2], outer[2]) - max(box[0], outer[0]))
    iy = max(0, min(box[3], outer[3]) - max(box[1], outer[1]))
    return ix * iy / max(1, (box[2] - box[0]) * (box[3] - box[1]))


def paste_mask(req: RenderRequest, region: dict, contours: dict) -> np.ndarray:
    """Page-size bool mask of what an edit may replace: the bubble holding the
    text (its contour, kept off the outline) plus the text box grown a little,
    never past the bubble's box; free text only gets the grown box."""
    from yomeru.lib.rendering.scanline import extract_bubble_contour

    W, H = req.original.size
    tb = (region["x1"], region["y1"], region["x2"], region["y2"])
    mask = np.zeros((H, W), np.uint8)
    container = None
    if not is_free(region.get("label")):
        cx, cy = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2
        holding = [c for c in req.containers if tuple(c) != tb and c[0] <= cx <= c[2] and c[1] <= cy <= c[3]
                   and _inside(tb, c) >= 0.9]
        if holding:
            container = min(holding, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
    if container is not None:
        if container not in contours:
            contours[container] = extract_bubble_contour(req.original, container)
        cnt = contours[container]
        if cnt is not None:
            cv2.drawContours(mask, [cnt.astype(np.int32)], -1, 255, -1)
            mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
    gx, gy = int((tb[2] - tb[0]) * 0.15) + 4, int((tb[3] - tb[1]) * 0.15) + 4
    cv2.rectangle(mask, (max(0, tb[0] - gx), max(0, tb[1] - gy)), (min(W, tb[2] + gx), min(H, tb[3] + gy)), 255, -1)
    if container is not None:
        clip = np.zeros_like(mask)
        cv2.rectangle(clip, tuple(container[:2]), tuple(container[2:]), 255, -1)
        mask = cv2.bitwise_and(mask, clip)
    return mask > 0


def crop_for(mask: np.ndarray, page_size: tuple[int, int]) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    """Crop box around the paste mask with context for the model, and the size
    it is sent at (long side ≤ 1024, ≥ 512, multiples of 32)."""
    W, H = page_size
    ys, xs = np.nonzero(mask)
    x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    m = max(32, int(0.4 * max(x2 - x1, y2 - y1)))
    box = (max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m))
    cw, ch = box[2] - box[0], box[3] - box[1]
    s = min(4.0, MAX_SIDE / max(cw, ch))
    if max(cw, ch) * s < MIN_SIDE:
        s = MIN_SIDE / max(cw, ch)
    return box, (_round32(cw * s), _round32(ch * s))


def _ecc(r: np.ndarray, o: np.ndarray, valid: np.ndarray, keep: np.ndarray):
    def gray(a):
        return cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255, (5, 5), 0)
    try:
        _, warp = cv2.findTransformECC(gray(r), gray(o), np.eye(2, 3, dtype=np.float32), cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6),
                                       keep & valid, 5)
    except cv2.error:
        return o, valid
    h, w = r.shape[:2]
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    return (cv2.warpAffine(o, warp, (w, h), flags=flags, borderMode=cv2.BORDER_REPLICATE),
            cv2.warpAffine(valid, warp, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP))


def _features(r: np.ndarray, raw: np.ndarray, keep: np.ndarray):
    """Keypoint registration of the raw answer: models that change the aspect
    ratio crop or pad instead of stretching, which resize + ECC cannot undo."""
    orb = cv2.ORB_create(4000)
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(r, cv2.COLOR_RGB2GRAY), keep * 255)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(raw, cv2.COLOR_RGB2GRAY), None)
    if d1 is None or d2 is None:
        return None
    ms = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
    if len(ms) < 12:
        return None
    src = np.float32([k2[m.trainIdx].pt for m in ms])
    dst = np.float32([k1[m.queryIdx].pt for m in ms])
    warp, inliers = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if warp is None or int(inliers.sum()) < 12:
        return None
    h, w = r.shape[:2]
    return (cv2.warpAffine(raw, warp, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE),
            cv2.warpAffine(np.ones(raw.shape[:2], np.uint8), warp, (w, h), flags=cv2.INTER_NEAREST))


def align(ref: Image.Image, out: Image.Image, mask: np.ndarray, text_box: tuple[int, int, int, int] | None = None,
          good: float = 6.0) -> tuple[Image.Image, float]:
    """Register `out` onto `ref` using only the area away from the paste mask
    (crop size; `mask` at any scale). Returns the aligned image and the mean
    pixel difference left in that area, measured where the answer has pixels
    (an answer in another aspect ratio leaves a margin). The alpha channel
    marks those pixels; an answer leaving the source lettering (`text_box`)
    or more than 15 % of the paste area uncovered gets an infinite drift."""
    tw, th = ref.size
    r = np.asarray(ref.convert("RGB"))
    raw = np.asarray(out.convert("RGB"))
    o = np.asarray(out.convert("RGB").resize((tw, th), Image.LANCZOS))
    paste = cv2.resize(mask.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST)
    keep = (cv2.dilate(paste, np.ones((25, 25), np.uint8)) == 0).astype(np.uint8)
    if keep.sum() < 100:   # the bubble fills the crop: nothing to align on
        return Image.fromarray(o).convert("RGBA"), 0.0

    def score(a, valid):
        area = (keep & valid) > 0
        if (paste & (1 - valid)).sum() > 0.15 * paste.sum() or area.sum() < 0.3 * keep.sum():
            return float("inf")
        if text_box is not None:
            x1, y1, x2, y2 = text_box
            if valid[max(0, y1):y2, max(0, x1):x2].mean() < 0.99:
                return float("inf")
        return round(float(np.abs(r.astype(np.float32) - a).mean(-1)[area].mean()), 2)

    ones = np.ones((th, tw), np.uint8)
    cands = [(o, score(o, ones), ones)]
    al, v = _ecc(r, o, ones, keep)
    cands.append((al, score(al, v), v))
    if min(c[1] for c in cands) > good:
        f = _features(r, raw, keep)
        if f is not None:
            al, v = _ecc(r, f[0], f[1], keep)
            cands += [(f[0], score(*f), f[1]), (al, score(al, v), v)]
    best = min(cands, key=lambda t: t[1])
    return Image.fromarray(np.dstack([best[0], best[2] * 255])), best[1]


def unchanged(ref: Image.Image, edited: Image.Image, text_box: tuple[int, int, int, int], min_diff: float = 15.0) -> bool:
    """The model gave the lettering back as it was (blurred so a slight
    misalignment of the same strokes does not count as a change)."""
    x1, y1, x2, y2 = text_box
    if x2 - x1 < 4 or y2 - y1 < 4:
        return False

    def g(im):
        return cv2.GaussianBlur(np.asarray(im.convert("L"), np.float32), (9, 9), 0)[y1:y2, x1:x2]
    return float(np.abs(g(ref) - g(edited)).mean()) < min_diff


def _cache_key(job: _Job, provider: Provider) -> str:
    buf = io.BytesIO()
    job.crop.save(buf, "PNG")
    h = hashlib.sha1(buf.getvalue())
    h.update(f"\0{job.prompt}\0{PROMPT_VERSION}\0{provider.key}\0{job.seed}".encode())
    return h.hexdigest()[:20]


def _jobs(req: RenderRequest, base: RenderResult, scope: str) -> list[_Job]:
    matches = {m.get("dialogue_index"): m for m in req.matches}
    contours: dict = {}
    jobs = []
    for ev in base.events:
        i = ev.get("dialogue_index", -1)
        engine = req.overrides.get(i, {}).get("engine") or "auto"
        m = matches.get(i)
        if engine == "scanline" or m is None or not (0 <= i < len(req.dialogues)):
            continue
        if ev["status"] != "ok" and ev.get("skip_reason") != "no_fit":
            continue
        text = ev.get("text") or ""
        dlg = req.dialogues[i]
        if not text.strip():
            continue
        if engine != "ai" and (scope == "manual" or (scope == "hard" and not is_hard(dlg, m["region"], ev))):
            continue
        mask = paste_mask(req, m["region"], contours)
        box, size = crop_for(mask, req.original.size)
        crop = req.original.crop(box).resize(size, Image.LANCZOS)
        prompt = build_prompt(dlg.get("text") or "", text, ev.get("lines") or [text], req.drawn_language)
        seed = SEED + int(req.overrides.get(i, {}).get("seed") or 0)
        r = m["region"]
        sx, sy = size[0] / (box[2] - box[0]), size[1] / (box[3] - box[1])
        text_box = (int((r["x1"] - box[0]) * sx), int((r["y1"] - box[1]) * sy),
                    int((r["x2"] - box[0]) * sx), int((r["y2"] - box[1]) * sy))
        jobs.append(_Job(m, ev, box, mask[box[1]:box[3], box[0]:box[2]], crop, text_box, prompt, seed))
    return jobs


class _Budget:
    """Run-wide spend cap shared by the page's parallel calls."""

    def __init__(self, cap: float, spent: float):
        self.cap, self.spent, self.lock = cap, spent, threading.Lock()

    def allows(self) -> bool:
        with self.lock:
            return self.spent < self.cap

    def add(self, cost: float | None) -> None:
        with self.lock:
            self.spent += cost or 0.0


def _edit(job: _Job, providers: list[Provider], cache, budget: _Budget, max_drift: float) -> tuple[Image.Image | None, dict]:
    """Walk the chain; returns (aligned crop or None, record for the render log)."""
    from yomeru.core.gpu import gpu_lock

    rec: dict = {"fallback": []}
    for p in providers:
        key = _cache_key(job, p)
        hit = cache.get(key) if cache is not None else None
        if hit is not None:
            img, meta = hit
            if meta.get("ok"):
                return img, rec | {k: meta.get(k) for k in ("provider", "model", "drift")} | {"cache_hit": True, "cost_usd": 0.0}
            rec["fallback"].append(f"{p.label}: {meta.get('reason', 'rejected')}")
            continue
        if not budget.allows():
            rec["fallback"].append("cost cap reached")
            return None, rec
        try:
            with (gpu_lock() if getattr(p.impl, "local", False) else nullcontext()):
                res = p.impl.edit(EditRequest(image=job.crop, prompt=job.prompt, size=job.crop.size, seed=job.seed))
        except EditError as e:
            rec["fallback"].append(f"{p.label}: {type(e).__name__.removeprefix('Edit').lower()}: {str(e)[:160]}")
            continue
        except Exception as e:   # a buggy adapter must cost one dialogue, not the page
            rec["fallback"].append(f"{p.label}: error: {type(e).__name__}: {str(e)[:160]}")
            continue
        budget.add(res.cost_usd)
        aligned, drift = align(job.crop, res.image, job.mask, job.text_box)
        reason = ("answer does not cover the bubble" if drift == float("inf")
                  else f"image moved (drift {drift} > {max_drift})" if drift > max_drift
                  else "lettering left unchanged" if unchanged(job.crop, aligned, job.text_box) else "")
        drift = None if drift == float("inf") else drift
        ok = not reason
        meta = {"ok": ok, "provider": p.label, "model": res.model, "cost_usd": res.cost_usd, "seconds": res.seconds,
                "drift": drift, "seed": job.seed, "dialogue_index": job.event.get("dialogue_index"),
                "answer_size": list(res.image.size)}
        if reason:
            meta["reason"] = reason
        if cache is not None:
            cache.put(key, aligned, meta)
        if ok:
            return aligned, rec | {"provider": p.label, "model": res.model, "drift": drift, "cache_hit": False,
                                   "cost_usd": res.cost_usd, "seconds": res.seconds}
        rec["fallback"].append(f"{p.label}: {meta['reason']}")
    if providers:
        rec["fallback"].append("all providers failed")
    return None, rec


def _paste(page: np.ndarray, job: _Job, edited: Image.Image) -> None:
    x1, y1, x2, y2 = job.box
    size = (x2 - x1, y2 - y1)
    patch = np.asarray(edited.convert("RGB").resize(size, Image.LANCZOS), np.float32)
    mask = job.mask
    if edited.mode == "RGBA":   # only where the model's answer has pixels
        mask = mask & (np.asarray(edited.getchannel("A").resize(size, Image.NEAREST)) > 127)
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (5, 5), 1.2)[..., None]
    region = page[y1:y2, x1:x2]
    page[y1:y2, x1:x2] = region * (1 - alpha) + patch * alpha


def render_page(req: RenderRequest, options, providers: list[Provider]) -> RenderResult:
    from yomeru.lib.rendering.scanline_engine import layout_and_draw

    base = layout_and_draw(req)
    jobs = _jobs(req, base, options.scope) if req.use_translation else []
    if not jobs:
        return base
    if not providers:
        for j in jobs:
            j.event["fallback"] = ["no image-edit provider configured"]
        return base

    budget = _Budget(options.max_cost_per_run_usd, req.edit_cache.spent_usd() if req.edit_cache else 0.0)
    with ThreadPoolExecutor(max(1, min(options.max_parallel, len(jobs)))) as ex:
        results = list(ex.map(lambda j: _edit(j, providers, req.edit_cache, budget, options.max_drift), jobs))
    for p in providers:   # local servers give the GPU back to the rest of the pipeline
        if getattr(p.impl, "local", False) and hasattr(p.impl, "release"):
            p.impl.release()

    done = {j.event["dialogue_index"]: (j, img, rec) for j, (img, rec) in zip(jobs, results) if img is not None}
    for j, (img, rec) in zip(jobs, results):
        if img is None:
            j.event["fallback"] = rec["fallback"]
            print(f"  [image-edit] dialogue {j.event['dialogue_index']} → scanline: {'; '.join(rec['fallback'])}",
                  file=sys.stderr)
    if not done:
        return base

    final = layout_and_draw(replace(req, skipped=set(req.skipped) | set(done)))
    def with_edits(img: Image.Image) -> Image.Image:
        page = np.asarray(img.convert("RGB"), np.float32).copy()
        for j, edited, _ in done.values():
            _paste(page, j, edited)
        return Image.fromarray(page.clip(0, 255).astype(np.uint8))

    events = []
    failed = {j.event["dialogue_index"]: rec["fallback"] for j, (img, rec) in zip(jobs, results) if img is None}
    for ev in final.events:
        i = ev.get("dialogue_index")
        if i in done:
            j, _, rec = done[i]
            ev = {**j.event, "status": "ok", "engine": "ai", **{k: v for k, v in rec.items() if v or k == "cache_hit"}}
        elif i in failed:
            ev = {**ev, "fallback": failed[i]}
        events.append(ev)
    return RenderResult(image=with_edits(final.image), events=events, layouts=final.layouts + len(done),
                        preview=with_edits(final.preview) if final.preview is not None else None)
