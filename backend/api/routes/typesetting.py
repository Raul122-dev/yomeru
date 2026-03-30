from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.runs import Run
from api.state import queues as _queues

router = APIRouter(prefix="/runs", tags=["typesetting"])


class TypesetRequest(BaseModel):
    use_translation: bool = True
    skip_sfx: bool = True
    skip_narration: bool = False
    max_font_size: int = 30
    # stage backends
    detector_backend: str = "auto"
    detector_threshold: float = 0.5
    matcher_backend: str = "hungarian"
    inpainter_backend: str = "auto"
    renderer_backend: str = "pil"
    # matching weights
    ocr_weight: float = 0.4
    spatial_weight: float = 0.4
    position_weight: float = 0.2
    match_min_score: float = 0.05
    save_debug: bool = True


@router.get("/typeset/capabilities")
def typeset_capabilities():
    """Return what's available based on setup_typesetting.py status file."""
    status_file = Path(__file__).parent.parent.parent / "typesetting_status.json"
    if not status_file.exists():
        return {
            "ready": False,
            "message": "Run python backend/setup_typesetting.py first",
            "detectors": [],
            "device": "cpu",
        }
    status = json.loads(status_file.read_text())
    from core.typesetting.stages.detection.ctd import CTDDetector
    from core.typesetting.stages.inpainting import lama_available
    # Always show both detectors; mark CTD as unavailable if model not downloaded
    detectors = [
        {
            "key": "ogkalu",
            "label": "ogkalu RT-DETR",
            "available": True,
            "note": "HuggingFace model, downloads on first use. Best general-purpose.",
        },
        {
            "key": "ctd",
            "label": "CTD (Comic Text Detector)",
            "available": CTDDetector.is_available(),
            "note": "Pixel-level masks for better inpainting. Requires manual download of comictextdetector.pt.",
            "download_url": "https://github.com/zyddnys/manga-image-translator/releases/tag/beta-0.2.1",
        },
    ]
    return {
        "ready":      status.get("torch", False),
        "device":     status.get("device", "cpu"),
        "detectors":  detectors,
        "inpainter":  "lama" if lama_available() else "opencv",
        "lama_ready": lama_available(),
        "message":    None if status.get("torch", False) else "Run python backend/setup_typesetting.py first",
    }


@router.post("/{run_id}/typeset", status_code=202)
async def start_typeset(run_id: str, body: TypesetRequest = TypesetRequest()):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    if run.meta()["status"] not in ("done", "failed"):
        raise HTTPException(400, "run must be completed before typesetting")
    if not (run.output_dir() / "page_analyses.json").exists():
        raise HTTPException(400, "no analyses found — run the pipeline first")

    q: asyncio.Queue = asyncio.Queue()
    _queues[run_id] = q

    async def _task():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _typeset_sync, run_id, body, q, loop)
        await q.put(None)
        _queues.pop(run_id, None)

    asyncio.create_task(_task())
    return {"status": "started", "run_id": run_id}


@router.get("/{run_id}/typeset/status")
def typeset_status(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    typeset_dir = run.output_dir() / "typeset"
    if not typeset_dir.exists():
        return {"status": "not_started", "pages": [], "active": False}
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    pages = sorted(
        p.name for p in typeset_dir.iterdir()
        if p.suffix.lower() in exts and p.is_file()
    )
    return {"status": "done" if pages else "not_started", "pages": pages, "active": run_id in _queues}


@router.get("/{run_id}/typeset/debug")
def list_debug_images(run_id: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    debug_dir = run.output_dir() / "typeset" / "debug"
    if not debug_dir.exists():
        return {"images": []}
    # Group by page number: p01_s2_detection, p01_s3_matching, p01_s4_inpainted
    images = sorted(p.name for p in debug_dir.iterdir() if p.suffix.lower() in {".jpg", ".png"})
    return {"images": images}


@router.get("/{run_id}/typeset/debug/{filename}")
def get_debug_image(run_id: str, filename: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    path = run.output_dir() / "typeset" / "debug" / filename
    if not path.exists(): raise HTTPException(404, "debug image not found")
    return FileResponse(path)


@router.get("/{run_id}/typeset/render-log/{page_num}")
def get_render_log(run_id: str, page_num: int):
    """Return the render log for a specific page."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    log_path = run.output_dir() / "typeset" / "debug" / f"p{page_num:02d}_render_log.json"
    if not log_path.exists():
        return {"page_number": page_num, "renders": [], "matched": 0, "unmatched": 0}
    import json
    return json.loads(log_path.read_text())



# ── font management ───────────────────────────────────────────────────────────

@router.get("/typeset/fonts")
def list_fonts():
    """List all custom fonts installed in assets/fonts/."""
    from pathlib import Path
    fonts_dir = Path(__file__).parent.parent.parent / "assets" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    fonts = [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in sorted(fonts_dir.iterdir())
        if f.suffix.lower() in (".ttf", ".otf", ".ttc", ".woff", ".woff2")
    ]
    return {"fonts": fonts}


@router.post("/typeset/fonts/upload")
async def upload_font(file: UploadFile = FastAPIFile(...)):
    """Upload a font file to assets/fonts/."""
    from pathlib import Path
    if not file.filename:
        raise HTTPException(400, "no filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".ttf", ".otf", ".ttc"):
        raise HTTPException(400, f"unsupported font format '{suffix}' — use .ttf, .otf or .ttc")
    fonts_dir = Path(__file__).parent.parent.parent / "assets" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    dest = fonts_dir / Path(file.filename).name
    content = await file.read()
    dest.write_bytes(content)
    # clear font cache so next render picks up the new font
    try:
        from core.typesetting.stages.rendering.pil import _font_cache
        _font_cache.clear()
    except Exception:
        pass
    return {"name": dest.name, "size_kb": round(len(content) / 1024, 1)}


@router.delete("/typeset/fonts/{filename}")
def delete_font(filename: str):
    """Delete a font from assets/fonts/."""
    from pathlib import Path
    fonts_dir = Path(__file__).parent.parent.parent / "assets" / "fonts"
    dest = fonts_dir / filename
    if not dest.exists() or dest.parent != fonts_dir:
        raise HTTPException(404, "font not found")
    dest.unlink()
    try:
        from core.typesetting.stages.rendering.pil import _font_cache
        _font_cache.clear()
    except Exception:
        pass
    return {"deleted": filename}

@router.get("/{run_id}/typeset/pages/{filename}")
def get_typeset_page(run_id: str, filename: str):
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    path = run.output_dir() / "typeset" / filename
    if not path.exists(): raise HTTPException(404, "typeset image not found")
    return FileResponse(path)


def _typeset_sync(
    run_id: str,
    body: TypesetRequest,
    queue: asyncio.Queue,
    loop: "asyncio.AbstractEventLoop",
) -> None:
    from core.typesetting import TypesetOptions, typeset_run

    run = Run.load(run_id)
    if not run: return

    def emit(ev: dict):
        try: loop.call_soon_threadsafe(queue.put_nowait, ev)
        except Exception as e: print(f"  emit error: {e}", file=sys.stderr)

    opts = TypesetOptions(
        use_translation=body.use_translation,
        skip_sfx=body.skip_sfx,
        skip_narration=body.skip_narration,
        max_font_size=body.max_font_size,
        detector_backend=body.detector_backend,
        detector_threshold=body.detector_threshold,
        matcher_backend=body.matcher_backend,
        inpainter_backend=body.inpainter_backend,
        renderer_backend=body.renderer_backend,
        ocr_weight=body.ocr_weight,
        spatial_weight=body.spatial_weight,
        position_weight=body.position_weight,
        match_min_score=body.match_min_score,
        save_debug=body.save_debug,
    )

    try:
        meta = run.meta()
        run.update(typeset_status="running")
        typeset_run(
            pages_dir=run.pages_dir(),
            output_dir=run.output_dir(),
            analyses_file=run.output_dir() / "page_analyses.json",
            options=opts,
            on_progress=emit,
            source_language=meta.get("source_language", "auto") or "auto",
        )
        run.update(typeset_status="done")
    except Exception as e:
        print(f"\n[typeset {run_id}] error: {e}", file=sys.stderr)
        run.update(typeset_status="failed")
        emit({"type": "typeset_error", "message": str(e)})

# ── per-page stage endpoints ───────────────────────────────────────────────────

class RenderOverride(BaseModel):
    dialogue_index: int
    text_translated: str | None = None
    font_style: str | None = None
    font_size_override: int | None = None
    tone: str | None = None
    skip: bool = False


class ReRenderRequest(BaseModel):
    render_overrides: list[RenderOverride] = []


@router.post("/{run_id}/typeset/stages/rendering/{page_num}", status_code=202)
async def rerender_page(run_id: str, page_num: int, body: ReRenderRequest = ReRenderRequest()):
    """Re-run rendering for a single page with optional per-dialogue overrides."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")

    # Load existing stage log to get matches + inpainted image
    debug_dir = run.output_dir() / "typeset" / "debug"
    log_path  = debug_dir / f"p{page_num:02d}_render_log.json"
    if not log_path.exists():
        raise HTTPException(404, "stage log not found — run typesetting first")

    import asyncio as _asyncio
    q: asyncio.Queue = asyncio.Queue()

    async def _task():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _rerender_sync, run_id, page_num,
            [o.model_dump() for o in body.render_overrides], q, loop,
        )
        await q.put(None)

    asyncio.create_task(_task())
    return {"ok": True, "page": page_num}


@router.put("/{run_id}/typeset/renders/{page_num}")
def save_render_overrides(run_id: str, page_num: int, body: ReRenderRequest):
    """Persist render overrides for a page (used on next full re-typeset)."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    overrides_file = debug_dir / f"p{page_num:02d}_render_overrides.json"
    import json as _json
    overrides_file.write_text(_json.dumps(
        [o.model_dump() for o in body.render_overrides], indent=2
    ))
    return {"ok": True}


def _rerender_sync(
    run_id: str, page_num: int,
    overrides: list[dict],
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Re-render a single page using saved matches and a new set of overrides."""
    import json as _json, sys
    from pathlib import Path
    from PIL import Image as _PIL

    run = Run.load(run_id)
    if not run: return

    output_dir = run.output_dir()
    typeset_dir = output_dir / "typeset"
    debug_dir   = typeset_dir / "debug"

    def emit(ev: dict):
        try: loop.call_soon_threadsafe(queue.put_nowait, ev)
        except: pass

    try:
        # Load render log for this page
        log_file = debug_dir / f"p{page_num:02d}_render_log.json"
        stage_log = _json.loads(log_file.read_text())

        # Load the inpainted image (S4 output = base for rendering)
        inpainted_path = debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"
        if not inpainted_path.exists():
            emit({"type": "rerender_error", "page": page_num, "error": "inpainted image not found"})
            return
        base_img = _PIL.open(inpainted_path).convert("RGB")

        # Build override dict keyed by dialogue_index
        override_map = {o["dialogue_index"]: o for o in overrides}

        # Re-render
        from core.typesetting.stages.rendering import build_renderer, RenderResult
        renderer = build_renderer("pil")

        s3 = stage_log.get("s3_matching", {})
        s5 = stage_log.get("s5_rendering", {})
        matches = s3.get("matches", [])
        orig_renders = s5.get("renders", [])
        source_lang = stage_log.get("source_language", "auto")

        result = base_img.copy()
        render_events = []

        for match in matches:
            dlg_i = match["dialogue_index"]
            ovr   = override_map.get(dlg_i, {})

            # skip?
            if ovr.get("skip"):
                render_events.append({"dialogue_index": dlg_i, "status": "skip", "skip_reason": "override"})
                continue

            # get text from override or original render log
            orig = next((r for r in orig_renders if r["dialogue_index"] == dlg_i), {})
            text = ovr.get("text_translated") or orig.get("text", "")

            bbox  = (match["region"]["x1"], match["region"]["y1"],
                     match["region"]["x2"], match["region"]["y2"])
            tone  = ovr.get("tone") or orig.get("tone", "neutral")
            style = ovr.get("font_style") or orig.get("font_style")
            btype = orig.get("bubble_type", "speech")

            rendered, rr = renderer.render(
                image=result,
                bbox=bbox,
                text=text,
                tone=tone,
                bubble_type=btype,
                font_style=style,
                source_language=source_lang,
            )
            if rr.status == "ok":
                result = rendered
            render_events.append({
                "dialogue_index": dlg_i,
                "region_id": match.get("region_id"),
                "text": text,
                "status": rr.status,
                "skip_reason": rr.skip_reason,
                "font_size": rr.font_size,
                "font_style": rr.font_style,
                "lines": rr.lines,
            })

        # Save result
        pages = sorted(
            p for p in run.pages_dir().iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        if page_num <= len(pages):
            out_path = typeset_dir / pages[page_num - 1].name
            result.save(str(out_path), quality=95)
        result.save(str(debug_dir / f"p{page_num:02d}_s5_final.jpg"), quality=88)

        # Update render log
        stage_log["s5_rendering"]["renders"] = render_events
        log_file.write_text(_json.dumps(stage_log, indent=2, ensure_ascii=False))

        emit({"type": "rerender_done", "page": page_num, "renders": len(render_events)})
        print(f"  [rerender] p{page_num}: {len(render_events)} renders done", file=sys.stderr)

    except Exception as e:
        import traceback
        print(f"  [rerender] error: {e}\n{traceback.format_exc()}", file=sys.stderr)
        emit({"type": "rerender_error", "page": page_num, "error": str(e)})

# ── matching refinements ───────────────────────────────────────────────────────

class MatchOverride(BaseModel):
    dialogue_index: int
    region_id: int
    match_type: str = "manual"
    dialogue_text: str = ""


class MatchesBody(BaseModel):
    matches: list[MatchOverride] = []


@router.put("/{run_id}/typeset/matches/{page_num}")
def save_page_matches(run_id: str, page_num: int, body: MatchesBody):
    """Persist refined matches for a page."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    import json as _json
    matches_file = debug_dir / f"p{page_num:02d}_matches_refined.json"
    matches_file.write_text(_json.dumps(
        [m.model_dump() for m in body.matches], indent=2
    ))
    return {"ok": True, "matches": len(body.matches)}


@router.delete("/{run_id}/typeset/matches/{page_num}/refined", status_code=204)
def revert_page_matches(run_id: str, page_num: int):
    """Remove refined matches, reverting to auto matching."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    f = run.output_dir() / "typeset" / "debug" / f"p{page_num:02d}_matches_refined.json"
    if f.exists(): f.unlink()


@router.post("/{run_id}/typeset/stages/matching/{page_num}", status_code=202)
async def rerun_matching(run_id: str, page_num: int):
    """Re-run S3 matching for a single page."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    import asyncio as _asyncio
    q: asyncio.Queue = asyncio.Queue()
    async def _task():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _rematching_sync, run_id, page_num, q, loop)
    asyncio.create_task(_task())
    return {"ok": True}


def _rematching_sync(run_id: str, page_num: int, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    """Re-run matching for a page using saved detections."""
    import json as _json, sys
    from PIL import Image as _PIL
    from core.typesetting.stages.matching import build_matcher
    from core.annotator import load_page_detections_list

    run = Run.load(run_id)
    if not run: return

    def emit(ev: dict):
        try: loop.call_soon_threadsafe(queue.put_nowait, ev)
        except: pass

    try:
        output_dir = run.output_dir()
        debug_dir = output_dir / "typeset" / "debug"

        # Load analyses for this page
        analyses_f = run.active_analyses_file()
        if not analyses_f.exists(): emit({"type": "error", "message": "analyses not found"}); return
        all_analyses = _json.loads(analyses_f.read_text())
        page_data = next((a for a in all_analyses if a.get("page_number") == page_num), None)
        if not page_data: emit({"type": "error", "message": f"page {page_num} not in analyses"}); return

        dialogues = page_data.get("dialogues", [])
        source_lang = page_data.get("source_language", "auto")

        # Load detections
        regions = load_page_detections_list(output_dir, page_num)

        # Get page image
        pages = sorted(p for p in run.pages_dir().iterdir() if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"})
        if page_num > len(pages): emit({"type": "error", "message": "page not found"}); return
        image = _PIL.open(pages[page_num - 1]).convert("RGB")

        from core.typesetting.stages.detection import TextRegion
        from core.typesetting.pipeline import region_from_detection
        img_w, img_h = image.size

        # Direct matches
        saved_dets = {r["id"]: r for r in regions}
        from core.typesetting.stages.matching import MatchResult
        matches = {}
        unresolved = []
        hint_bboxes = []
        for i, dlg in enumerate(dialogues):
            rid = dlg.get("region_id")
            if rid is not None and int(rid) in saved_dets:
                det = saved_dets[int(rid)]
                reg = region_from_detection(det, img_w, img_h)
                matches[i] = MatchResult(
                    dialogue_index=i, region=reg,
                    spatial_score=1.0, text_score=1.0, position_score=1.0, total_score=1.0,
                )
            else:
                unresolved.append(i)
                bx = dlg.get("bbox")
                hint_bboxes.append(tuple(bx) if bx and len(bx) == 4 else None)

        if unresolved:
            from core.typesetting.stages.detection import TextRegion as TR
            candidate_regions = [region_from_detection(r, img_w, img_h) for r in regions]
            matcher = build_matcher("hungarian")
            fb = matcher.match(
                image=image,
                dialogues=[dialogues[i] for i in unresolved],
                regions=candidate_regions,
                hint_bboxes=hint_bboxes,
                source_language=source_lang,
            )
            for local_i, fb_match in fb.items():
                orig_i = unresolved[local_i]
                fb_match.dialogue_index = orig_i
                matches[orig_i] = fb_match

        # Rebuild log
        log_f = debug_dir / f"p{page_num:02d}_render_log.json"
        if log_f.exists():
            log = _json.loads(log_f.read_text())
            match_events = []
            for i, m in matches.items():
                dlg = dialogues[i]
                match_events.append({
                    "dialogue_index": i,
                    "region_id": dlg.get("region_id"),
                    "match_type": "direct" if m.total_score == 1.0 else "fallback",
                    "region": {"x1": m.region.x1, "y1": m.region.y1, "x2": m.region.x2, "y2": m.region.y2,
                               "label": m.region.label, "score": round(m.region.score, 3)},
                    "scores": {"spatial": round(m.spatial_score, 3), "text": round(m.text_score, 3),
                               "position": round(m.position_score, 3), "total": round(m.total_score, 3)},
                    "ocr_text": getattr(m, "ocr_text", None),
                    "dialogue_text": dialogues[i].get("text", "")[:60],
                })
            log["s3_matching"]["matched"] = len(matches)
            log["s3_matching"]["matches"] = match_events
            log_f.write_text(_json.dumps(log, indent=2, ensure_ascii=False))

        emit({"type": "rematching_done", "page": page_num, "matched": len(matches)})
        print(f"  [rematching] p{page_num}: {len(matches)} matched", file=sys.stderr)
    except Exception as e:
        import traceback
        print(f"  [rematching] error: {e}\n{traceback.format_exc()}", file=sys.stderr)
        emit({"type": "rematching_error", "page": page_num, "error": str(e)})


# ── mask refinements ───────────────────────────────────────────────────────────

class MaskBody(BaseModel):
    mask_data_url: str  # base64 PNG data URL


@router.put("/{run_id}/typeset/masks/{page_num}")
def save_page_mask(run_id: str, page_num: int, body: MaskBody):
    """Save a refined inpainting mask as PNG."""
    import base64
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    debug_dir = run.output_dir() / "typeset" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    data_url = body.mask_data_url
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        img_bytes = base64.b64decode(data_url)
        mask_file = debug_dir / f"p{page_num:02d}_mask_refined.png"
        mask_file.write_bytes(img_bytes)
        return {"ok": True, "path": str(mask_file)}
    except Exception as e:
        raise HTTPException(400, f"failed to decode mask: {e}")


@router.post("/{run_id}/typeset/stages/inpainting/{page_num}", status_code=202)
async def rerun_inpainting(run_id: str, page_num: int):
    """Re-run S4 inpainting for a single page using refined mask if it exists."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    q: asyncio.Queue = asyncio.Queue()
    async def _task():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _reinpaint_sync, run_id, page_num, q, loop)
    asyncio.create_task(_task())
    return {"ok": True}


def _reinpaint_sync(run_id: str, page_num: int, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    import json as _json, sys
    import numpy as np
    from PIL import Image as _PIL

    run = Run.load(run_id)
    if not run: return

    def emit(ev: dict):
        try: loop.call_soon_threadsafe(queue.put_nowait, ev)
        except: pass

    try:
        output_dir = run.output_dir()
        debug_dir  = output_dir / "typeset" / "debug"

        # Get original page image
        pages = sorted(p for p in run.pages_dir().iterdir() if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"})
        if page_num > len(pages): emit({"type": "error", "message": "page not found"}); return
        image = _PIL.open(pages[page_num - 1]).convert("RGB")

        # Load refined mask if exists, else compute from saved detections
        refined_mask_f = debug_dir / f"p{page_num:02d}_mask_refined.png"
        if refined_mask_f.exists():
            mask_img = _PIL.open(refined_mask_f).convert("L").resize(image.size)
            mask = np.array(mask_img)
            print(f"  [reinpaint] p{page_num}: using refined mask", file=sys.stderr)
        else:
            # Build mask from matched regions in render log
            log_f = debug_dir / f"p{page_num:02d}_render_log.json"
            if not log_f.exists(): emit({"type": "error", "message": "render log not found"}); return
            log = _json.loads(log_f.read_text())
            from core.typesetting.stages.inpainting import build_text_mask
            img_w, img_h = image.size
            mask = np.zeros((img_h, img_w), dtype=np.uint8)
            for m in log.get("s3_matching", {}).get("matches", []):
                r = m["region"]
                region_mask = build_text_mask(image, (r["x1"], r["y1"], r["x2"], r["y2"]))
                mask = np.maximum(mask, region_mask)
            print(f"  [reinpaint] p{page_num}: using computed mask", file=sys.stderr)

        if mask.sum() == 0:
            emit({"type": "reinpaint_done", "page": page_num, "skipped": True})
            return

        # Inpaint
        from core.typesetting.stages.inpainting import build_inpainter
        meta = run.meta()
        inpainter_backend = meta.get("inpainter_backend", "auto")  # stored in typeset opts would be better
        inpainted = build_inpainter(inpainter_backend).inpaint(image, mask)

        # Save
        inpainted.save(str(debug_dir / f"p{page_num:02d}_s4_inpainted.jpg"), quality=88)

        # Update log
        log_f2 = debug_dir / f"p{page_num:02d}_render_log.json"
        if log_f2.exists():
            log2 = _json.loads(log_f2.read_text())
            log2["s4_inpainting"] = {
                "backend": inpainter_backend,
                "mask_pixels": int(mask.sum() // 255),
                "total_pixels": image.width * image.height,
                "coverage_pct": round(mask.sum() / 255 / max(1, mask.size) * 100, 2),
                "skipped": False,
                "refined_mask": True,
            }
            log_f2.write_text(_json.dumps(log2, indent=2, ensure_ascii=False))

        emit({"type": "reinpaint_done", "page": page_num})
        print(f"  [reinpaint] p{page_num}: done", file=sys.stderr)
    except Exception as e:
        import traceback
        print(f"  [reinpaint] error: {e}\n{traceback.format_exc()}", file=sys.stderr)
        emit({"type": "reinpaint_error", "page": page_num, "error": str(e)})

# ── all-pages stage runners ───────────────────────────────────────────────────

@router.post("/{run_id}/typeset/run/matching", status_code=202)
async def run_matching_all(run_id: str, body: TypesetRequest = TypesetRequest()):
    """Run S3 matching for ALL pages."""
    run = Run.load(run_id); 
    if not run: raise HTTPException(404, "run not found")
    opts = _build_opts(body)
    _launch_stage(run_id, "matching", opts)
    return {"ok": True}


@router.post("/{run_id}/typeset/run/inpainting", status_code=202)
async def run_inpainting_all(run_id: str, body: TypesetRequest = TypesetRequest()):
    """Run S4 inpainting for ALL pages."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    opts = _build_opts(body)
    _launch_stage(run_id, "inpainting", opts)
    return {"ok": True}


@router.post("/{run_id}/typeset/run/rendering", status_code=202)
async def run_rendering_all(run_id: str, body: TypesetRequest = TypesetRequest()):
    """Run S5 rendering for ALL pages."""
    run = Run.load(run_id)
    if not run: raise HTTPException(404, "run not found")
    opts = _build_opts(body)
    _launch_stage(run_id, "rendering", opts)
    return {"ok": True}


def _build_opts(body: TypesetRequest):
    from core.typesetting.pipeline import TypesetOptions
    return TypesetOptions(
        use_translation=body.use_translation, skip_sfx=body.skip_sfx,
        skip_narration=body.skip_narration, max_font_size=body.max_font_size,
        detector_backend=body.detector_backend, detector_threshold=body.detector_threshold,
        matcher_backend=body.matcher_backend, inpainter_backend=body.inpainter_backend,
        renderer_backend=body.renderer_backend, ocr_weight=body.ocr_weight,
        spatial_weight=body.spatial_weight, position_weight=body.position_weight,
        match_min_score=body.match_min_score, save_debug=body.save_debug,
    )


def _launch_stage(run_id: str, stage: str, opts) -> None:
    from api.state import queues as _queues
    q: asyncio.Queue = asyncio.Queue()
    _queues[run_id] = q

    async def _task():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _stage_sync, run_id, stage, opts, q, loop)
        await q.put(None)
        _queues.pop(run_id, None)

    asyncio.create_task(_task())


def _stage_sync(run_id: str, stage: str, opts, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    import traceback, sys
    print(f"\n[stage_sync] starting stage={stage} run={run_id}", file=sys.stderr)

    def emit(ev: dict):
        try: loop.call_soon_threadsafe(queue.put_nowait, ev)
        except Exception as _e:
            print(f"  [emit error] {_e}", file=sys.stderr)

    try:
        from core.typesetting.pipeline import (
            run_matching_stage, run_inpainting_stage, run_rendering_stage,
        )
        print(f"  [{stage}] imports OK", file=sys.stderr)

        run = Run.load(run_id)
        if not run:
            print(f"  [{stage}] run not found: {run_id}", file=sys.stderr)
            emit({"type": "error", "message": f"run not found: {run_id}"})
            return

        status_key = f"typeset_{stage}_status"
        run.update(**{status_key: "running"})

        meta        = run.meta()
        output      = run.output_dir()
        pages_dir   = run.pages_dir()
        analyses_f  = run.active_analyses_file()
        source_lang = meta.get("source_language", "auto")

        print(f"  [{stage}] output={output} analyses_exists={analyses_f.exists()}", file=sys.stderr)

        if not analyses_f.exists():
            msg = f"analyses file not found: {analyses_f} — run analysis phase first"
            print(f"  [{stage}] ERROR: {msg}", file=sys.stderr)
            run.update(**{status_key: "failed"})
            emit({"type": "error", "message": msg})
            return

        if stage == "matching":
            run_matching_stage(pages_dir, output, analyses_f, opts, emit, source_lang)
        elif stage == "inpainting":
            run_inpainting_stage(pages_dir, output, opts, emit)
        elif stage == "rendering":
            run_rendering_stage(pages_dir, output, analyses_f, opts, emit, source_lang)

        run.update(**{status_key: "done"})
        print(f"  [{stage}] done", file=sys.stderr)

    except Exception as e:
        print(f"  [{stage}] EXCEPTION: {e}\n{traceback.format_exc()}", file=sys.stderr)
        try:
            run2 = Run.load(run_id)
            if run2: run2.update(**{f"typeset_{stage}_status": "failed"})
        except: pass
        emit({"type": "error", "message": f"{stage} failed: {e}"})