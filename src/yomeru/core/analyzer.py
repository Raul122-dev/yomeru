from __future__ import annotations
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

from json_repair import repair_json
from yomeru.core.models import DEFAULT_FORMAT, PageAnalysis, format_context_str

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load(name: str) -> str:
    p = _PROMPTS_DIR / name
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _get_system_prompt() -> str:
    return _load("system.md")


def _build_language_block(
    source_language: str,
    target_language: str | None,
    ui_language: str,
) -> str:
    lines: list[str] = []

    if source_language and source_language.lower() != "auto":
        lines.append(f"**Source language: {source_language}**")
        lines.append(f"Extract all text verbatim in {source_language}. Do not alter spelling or formatting.")
    else:
        lines.append("**Source language: auto-detect** — extract text verbatim in whatever language is written.")

    if target_language:
        lines.append(f"\n**Translation: {source_language} → {target_language}**")
        lines.append(f"For every dialogue, include `text_translated` with an accurate {target_language} translation.")
        lines.append("Preserve tone and register. Adapt SFX phonetically.")
    else:
        lines.append("\n**Translation: enabled** — include `text_translated` in English by default.")

    if ui_language and ui_language.lower() != "english":
        lines.append(f"\n**Descriptions language: {ui_language}**")
        lines.append(f"Write scene.location, scene.mood, scene.narrative_beat, character descriptions, "
                     f"emotional_state, last_action, and page_summary in {ui_language}.")

    return "\n".join(lines)


def _build_detection_context(regions: list[dict], image_size: tuple[int, int]) -> str:
    """Build a rich detection context for the VLM prompt.
    
    Includes:
    - Region listing with type, position, and dimensions
    - Overlap/adjacency warnings
    - Expected dialogue count hints
    - Clear instructions about text separation
    """
    img_w, img_h = image_size
    n = len(regions)

    # Classify regions
    text_regions = [r for r in regions if r.get("label") in ("text_bubble", "text_free", "sfx", "caption")]
    bubble_regions = [r for r in regions if r.get("label") == "bubble"]

    # Find overlapping/adjacent pairs
    overlap_warnings: list[str] = []
    for i, a in enumerate(regions):
        for j, b in enumerate(regions):
            if j <= i:
                continue
            # Check overlap
            ix1 = max(a["x1"], b["x1"])
            iy1 = max(a["y1"], b["y1"])
            ix2 = min(a["x2"], b["x2"])
            iy2 = min(a["y2"], b["y2"])
            if ix1 >= ix2 or iy1 >= iy2:
                # No intersection — check adjacency (within 20px)
                a_is_text = a.get("label") in ("text_bubble", "text_free", "sfx", "caption")
                b_is_text = b.get("label") in ("text_bubble", "text_free", "sfx", "caption")
                if not (a_is_text and b_is_text):
                    continue
                gap_x = max(0, max(a["x1"], b["x1"]) - min(a["x2"], b["x2"]))
                gap_y = max(0, max(a["y1"], b["y1"]) - min(a["y2"], b["y2"]))
                if gap_x <= 20 and gap_y <= 20:
                    overlap_warnings.append(
                        f"  ⚠ Regions [{a['id']}] and [{b['id']}] are adjacent (gap ~{max(gap_x,gap_y)}px) — they contain SEPARATE text"
                    )
            else:
                # They intersect — only warn if BOTH are text-bearing
                a_is_text = a.get("label") in ("text_bubble", "text_free", "sfx", "caption")
                b_is_text = b.get("label") in ("text_bubble", "text_free", "sfx", "caption")
                if a_is_text and b_is_text:
                    overlap_warnings.append(
                        f"  ⚠ Regions [{a['id']}] and [{b['id']}] OVERLAP — each contains its OWN separate text, do NOT merge them"
                    )

    # Build region listing with richer metadata
    region_lines: list[str] = []
    for r in regions:
        rid = r["id"]
        label = r.get("label", "bubble")
        x1, y1, x2, y2 = r["x1"], r["y1"], r["x2"], r["y2"]
        w, h = x2 - x1, y2 - y1
        # Classify position in 9-zone grid
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        col = "left" if cx < img_w / 3 else ("right" if cx > img_w * 2 / 3 else "center")
        row = "top" if cy < img_h / 3 else ("bottom" if cy > img_h * 2 / 3 else "middle")
        pos = f"{row}-{col}"

        must_have_text = label in ("text_bubble", "text_free", "sfx", "caption")
        marker = "★" if must_have_text else "○"
        region_lines.append(
            f"  {marker} [{rid}] {label} — {w}×{h}px at {pos} ({x1},{y1})-({x2},{y2})"
        )

    # Assemble context
    parts: list[str] = [
        f"\n\n## Detected text regions ({n} total)",
        f"The image has colored numbered boxes drawn on detected regions.",
        f"- ★ = text region (MUST have a dialogue entry) — {len(text_regions)} regions",
        f"- ○ = bubble container (may or may not contain text) — {len(bubble_regions)} regions",
        "",
        "### Region list",
        *region_lines,
    ]

    if overlap_warnings:
        parts.extend([
            "",
            "### ⚠ Overlapping/adjacent regions",
            "These regions are visually close but contain SEPARATE text. "
            "Do NOT combine their text into a single dialogue entry:",
            *overlap_warnings,
        ])

    parts.extend([
        "",
        "### Instructions for region_id assignment",
        "- For EVERY dialogue you extract, set `region_id` to the numbered box that contains that text.",
        "- Each region should map to AT MOST one dialogue entry.",
        f"- You should produce approximately {len(text_regions)} dialogue entries for the ★ regions "
        f"(each text_bubble/text_free/sfx/caption region contains its own separate text).",
        "- If two adjacent bubbles have separate text, create separate dialogue entries with their respective region_ids.",
        "- Only set `region_id: null` if the text truly has no numbered box on it.",
    ])

    return "\n".join(parts)


def _build_user_text(
    page_number: int,
    comic_format: str,
    previous_context: str | None,
    source_language: str = "auto",
    target_language: str | None = None,
    ui_language: str = "English",
    global_context: str = "",
    page_context: str = "",
    image_size: tuple[int, int] | None = None,
) -> str:
    parts: list[str] = []

    # 1. format
    fmt_text = _load(f"format_{comic_format}.md") or _load("format_auto.md")
    if fmt_text:
        parts.append(fmt_text)

    # 2. language instructions
    lang_block = _build_language_block(source_language, target_language, ui_language)
    parts.append(lang_block)

    # 3. global manga context
    if global_context.strip():
        parts.append(f"## Manga context\n\n{global_context.strip()}")

    # 4. previous page context
    if previous_context:
        parts.append(f"## Context from previous pages\n\n{previous_context}\n\nReuse character IDs above for recognized characters.")

    # 5. per-page context
    if page_context.strip():
        parts.append(f"## Note for this page\n\n{page_context.strip()}")

    # 6. instruction
    size_note = ""
    if image_size:
        w, h = image_size
        size_note = f"Image dimensions: {w}×{h} pixels. All bbox coordinates must be in this pixel space (0 to {w} for x, 0 to {h} for y).\n\n"
    parts.append(f"---\n\n{size_note}This is **page {page_number}**. Analyze and return the JSON object.")

    return "\n\n".join(parts)


def _parse(raw: str) -> dict:
    for pat in [r"<[|]endoftext[|]>.*", r"<[|]im_start[|]>.*", r"<[|]im_end[|]>.*"]:
        raw = re.sub(pat, "", raw, flags=re.DOTALL)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"[{].*[}]", raw, re.DOTALL)
    candidate = m.group(0) if m else raw
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        r = repair_json(candidate, return_objects=True)
        if isinstance(r, dict): return r
        raise ValueError(f"unparseable response: {raw[:200]!r}")


# Max dimension (longest side) sent to the model.
# We control the resize ourselves so bbox coordinates are always in this known space,
# regardless of what the API provider might do internally.
MAX_ANALYSIS_SIDE = 1600


def _prepare_image_from_pil(img: "object") -> tuple[str, str, int, int]:
    """Encode an already-loaded PIL Image for the VLM."""
    from PIL import Image as _PIL
    import io as _io
    img = img  # type: ignore[assignment]
    orig_w, orig_h = img.size  # type: ignore[attr-defined]
    max_dim = max(orig_w, orig_h)
    if max_dim > MAX_ANALYSIS_SIDE:
        scale = MAX_ANALYSIS_SIDE / max_dim
        model_w = max(1, int(orig_w * scale))
        model_h = max(1, int(orig_h * scale))
        img = img.resize((model_w, model_h), _PIL.LANCZOS)  # type: ignore[attr-defined]
    else:
        model_w, model_h = orig_w, orig_h
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", quality=92)  # type: ignore[attr-defined]
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    return b64, "image/jpeg", model_w, model_h


def _prepare_image(path: Path) -> tuple[str, str, int, int]:
    """
    Load image, resize to MAX_ANALYSIS_SIDE if needed, encode as JPEG.
    Returns: (base64, mime, model_width, model_height)

    model_width / model_height = what the model actually sees.
    Store these in page_analyses.json so typesetting can scale bboxes
    from model space back to the original full-resolution image.
    """
    from PIL import Image as _PIL
    import io as _io

    img = _PIL.open(path).convert("RGB")
    orig_w, orig_h = img.size

    max_dim = max(orig_w, orig_h)
    if max_dim > MAX_ANALYSIS_SIDE:
        scale = MAX_ANALYSIS_SIDE / max_dim
        model_w = max(1, int(orig_w * scale))
        model_h = max(1, int(orig_h * scale))
        img = img.resize((model_w, model_h), _PIL.LANCZOS)  # type: ignore[attr-defined]
    else:
        model_w, model_h = orig_w, orig_h

    buf = _io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    return b64, "image/jpeg", model_w, model_h


def analyze_page(
    image_path: Path,
    page_number: int,
    previous_context: str | None = None,
    model: str = "",
    comic_format: str = DEFAULT_FORMAT,
    api_base: str | None = None,
    on_token: Callable[[str], None] | None = None,
    # language options
    source_language: str = "auto",
    target_language: str | None = None,
    ui_language: str = "English",
    global_context: str = "",
    page_context: str = "",
    # detection-first options
    output_dir: Path | None = None,
    detector_backend: str = "auto",
    detector_threshold: float = 0.4,
    on_detect_done: Callable[[dict], None] | None = None,
    # If set, load saved/refined detections instead of running detector
    saved_detections_dir: Path | None = None,
) -> PageAnalysis:
    if not model:
        raise ValueError("model is required — set it in Settings or when creating the run")

    import litellm
    litellm.suppress_debug_info = True
    os.environ.setdefault("LITELLM_LOG", "ERROR")

    # ── detection-first: annotate image before sending to VLM ─────────────────
    detection_context = ""

    if saved_detections_dir is not None:
        # Phase 2 analysis-only mode: load saved/refined detections, don't re-run detector
        try:
            from PIL import Image as _PIL_DET
            from yomeru.core.annotator import annotate_from_detections, load_page_detections_list
            raw_img = _PIL_DET.open(image_path).convert("RGB")
            regions = load_page_detections_list(saved_detections_dir, page_number)
            if regions:
                annotated = annotate_from_detections(raw_img, regions)
                n = len(regions)
                print(f"  [analyzer] p{page_number}: {n} saved regions loaded", file=sys.stderr)
                detection_context = _build_detection_context(regions, raw_img.size)
                b64, mime, model_w, model_h = _prepare_image_from_pil(annotated.annotated_image)
            else:
                print(f"  [analyzer] p{page_number}: no saved detections, using original image", file=sys.stderr)
                b64, mime, model_w, model_h = _prepare_image(image_path)
        except Exception as e:
            print(f"  [analyzer] WARNING: failed to load saved detections: {e}", file=sys.stderr)
            b64, mime, model_w, model_h = _prepare_image(image_path)

    elif output_dir is not None:
        # Legacy / run-all mode: run detector + save detections
        try:
            from PIL import Image as _PIL_DET
            from yomeru.core.annotator import annotate_page, save_detections
            raw_img = _PIL_DET.open(image_path).convert("RGB")
            annotated = annotate_page(raw_img, detector_backend, detector_threshold)
            save_detections(annotated.regions, output_dir, page_number, annotated.original_size)
            n = len(annotated.regions)
            if on_detect_done:
                on_detect_done({"type": "page_detect_done", "page": page_number, "regions": n})
            print(f"  [analyzer] p{page_number}: {n} regions annotated", file=sys.stderr)
            detection_context = _build_detection_context(annotated.regions, raw_img.size)
            b64, mime, model_w, model_h = _prepare_image_from_pil(annotated.annotated_image)
        except Exception as e:
            import traceback as _tb
            print(f"  [analyzer] WARNING: detection step failed (backend={detector_backend}): {e}", file=sys.stderr)
            print(_tb.format_exc(), file=sys.stderr)
            print("  [analyzer] falling back to original image (no region annotations)", file=sys.stderr)
            b64, mime, model_w, model_h = _prepare_image(image_path)
    else:
        b64, mime, model_w, model_h = _prepare_image(image_path)
    system_prompt = _get_system_prompt()
    user_text = _build_user_text(
        page_number=page_number,
        comic_format=comic_format,
        previous_context=previous_context,
        source_language=source_language,
        target_language=target_language,
        ui_language=ui_language,
        global_context=global_context,
        page_context=page_context,
        image_size=(model_w, model_h),
    ) + detection_context

    print(f"  → litellm  model={model!r}  api_base={api_base!r}  lang={source_language}"
          + (f" → {target_language}" if target_language else " → English")
          + (f"  ui={ui_language}" if ui_language.lower() != "english" else ""),
          file=sys.stderr)

    stream = litellm.completion(
        model=model,
        max_tokens=3000,
        stream=True,
        api_base=api_base or None,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ],
    )

    chunks: list[str] = []
    for chunk in stream:
        try:
            choices = getattr(chunk, "choices", None)
            if not choices: continue
            delta = getattr(choices[0], "delta", None)
            token: str = getattr(delta, "content", None) or ""
        except (IndexError, AttributeError):
            continue
        if token:
            chunks.append(token)
            if on_token: on_token(token)

    raw = "".join(chunks)
    if not raw.strip():
        raise ValueError(f"empty response from model '{model}'")

    # detect model refusals before trying to parse
    refusal_phrases = [
        "i'm just a language model",
        "i can't help with that",
        "i cannot help with that",
        "i'm not able to",
        "i cannot assist",
        "i'm unable to",
        "as an ai",
        "i don't feel comfortable",
    ]
    raw_lower = raw.lower()
    if any(phrase in raw_lower for phrase in refusal_phrases) and "{" not in raw:
        raise ValueError(
            f"model refused to process this page — "
            f"try a different model or add context explaining this is fictional content. "
            f"Response: {raw[:120]!r}"
        )

    data = _parse(raw)
    data["page_number"] = page_number
    result = PageAnalysis(**data)

    # Post-validate: warn if detection was run but model returned no region_ids
    if output_dir is not None and result.dialogues:
        assigned = sum(1 for d in result.dialogues if d.region_id is not None)
        total = len(result.dialogues)
        if assigned == 0:
            print(
                f"  [analyzer] WARNING p{page_number}: {total} dialogues, 0 region_ids — "
                f"model ignored numbered boxes. Fallback matching will be used.",
                file=sys.stderr,
            )
        else:
            print(f"  [analyzer] p{page_number}: {assigned}/{total} region_ids assigned", file=sys.stderr)

    return result