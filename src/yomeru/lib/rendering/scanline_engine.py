"""Scanline rendering engine.

Lays out every matched dialogue of a page inside its bubble (contour-following
scanlines, vertical CJK-style columns for narrow bubbles, bbox fallback),
normalises font sizes across the page, nudges colliding lines apart and draws
the result twice: a debug image with green bubble contours and the production
image.

Pure function of the run's files: no HTTP, no globals. Used by the rendering
phase and by the preview endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from yomeru.core import artifacts
from yomeru.core.languages import profile, text_rules
from yomeru.core.paths import FONTS_DIR
from yomeru.core.labels import CONTAINER_LABELS, TEXT_BUBBLE, is_free as is_free_label
from yomeru.core.paths import list_page_files
from yomeru.core.runs import Run
from yomeru.lib.rendering.color_detect import (
    detect_background_color,
)
from yomeru.lib.rendering.pil import (
    _get_font, _tone_to_style,
)
from yomeru.lib.rendering.scanline import (
    extract_bubble_contour, scanline_layout,
)
from yomeru.lib.rendering.text_layout import (
    measure_line_height, measure_width, extract_embedded_breaks, wrap_text,
)


class RenderInputMissing(Exception):
    """A file the engine needs (page, inpainted image, render log) does not exist."""


@dataclass
class RenderOutput:
    preview_path: Path
    production_path: Path
    layouts: int
    # One record per effective match, as actually rendered: status ok/skip
    # (+ reason), the text used, final font size, style, lines and container.
    events: list[dict]


def output_paths(run: Run, page_num: int) -> tuple[Path, Path]:
    return (artifacts.page_artifact(run, page_num, artifacts.SCANLINE_PREVIEW),
            artifacts.page_artifact(run, page_num, artifacts.SCANLINE_PRODUCTION))


def input_paths(run: Run, page_num: int) -> list[Path]:
    """Files whose change makes a cached render stale."""
    a = artifacts
    return [a.page_artifact(run, page_num, n) for n in
            (a.RENDER_LOG, a.MATCHES_REFINED, a.RENDER_OVERRIDES)] + [
        a.existing_page_artifact(run, page_num, a.S4_INPAINTED),
        run.active_analyses_file(),
        run.output_dir() / "edits.json",       # merged into the dialogues
        run.output_dir() / a.TRANSLATIONS,     # separate translation step
        run.active_detections_file(),          # bubble containers
        FONTS_DIR,                             # a font added/removed changes the drawing
    ]


def settings_signature(run: Run) -> str:
    """The run settings that change a render (technique + options, use_translation,
    target language). Compared by value, not by meta.json's mtime: meta.json is
    rewritten for status/progress at the end of every job, which made every
    finished run look stale and re-render on first view."""
    import hashlib
    import json
    from yomeru.core.settings import run_settings
    st = run_settings(run.meta())
    key = {"rendering": st.rendering.model_dump(), "target": st.language.target}
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def _signature_path(run: Run, page_num: int) -> Path:
    return output_paths(run, page_num)[1].with_suffix(".sig")


def largest_fitting_layout(sizes, width_factors, try_layout, usable_h: int, max_fill: float = 0.95):
    """First (size, font, lines) — sizes descending, widest factor first — whose
    text block fits in `max_fill` of the usable height. `try_layout(size, wf)`
    returns (font, lines, line_height) or None. Legibility first: a larger size
    that fits always wins; fewer, wider lines win at equal size."""
    for size in sizes:
        for wf in width_factors:
            got = try_layout(size, wf)
            if got is None:
                continue
            font, lines, lh = got
            if len(lines) * lh / usable_h <= max_fill:
                return (size, font, lines)
    return None


HYPHEN_GAIN = 1.4


MAX_OVER_MEDIAN = 1.45   # a short line in a big bubble shouldn't shout over the page
MIN_UNDER_MEDIAN = 0.7   # small outliers are lifted toward the median when they fit
TOUCH_GAP = 0            # px: containers must overlap to be one visual bubble (double bubbles)


def bubble_groups(bboxes: list[tuple[int, int, int, int]], gap: int = TOUCH_GAP) -> list[list[int]]:
    """Indices of containers that touch or overlap (double/joined bubbles)."""
    n = len(bboxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        ax1, ay1, ax2, ay2 = bboxes[i]
        for j in range(i + 1, n):
            bx1, by1, bx2, by2 = bboxes[j]
            if ax1 - gap <= bx2 and bx1 - gap <= ax2 and ay1 - gap <= by2 and by1 - gap <= ay2:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def harmonize_sizes(sizes, bboxes, adjustable, min_font, joinable=None) -> dict[int, tuple[int, int]]:
    """Target size window (lo, hi) per adjustable layout:
    - joined bubbles share one size (the group's smallest: it is what fits);
    - nothing exceeds MAX_OVER_MEDIAN x the page median;
    - small outliers are lifted toward MIN_UNDER_MEDIAN x median (only if it fits).
    Callers re-lay out inside the contour and keep the old layout otherwise."""
    plan: dict[int, tuple[int, int]] = {}
    if not sizes:
        return plan
    med = sorted(sizes)[len(sizes) // 2]
    cap = int(med * MAX_OVER_MEDIAN)
    floor = int(med * MIN_UNDER_MEDIAN)
    want = list(sizes)
    for i, s in enumerate(sizes):
        if not adjustable[i]:
            continue
        if len(sizes) > 2 and s > cap:
            want[i] = cap
            plan[i] = (min_font, cap)
        elif len(sizes) > 2 and s < floor:
            plan[i] = (s + 1, floor)
    joinable = joinable or [True] * len(sizes)
    idx = [i for i in range(len(sizes)) if joinable[i]]
    groups = [[idx[k] for k in g] for g in bubble_groups([bboxes[i] for i in idx])]
    for g in groups:
        target = min(want[i] for i in g)
        for i in g:
            if not adjustable[i]:
                continue
            if want[i] > target:
                plan[i] = (min_font, target)
            else:
                plan.pop(i, None)  # the group's size-setter: no lift that would break the match
    return plan


def proper_names(source: str, drawn: str) -> frozenset[str]:
    """Words the translation carries over verbatim from the source (character
    names). Never split at a syllable."""
    import re
    tok = lambda s: {w.upper() for w in re.findall(r"[^\W\d_]{3,}", s)}  # noqa: E731
    return frozenset(tok(source) & tok(drawn))


def prefer_unsplit(whole, split):
    """Syllable splits only when they buy a clearly larger font (>= 40%):
    '¡¡GRA-CIAS!!' or 'TRABA-JO' for +3 pt read worse than whole words."""
    if whole is None:
        return split
    if split is not None and split[0] >= whole[0] * HYPHEN_GAIN:
        return split
    return whole


def is_cached(run: Run, page_num: int) -> bool:
    preview, production = output_paths(run, page_num)
    if not (preview.exists() and production.exists()):
        return False
    mtime = min(preview.stat().st_mtime, production.stat().st_mtime)
    if any(f.exists() and f.stat().st_mtime > mtime for f in input_paths(run, page_num)):
        return False
    sig = _signature_path(run, page_num)
    return sig.exists() and sig.read_text() == settings_signature(run)


def build_request(run: Run, page_num: int, use_translation: bool | None = None):
    """Everything the render needs for one page, resolved from the run's files
    (edits, refined matches, overrides, settings). Backends only see this."""
    from yomeru.core.contracts import RenderRequest
    from yomeru.core.settings import run_settings

    inpainted_path = artifacts.existing_page_artifact(run, page_num, artifacts.S4_INPAINTED)
    if not inpainted_path.exists():
        raise RenderInputMissing("No inpainted image for this page")
    all_pages = list_page_files(run.pages_dir())
    if page_num < 1 or page_num > len(all_pages):
        raise RenderInputMissing(f"Page {page_num} not found")
    log = artifacts.load_render_log(run, page_num)
    if log is None:
        raise RenderInputMissing("No render log for this page")

    with Image.open(inpainted_path) as _im:
        img = _im.convert("RGB")
    with Image.open(all_pages[page_num - 1]) as _im:
        original_img = _im.convert("RGB")

    page_analysis = artifacts.page_analysis(artifacts.load_analyses(run), page_num)
    st = run_settings(run.meta())
    if use_translation is None:
        use_translation = st.rendering.use_translation
    # Hyphenation rules of the language being DRAWN: the target language for
    # translations (was the source language → Spanish split with en_US rules),
    # the source language when rendering the original text.
    drawn_lang = st.language.target if use_translation else page_analysis.get("source_language", "auto")
    return RenderRequest(
        inpainted=img,
        original=original_img,
        matches=artifacts.effective_matches(run, page_num, log),
        dialogues=page_analysis.get("dialogues", []),
        overrides=artifacts.load_render_overrides(run, page_num),
        skipped=artifacts.skipped_dialogues(page_analysis, artifacts.load_render_overrides(run, page_num)),
        # Bubble containers from the active (possibly edited) detections, in file order
        containers=[
            (r["x1"], r["y1"], r["x2"], r["y2"])
            for r in artifacts.load_detections(run).get(page_num, {}).values() if r.get("label") in CONTAINER_LABELS
        ],
        use_translation=use_translation,
        lang_code=profile(drawn_lang).hyphenation,
        drawn_language=drawn_lang if drawn_lang != "auto" else "",
        edit_cache=artifacts.PageEditCache(run, page_num),
    )


def render_page(run: Run, page_num: int, use_translation: bool | None = None,
                backend: str | None = None, backend_options: dict | None = None) -> RenderOutput:
    """Render one page with the run's rendering backend; writes preview +
    production images atomically. Facade used by the phase, the preview
    endpoints and tests."""
    from yomeru.core.settings import run_settings
    from yomeru.plugins import get_backend

    from contextlib import nullcontext
    from yomeru.core.gpu import gpu_lock

    req = build_request(run, page_num, use_translation)
    st = run_settings(run.meta()).rendering
    spec, be = get_backend("rendering", backend or st.backend, backend_options if backend else st.options)
    with (gpu_lock() if spec.needs_gpu else nullcontext()):
        res = be.render_page(req)
    preview_path, production_path = output_paths(run, page_num)
    if res.preview is not None:
        _save_atomic(res.preview, preview_path)
    _save_atomic(res.image, production_path)
    if (backend is None or backend == st.backend) and use_translation in (None, req.use_translation) \
            and req.use_translation == run_settings(run.meta()).rendering.use_translation:
        # rendered with the run's own settings → valid cache for the preview endpoints
        _signature_path(run, page_num).write_text(settings_signature(run))
    return RenderOutput(preview_path, production_path, res.layouts, res.events)


def layout_and_draw(req):
    """The scanline technique: pure function of the request (no run, no files)."""
    from yomeru.core.contracts import RenderResult

    img = req.inpainted
    original_img = req.original
    # Resolution-relative font floor
    MIN_FONT = max(8, max(img.size) // 150)
    matches = req.matches
    dialogues = req.dialogues
    overrides = req.overrides
    skipped_set = req.skipped
    bubble_regions = list(req.containers)
    use_translation = req.use_translation
    lang_code = req.lang_code

    # Pre-compute contours for all bubbles (expensive, cache once)
    bubble_contours: dict[tuple[int, int, int, int], object] = {}
    for bb in bubble_regions:
        bubble_contours[bb] = extract_bubble_contour(original_img, bb)

    result_img = img.copy()
    draw = ImageDraw.Draw(result_img)

    # Deduplicate: when multiple dialogues share the same region bbox,
    # keep only the LAST one (typically the actual dialogue, not auxiliary text)
    seen_bboxes: dict[tuple[int, int, int, int], int] = {}
    for idx, m in enumerate(matches):
        r = m["region"]
        bbox_key = (r["x1"], r["y1"], r["x2"], r["y2"])
        seen_bboxes[bbox_key] = idx  # last one wins
    valid_match_indices = set(seen_bboxes.values())

    # ── Pass 1: Compute all layouts ──────────────────────────────────────────
    # Store: list of (layout, is_free, text_color, outline_color, bubble_bbox, text_angle, clean_text, lang_code)
    all_layouts: list[tuple] = []
    events: list[dict] = []
    layout_event: list[dict] = []  # parallel to all_layouts
    layout_relayout: list = []     # parallel: contour re-search fn or None
    container_owner: dict[tuple, int] = {}

    def skip_event(dlg_i: int, m: dict, reason: str, text: str = "") -> None:
        events.append({"dialogue_index": dlg_i, "region_id": m.get("region_id"),
                       "status": "skip", "skip_reason": reason, "text": text})

    # Columns of vertical CJK free text that will be turned 90° (see
    # rotated_free below): horizontal free text crossing one keeps clear of it.
    turned_columns = []
    for m in matches:
        di, r = m.get("dialogue_index", -1), m.get("region") or {}
        if 0 <= di < len(dialogues) and is_free_label(r.get("label", "")):
            d = dialogues[di]
            tt = (d.get("text_translated") if use_translation else d.get("text")) or ""
            if (text_rules(d.get("text") or "").vertical_native and tt and text_rules(tt).turn_vertical_source
                    and (r["y2"] - r["y1"]) >= 2.5 * (r["x2"] - r["x1"])):
                turned_columns.append((r["x1"], r["y1"], r["x2"], r["y2"]))

    for match_idx, m in enumerate(matches):
        dlg_i = m.get("dialogue_index", -1)
        if match_idx not in valid_match_indices:
            skip_event(dlg_i, m, "duplicate_region")
            continue
        if dlg_i < 0 or dlg_i >= len(dialogues):
            skip_event(dlg_i, m, "no_dialogue")
            continue

        dlg = dialogues[dlg_i]
        ovr = overrides.get(dlg_i, {})

        # Skip (override or VLM-suggested)
        if dlg_i in skipped_set:
            skip_event(dlg_i, m, ovr.get("skip_reason") or dlg.get("skip_reason") or "skipped")
            continue

        if use_translation:
            text = ovr.get("text_translated") or dlg.get("text_translated") or dlg.get("text", "")
            if (not ovr.get("text_translated") and text_rules(text).caps_follow_source
                    and _all_caps(dlg.get("text", ""))):
                text = text.upper()  # lettering in capitals stays in capitals (the model mixed cases)
        else:  # layout check with the original text
            text = dlg.get("text", "")
        if not text.strip():
            skip_event(dlg_i, m, "empty_text")
            continue

        r = m["region"]
        text_bbox = (r["x1"], r["y1"], r["x2"], r["y2"])
        label = r.get("label", TEXT_BUBBLE)
        if is_free_label(label):
            text_bbox = _clear_of_columns(text_bbox, turned_columns)

        # Color and style for free text vs bubble text
        is_free = is_free_label(label)

        # Only an ERASED region may go down to the minimum size / overflow: if the
        # original text is still there (user's mask edit), a squeezed translation
        # on top of it garbles both — keep the old behaviour (skip as no_fit).
        erased = _was_erased(original_img, img, text_bbox)
        floor = MIN_FONT if erased else MIN_FONT + 1

        # Find containing bubble
        tcx = (text_bbox[0] + text_bbox[2]) // 2
        tcy = (text_bbox[1] + text_bbox[3]) // 2
        bubble_bbox = _container_for(text_bbox, (tcx, tcy), bubble_regions) or text_bbox

        # For free text: expand bbox horizontally into surrounding homogeneous area
        if is_free and bubble_bbox == text_bbox:
            expanded = _expand_free_text_bbox(img, text_bbox)
            # Use expanded X (width) but keep original Y (vertical centering on sign)
            bubble_bbox = _clear_of_columns((expanded[0], text_bbox[1], expanded[2], text_bbox[3]), turned_columns)

        # Clean text
        clean_text, _ = extract_embedded_breaks(text)
        if not clean_text.strip():
            skip_event(dlg_i, m, "empty_text", text)
            continue
        lang_code_for_this_match = lang_code

        # Determine style and font
        tone = ovr.get("tone") or dlg.get("tone", "neutral")
        bubble_type = dlg.get("bubble_type", "speech")
        font_style_ovr = ovr.get("font_style") or dlg.get("font_style")
        style = font_style_ovr if font_style_ovr else _tone_to_style(tone, bubble_type)

        if is_free:
            # Free text: ALWAYS black text + white outline (universally readable)
            text_color = (0, 0, 0)
            outline_color = (255, 255, 255)
            # Force bold for free text
            style = "bold"
        else:
            bg_color = detect_background_color(img, text_bbox)
            lum = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
            text_color = (0, 0, 0) if lum > 128 else (255, 255, 255)
            outline_color = None

        # Adaptive padding based on bubble size
        bubble_w = bubble_bbox[2] - bubble_bbox[0]
        bubble_h = bubble_bbox[3] - bubble_bbox[1]
        scan_padding = max(5, min(12, int(min(bubble_w, bubble_h) * 0.06)))

        # Detect vertical bubble (tall and narrow)
        is_vertical_bubble = bubble_h > bubble_w * 1.8

        # Max font size: for vertical bubbles, allow larger fonts
        # (they'll use more lines with narrow width factors)
        if is_vertical_bubble:
            max_size = max(20, min(50, bubble_h // 5))
        else:
            max_size = max(30, min(60, bubble_h // 6))
            if bubble_w < 80:
                max_size = min(max_size, max(12, bubble_w // 4))

        # A short shout (one or two words) is lettered big in comics: let it
        # grow with its bubble, and keep it out of the page-median cap, which
        # shrank it to body-text size in bubbles the original fills.
        words_ = clean_text.split()
        is_shout = (not is_free and style == "bold" and tone in ("shouting", "screaming", "yelling", "angry", "excited")
                    and len(words_) <= 2 and len(clean_text.replace(" ", "")) <= 12)
        if is_shout:
            max_size = max(max_size, min(120, bubble_h // 2, bubble_w))

        # User-fixed size (render editor): the search starts at it, so the text
        # is never larger; it may still shrink if it truly does not fit.
        size_override = ovr.get("font_size_override")
        if size_override:
            max_size = max(MIN_FONT + 1, int(size_override))

        # Width factors: vertical bubbles get narrower factors to use more lines
        if is_vertical_bubble:
            width_factors = (0.90, 0.75, 0.60, 0.45, 0.35, 0.25)
        else:
            width_factors = (0.90, 0.70, 0.55, 0.45)

        # For very narrow bubbles with SHORT text, use vertical text layout
        # (char-by-char top-to-bottom). Only for brief expressions (≤3 short words,
        # ≤12 chars total) — longer text uses normal horizontal layout with small font.
        best_layout = None
        relayout = None  # contour re-search at other sizes (harmonisation pass)
        words = clean_text.strip().split()
        char_count = len(clean_text.replace(" ", ""))
        is_short_text = len(words) <= 3 and char_count <= 12

        # Determine if vertical layout would produce a significantly better result:
        # Compare potential font size in horizontal vs vertical mode
        horiz_max_font = max(8, bubble_w // max(len(max(words, key=len)) if words else 1, 1))
        vert_potential_font = min(bubble_w - 10, bubble_h // max(char_count, 1) - 2) if char_count > 0 else 0

        # Stacking one glyph per line only reads naturally in CJK scripts; Latin
        # text became '¡/N/O/!' columns.
        rules = text_rules(clean_text)
        use_vertical = (
            rules.vertical_native
            and is_short_text
            and vert_potential_font > horiz_max_font * 1.5  # vertical gives ≥50% larger font
            and vert_potential_font >= 12  # minimum legible size
            and bubble_h > bubble_w * 1.8
        ) or (
            # A one-word Latin shout in a very tall, narrow bubble: scanlators
            # stack the letters; horizontal gave 9-11px.
            # Normal bubbles keep horizontal text ("¡NO!" stacked read badly).
            rules.stack_shouts and _all_caps(clean_text)   # stacked lowercase reads badly
            and len(words) == 1 and 3 <= char_count <= 14
            and bubble_h >= bubble_w * 2.5
            and vert_potential_font >= max(14, horiz_max_font * 1.8)
        )

        # Vertical CJK lettering on the art (e.g. cover blurbs) translated to
        # a Latin script: lay the line out along the column and turn it 90°
        # (spine-style), instead of a 12px horizontal staircase across the art.
        rotated_free = (
            is_free and rules.turn_vertical_source and text_rules(dlg.get("text") or "").vertical_native
            and (text_bbox[3] - text_bbox[1]) >= 2.5 * (text_bbox[2] - text_bbox[0])
        )
        rot90 = False
        if rotated_free:
            best_layout = _rotated_free_layout(clean_text, style, text_bbox, MIN_FONT, lang_code_for_this_match)
            if best_layout is not None:
                use_vertical, rot90 = False, True

        if use_vertical and clean_text.strip():
            vert_pad = max(4, scan_padding)
            usable_w = bubble_w - vert_pad * 2
            usable_h = bubble_h - vert_pad * 2

            vert_words = clean_text.strip().split()
            flat = "".join(vert_words)
            total_word_gaps = max(0, len(vert_words) - 1)

            # Font size = what fits the width
            vert_size = min(usable_w - 4, 40)
            vert_size = max(10, vert_size)

            # Fixed line_spacing between characters
            # Free text needs more gap due to outline adding visual weight
            line_spacing = max(4, vert_size // 4) if is_free else max(3, vert_size // 6)
            word_extra = vert_size // 3  # extra gap between words

            # Measure actual per-char heights using getbbox
            vert_font = _get_font(style, vert_size)
            char_heights = []
            for ch in flat:
                bb = vert_font.getbbox(ch)
                char_heights.append(bb[3] - bb[1] if bb else vert_size)

            total_h = sum(char_heights) + line_spacing * (len(flat) - 1) + word_extra * total_word_gaps

            # Shrink font if total exceeds 80% of usable height
            max_fill = int(usable_h * 0.80)
            while total_h > max_fill and vert_size > 10:
                vert_size -= 1
                vert_font = _get_font(style, vert_size)
                line_spacing = max(3, vert_size // 6)
                word_extra = vert_size // 3
                char_heights = []
                for ch in flat:
                    bb = vert_font.getbbox(ch)
                    char_heights.append(bb[3] - bb[1] if bb else vert_size)
                total_h = sum(char_heights) + line_spacing * (len(flat) - 1) + word_extra * total_word_gaps

            from yomeru.lib.rendering.scanline import PositionedLine
            positioned_lines = []

            # Center block vertically
            start_y = bubble_bbox[1] + vert_pad + (usable_h - total_h) // 2
            col_x = bubble_bbox[0] + vert_pad + (usable_w - vert_size) // 2

            cy = start_y
            char_idx = 0
            for word_idx, word in enumerate(vert_words):
                for ch in word:
                    bb = vert_font.getbbox(ch)
                    ch_w = bb[2] - bb[0] if bb else vert_size
                    cx = col_x + (vert_size - ch_w) // 2
                    # Compensate for bbox top offset: draw at cy - bb[1]
                    draw_y = cy - (bb[1] if bb else 0)
                    positioned_lines.append(PositionedLine(text=ch, x=cx, y=draw_y, width=vert_size))
                    cy += char_heights[char_idx] + line_spacing
                    char_idx += 1
                if word_idx < len(vert_words) - 1:
                    cy += word_extra

            if positioned_lines:
                best_layout = (vert_size, vert_font, positioned_lines)

        # Largest size that fits (fill <= 0.95). At that size prefer the widest
        # lines (fewest breaks); narrower width factors only when the wide one
        # fails. The old search optimised for a vertical-fill band (0.35-0.85)
        # and discarded larger sizes that fit, giving small text with many breaks.
        if best_layout is None:
            protected = proper_names(dlg.get("text") or "", clean_text)

            # Bound by value: `relayout` is called after the loop (harmonisation)
            def _try_with(hyphenate: bool | str, _style=style, _bb=bubble_bbox, _text=clean_text,
                          _lang=lang_code_for_this_match, _pad=scan_padding, _prot=protected):
                def _try(size: int, wf: float):
                    font = _get_font(_style, size)
                    pos = scanline_layout(
                        original_img, _bb, _text, font, size, _lang, padding=_pad, width_factor=wf,
                        precomputed_contour=bubble_contours.get(_bb), hyphenate=hyphenate, protected=_prot,
                    )
                    return (font, pos, measure_line_height(font, size)) if pos else None
                return _try

            usable_h = max(1, bubble_h - scan_padding * 2)

            def _search(sizes, _wf=width_factors, _uh=usable_h, _t=_try_with):
                whole = largest_fitting_layout(sizes, _wf, _t(False), usable_h=_uh)
                split = largest_fitting_layout(sizes, _wf, _t(True), usable_h=_uh)
                got = prefer_unsplit(whole, split)
                if got is None:  # nothing fits whole: any split (never names)
                    got = largest_fitting_layout(sizes, _wf, _t("force"), usable_h=_uh)
                return got

            best_layout = _search(range(max_size, floor - 1, -3))
            relayout = _search

        # FALLBACK: if scanline failed, use simple bbox centered rendering
        overflow = False
        if best_layout is None:
            for try_size in range(max(max_size, floor), floor - 1, -1):
                font = _get_font(style, try_size)
                lh = measure_line_height(font, try_size)
                pad = max(4, scan_padding)
                bw = bubble_w - pad * 2
                bh = bubble_h - pad * 2
                if bw < 10 or bh < 10:
                    continue
                if lh > (bubble_h - 2) * 1.1:
                    # taller than the whole box: SFX/notes came out at 30px over
                    # 20px-high originals, across panel borders and page edges
                    continue
                max_lines = max(1, bh // lh)
                lines = wrap_text(clean_text, bw, max_lines, font, lang_code_for_this_match)
                if lines:
                    from yomeru.lib.rendering.scanline import PositionedLine
                    total_h = len(lines) * lh
                    start_y = bubble_bbox[1] + pad + (bh - total_h) // 2
                    positioned_lines = []
                    for li, line in enumerate(lines):
                        lw = measure_width(line, font)
                        lx = bubble_bbox[0] + pad + (bw - lw) // 2
                        positioned_lines.append(PositionedLine(text=line, x=lx, y=start_y + li * lh, width=bw))
                    best_layout = (try_size, font, positioned_lines)
                    break

        # LAST RESORT: the region was erased, so it must never stay empty (an
        # empty bubble reads worse than a slightly larger text). Smallest legible
        # size, wrapped to the box width (or the longest word), centred on the
        # box and kept on the page; reported as `overflow` for review.
        if best_layout is None and erased:
            best_layout = _overflow_layout(clean_text, _get_font(style, MIN_FONT), MIN_FONT, bubble_bbox,
                                           img.size, lang_code_for_this_match)
            overflow = best_layout is not None

        if best_layout:
            # Detect text angle for free text regions
            text_angle = 0.0
            if rot90:
                text_angle = -90.0
            elif is_free:
                from yomeru.lib.rendering.angle_detect import detect_text_angle
                text_angle = detect_text_angle(original_img, text_bbox)

            # One dialogue per bubble container: two matches resolving to the
            # same container used to be drawn on top of each other. Keep the
            # likelier one (not an SFX, longer text); the other is reported.
            prev = container_owner.get(bubble_bbox) if not is_free else None
            if prev is not None:
                pev = layout_event[prev]
                mine = (bubble_type != "sfx", len(clean_text))
                theirs = (pev["bubble_type"] != "sfx", len(pev["text"]))
                if mine <= theirs:
                    skip_event(dlg_i, m, "same_container", text)
                    continue
                pev.update(status="skip", skip_reason="same_container")
                all_layouts[prev] = None
            all_layouts.append((best_layout, is_free, text_color, outline_color, bubble_bbox, text_angle, clean_text, lang_code_for_this_match))
            if not is_free:
                container_owner[bubble_bbox] = len(all_layouts) - 1
            layout_relayout.append(relayout)
            ev = {"dialogue_index": dlg_i, "region_id": m.get("region_id"), "status": "ok",
                  "text": text, "font_style": style, "tone": tone, "bubble_type": bubble_type,
                  "bbox": list(bubble_bbox), "box_size": [bubble_w, bubble_h], "free": is_free,
                  "size_fixed": bool(size_override)}
            if is_shout:
                ev["shout"] = True
            if overflow:
                ev["overflow"] = True
            events.append(ev)
            layout_event.append(ev)
        else:
            skip_event(dlg_i, m, "no_fit", text)

    keep = [k for k, lay in enumerate(all_layouts) if lay is not None]
    all_layouts = [all_layouts[k] for k in keep]
    layout_event = [layout_event[k] for k in keep]
    layout_relayout = [layout_relayout[k] for k in keep]

    # ── Font harmony (contour layouts only; never through the bbox fallback) ──
    plan = harmonize_sizes(
        sizes=[lay[0][0] for lay in all_layouts],
        bboxes=[lay[4] for lay in all_layouts],
        adjustable=[layout_relayout[i] is not None and not layout_event[i].get("size_fixed")
                    and not layout_event[i].get("free") and not layout_event[i].get("shout")
                    for i in range(len(all_layouts))],
        min_font=MIN_FONT,
        # only speech-like balloons join; narration boxes sit edge to edge
        joinable=[layout_event[i].get("bubble_type") not in ("narration", "sfx") for i in range(len(all_layouts))],
    )
    for idx, (lo, hi) in plan.items():
        cur = all_layouts[idx][0][0]
        sizes = list(range(hi, lo - 1, -3)) if hi > cur else list(range(min(hi, cur), MIN_FONT, -3))
        got = layout_relayout[idx](sizes)
        if got is not None and lo <= got[0] <= hi:
            all_layouts[idx] = (got, *all_layouts[idx][1:])

    # ── Pass 2: Resolve line-level collisions between regions ────────────────
    # For each layout, compute per-line bounding boxes
    layout_line_rects: list[list[tuple[int, int, int, int]]] = []
    for (size, font, positioned), *_ in all_layouts:
        lh = measure_line_height(font, size)
        rects = []
        for pl in positioned:
            lw = measure_width(pl.text, font)
            rects.append((pl.x, pl.y, pl.x + lw, pl.y + lh))
        layout_line_rects.append(rects)

    # Check each pair of layouts for line-level collisions and nudge
    # Minimum readability gap between texts of different regions (in pixels).
    # Texts closer than this will be pushed apart even without actual overlap.
    # Scaled by average font size for consistency across resolutions.
    avg_font_size = sum(layout[0][0] for layout in all_layouts) / max(1, len(all_layouts)) if all_layouts else 20
    MIN_GAP = max(8, int(avg_font_size * 0.6))

    for i in range(len(all_layouts)):
        for j in range(i + 1, len(all_layouts)):
            rects_i = layout_line_rects[i]
            rects_j = layout_line_rects[j]
            if not rects_i or not rects_j:
                continue

            # Quick check: do the overall bounds (expanded by MIN_GAP) overlap?
            bounds_i = (min(r[0] for r in rects_i) - MIN_GAP, min(r[1] for r in rects_i) - MIN_GAP,
                        max(r[2] for r in rects_i) + MIN_GAP, max(r[3] for r in rects_i) + MIN_GAP)
            bounds_j = (min(r[0] for r in rects_j) - MIN_GAP, min(r[1] for r in rects_j) - MIN_GAP,
                        max(r[2] for r in rects_j) + MIN_GAP, max(r[3] for r in rects_j) + MIN_GAP)

            if bounds_i[2] <= bounds_j[0] or bounds_j[2] <= bounds_i[0]:
                continue
            if bounds_i[3] <= bounds_j[1] or bounds_j[3] <= bounds_i[1]:
                continue

            # Find lines that collide OR are too close (within MIN_GAP)
            for li_idx, ri in enumerate(rects_i):
                for lj_idx, rj in enumerate(rects_j):
                    # Expand rects by MIN_GAP for proximity detection
                    # Check if they're within MIN_GAP of each other
                    gap_x = max(0, max(ri[0], rj[0]) - min(ri[2], rj[2]))  # horizontal gap
                    gap_y = max(0, max(ri[1], rj[1]) - min(ri[3], rj[3]))  # vertical gap

                    # Lines must be vertically adjacent (y ranges overlap or nearly overlap)
                    if gap_y > MIN_GAP:
                        continue
                    # Lines must be horizontally close
                    if gap_x > MIN_GAP:
                        continue

                    # Compute how much they overlap or how close they are
                    overlap_x = min(ri[2], rj[2]) - max(ri[0], rj[0])  # negative = gap
                    overlap_y = min(ri[3], rj[3]) - max(ri[1], rj[1])  # negative = gap

                    # Needed separation: if overlapping, need to push by overlap + gap
                    # If just too close, need to push by (MIN_GAP - current_gap)
                    needed_x = (overlap_x + MIN_GAP) if overlap_x > 0 else (MIN_GAP - gap_x)
                    needed_y = (overlap_y + MIN_GAP) if overlap_y > 0 else (MIN_GAP - gap_y)

                    if needed_x <= 0 and needed_y <= 0:
                        continue

                    (_, _, pos_i), *_ = all_layouts[i]
                    (_, _, pos_j), *_ = all_layouts[j]
                    bbox_i = all_layouts[i][4]  # bubble_bbox
                    bbox_j = all_layouts[j][4]

                    # Compute margins in all directions for both layouts
                    margin_top_i = rects_i[0][1] - bbox_i[1] if rects_i else 0
                    margin_bot_i = bbox_i[3] - rects_i[-1][3] if rects_i else 0
                    margin_left_i = min(r[0] for r in rects_i) - bbox_i[0] if rects_i else 0
                    margin_right_i = bbox_i[2] - max(r[2] for r in rects_i) if rects_i else 0

                    margin_top_j = rects_j[0][1] - bbox_j[1] if rects_j else 0
                    margin_bot_j = bbox_j[3] - rects_j[-1][3] if rects_j else 0
                    margin_left_j = min(r[0] for r in rects_j) - bbox_j[0] if rects_j else 0
                    margin_right_j = bbox_j[2] - max(r[2] for r in rects_j) if rects_j else 0

                    # Decide: horizontal or vertical nudge based on which requires less movement
                    if needed_x <= needed_y:
                        # Horizontal nudge is smaller — shift left/right
                        nudge_amount = needed_x

                        # Determine relative positions
                        center_x_i = (ri[0] + ri[2]) // 2
                        center_x_j = (rj[0] + rj[2]) // 2

                        # Decide who moves: check if nudge fits within the bubble.
                        # The region that can absorb the shift WITHOUT exiting its bubble wins.
                        if center_x_i < center_x_j:
                            # i is left, j is right
                            # Option A: push i left (needs margin_left_i >= nudge)
                            # Option B: push j right (needs margin_right_j >= nudge)
                            can_i_left = margin_left_i >= nudge_amount
                            can_j_right = margin_right_j >= nudge_amount

                            if can_i_left and (not can_j_right or margin_left_i >= margin_right_j):
                                shift = -nudge_amount
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x + shift,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                            elif can_j_right:
                                shift = nudge_amount
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x + shift,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                            else:
                                # Neither fully fits — split: move each by half
                                half = nudge_amount // 2 + 1
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x - half,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x + half,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                        else:
                            # j is left, i is right
                            can_j_left = margin_left_j >= nudge_amount
                            can_i_right = margin_right_i >= nudge_amount

                            if can_j_left and (not can_i_right or margin_left_j >= margin_right_i):
                                shift = -nudge_amount
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x + shift,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                            elif can_i_right:
                                shift = nudge_amount
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x + shift,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                            else:
                                half = nudge_amount // 2 + 1
                                pos_j[lj_idx] = type(pos_j[lj_idx])(
                                    text=pos_j[lj_idx].text, x=pos_j[lj_idx].x - half,
                                    y=pos_j[lj_idx].y, width=pos_j[lj_idx].width)
                                pos_i[li_idx] = type(pos_i[li_idx])(
                                    text=pos_i[li_idx].text, x=pos_i[li_idx].x + half,
                                    y=pos_i[li_idx].y, width=pos_i[li_idx].width)
                    else:
                        # Vertical nudge is smaller — shift up/down
                        nudge_amount = needed_y // 2 + 2

                        center_y_i = (ri[1] + ri[3]) // 2
                        center_y_j = (rj[1] + rj[3]) // 2

                        total_margin_v_i = margin_top_i + margin_bot_i
                        total_margin_v_j = margin_top_j + margin_bot_j

                        if total_margin_v_i >= total_margin_v_j:
                            # Shift layout i's lines near the collision
                            shift = -nudge_amount if center_y_i < center_y_j else nudge_amount
                            if shift < 0:
                                for k in range(li_idx + 1):
                                    pos_i[k] = type(pos_i[k])(text=pos_i[k].text, x=pos_i[k].x, y=pos_i[k].y + shift, width=pos_i[k].width)
                            else:
                                for k in range(li_idx, len(pos_i)):
                                    pos_i[k] = type(pos_i[k])(text=pos_i[k].text, x=pos_i[k].x, y=pos_i[k].y + shift, width=pos_i[k].width)
                        else:
                            shift = -nudge_amount if center_y_j < center_y_i else nudge_amount
                            if shift < 0:
                                for k in range(lj_idx + 1):
                                    pos_j[k] = type(pos_j[k])(text=pos_j[k].text, x=pos_j[k].x, y=pos_j[k].y + shift, width=pos_j[k].width)
                            else:
                                for k in range(lj_idx, len(pos_j)):
                                    pos_j[k] = type(pos_j[k])(text=pos_j[k].text, x=pos_j[k].x, y=pos_j[k].y + shift, width=pos_j[k].width)

                    # Update rects after nudge
                    (size_i, font_i, _), *_ = all_layouts[i]
                    lh_i = measure_line_height(font_i, size_i)
                    layout_line_rects[i] = [(p.x, p.y, p.x + measure_width(p.text, font_i), p.y + lh_i) for p in pos_i]

                    (size_j, font_j, _), *_ = all_layouts[j]
                    lh_j = measure_line_height(font_j, size_j)
                    layout_line_rects[j] = [(p.x, p.y, p.x + measure_width(p.text, font_j), p.y + lh_j) for p in pos_j]
                    break  # Re-check after nudge
                else:
                    continue
                break  # Move to next pair after resolving

    # ── Pass 3: Render all layouts ───────────────────────────────────────────
    for layout_idx, ((size, font, positioned), is_free, text_color, outline_color, bubble_bbox, text_angle, _clean_text, _layout_lang_code) in enumerate(all_layouts):
        outline_w = max(4, size // 4) if is_free else 0

        if is_free and abs(text_angle) > 3 and positioned:
            # Render rotated text for angled free text
            _render_scanline_rotated(
                draw, result_img, positioned, font, size, text_color,
                outline_color, outline_w, text_angle, bubble_bbox,
            )
        else:
            from yomeru.lib.rendering.pil import _render_text_with_fallback
            for pl in positioned:
                _render_text_with_fallback(
                    draw, (pl.x, pl.y), pl.text, font, text_color, size,
                    outline_color if is_free else None, outline_w,
                )

        # Draw contour outline for debug (thin green)
        contour = bubble_contours.get(bubble_bbox)
        if contour is not None:
            pts = contour.reshape(-1, 2).tolist()
            if len(pts) > 2:
                draw.polygon([tuple(p) for p in pts], outline=(0, 200, 0))

    # Production version (no contours) — reuse resolved layouts
    prod_img = img.copy()
    prod_draw = ImageDraw.Draw(prod_img)

    for (size, font, positioned), is_free, text_color, outline_color, _bbox, text_angle, _clean_text, _layout_lang_code in all_layouts:
        outline_w = max(4, size // 4) if is_free else 0

        if is_free and abs(text_angle) > 3 and positioned:
            _render_scanline_rotated(
                prod_draw, prod_img, positioned, font, size, text_color,
                outline_color, outline_w, text_angle, _bbox,
            )
        else:
            from yomeru.lib.rendering.pil import _render_text_with_fallback
            for pl in positioned:
                _render_text_with_fallback(
                    prod_draw, (pl.x, pl.y), pl.text, font, text_color, size,
                    outline_color if is_free else None, outline_w,
                )

    # Final size and lines after harmonisation + collision nudging
    for ev, ((size, _font, positioned), *_rest) in zip(layout_event, all_layouts):
        ev["font_size"] = size
        ev["lines"] = [pl.text for pl in positioned]
    events.sort(key=lambda e: e["dialogue_index"])
    return RenderResult(image=prod_img, preview=result_img, events=events, layouts=len(all_layouts))


def _all_caps(s: str) -> bool:
    letters = [c for c in s if c.isalpha() and c.lower() != c.upper()]   # cased scripts only
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def _inside(text_bbox, box) -> float:
    """Fraction of the text box's area inside `box`."""
    ix = max(0, min(text_bbox[2], box[2]) - max(text_bbox[0], box[0]))
    iy = max(0, min(text_bbox[3], box[3]) - max(text_bbox[1], box[1]))
    area = max(1, (text_bbox[2] - text_bbox[0]) * (text_bbox[3] - text_bbox[1]))
    return ix * iy / area


def _container_for(text_bbox, center, containers):
    """The first container holding the text's centre — unless that one cuts
    through the text (< 70% inside) while another holds it whole (>= 90%):
    bubble boxes are rectangles and overlap, so a small caption next to a
    speech bubble had its centre inside the speech bubble's box and was drawn
    on top of its dialogue."""
    cx, cy = center
    first = next((c for c in containers if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]), None)
    if first is None or _inside(text_bbox, first) >= 0.7:
        return first
    better = [c for c in containers if _inside(text_bbox, c) >= 0.9]
    return min(better, key=lambda c: (c[2] - c[0]) * (c[3] - c[1])) if better else first


def _was_erased(original: Image.Image, inpainted: Image.Image, box, min_changed: float = 0.02) -> bool:
    """True if inpainting changed the region (its text is gone)."""
    import numpy as np
    x1, y1, x2, y2 = (int(v) for v in box)
    a = np.asarray(original.crop((x1, y1, x2, y2)).convert("L"), dtype=np.int16)
    b = np.asarray(inpainted.crop((x1, y1, x2, y2)).convert("L"), dtype=np.int16)
    return a.size > 0 and float((np.abs(a - b) > 24).mean()) >= min_changed


def _clear_of_columns(box, columns, gap: int = 6):
    """A horizontal free-text box crossed by a turned column keeps the larger
    side of it (otherwise it runs under the turned column)."""
    x1, y1, x2, y2 = box
    for cx1, cy1, cx2, cy2 in columns:
        if (cx1, cy1, cx2, cy2) == box or cy2 <= y1 or cy1 >= y2 or cx2 <= x1 or cx1 >= x2:
            continue
        if (y2 - y1) >= (x2 - x1):        # itself a column: leave it
            continue
        left, right = cx1 - gap - x1, x2 - (cx2 + gap)
        if max(left, right) <= 0:
            continue
        x1, x2 = (x1, cx1 - gap) if left >= right else (cx2 + gap, x2)
    return (x1, y1, x2, y2)


def _rotated_free_layout(text: str, style: str, box, min_font: int, lang_code):
    """Layout in the box turned 90° (width = column height), centred on the
    box's centre; drawn rotated -90° by the caller. Largest size that fits."""
    from yomeru.lib.rendering.scanline import PositionedLine
    w, h = box[2] - box[0], box[3] - box[1]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    vw, vh = h, w
    for size in range(min(60, max(min_font, int(vh * 0.8))), min_font - 1, -1):
        font = _get_font(style, size)
        lh = measure_line_height(font, size)
        max_lines = max(1, int(vh // lh))
        lines = wrap_text(text, vw - 6, max_lines, font, lang_code)
        if not lines or len(lines) * lh > vh:
            continue
        block_h = len(lines) * lh
        y0 = int(cy - block_h / 2)
        out = []
        for i, ln in enumerate(lines):
            lw = measure_width(ln, font)
            out.append(PositionedLine(text=ln, x=int(cx - lw / 2), y=y0 + i * lh, width=vw))
        return (size, font, out)
    return None


def _overflow_layout(text: str, font, size: int, box, page_size, lang_code):
    """Layout at `size` that ignores the box height: wrap to the box width (at
    least the longest word), centre on the box, clamp inside the page."""
    from yomeru.lib.rendering.scanline import PositionedLine
    words = text.split() or [text]
    longest = max(measure_width(w, font) for w in words)
    bw = max(box[2] - box[0] - 4, longest + 2)
    lines = wrap_text(text, bw, 999, font, lang_code) or [text]
    lh = measure_line_height(font, size)
    block_w = max(measure_width(ln, font) for ln in lines)
    block_h = lh * len(lines)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x0 = int(min(max(2, cx - block_w / 2), page_size[0] - block_w - 2))
    y0 = int(min(max(2, cy - block_h / 2), page_size[1] - block_h - 2))
    out = []
    for i, ln in enumerate(lines):
        lw = measure_width(ln, font)
        out.append(PositionedLine(text=ln, x=x0 + (block_w - lw) // 2, y=y0 + i * lh, width=block_w))
    return (size, font, out)


def _save_atomic(img: Image.Image, path: Path) -> None:
    if path.suffix.lower() == ".png":
        artifacts.save_lossless(img, path)
        return
    tmp = artifacts.tmp_path(path)
    img.save(str(tmp), quality=90)
    tmp.replace(path)


def _render_scanline_rotated(draw, base_img, positioned, font, size, text_color, outline_color, outline_w, angle, bubble_bbox):
    """Render positioned lines with rotation for angled free text."""
    from PIL import Image, ImageDraw as ID

    # Compute text block bounds
    lh = int(font.getmetrics()[0] + font.getmetrics()[1])
    min_x = min(pl.x for pl in positioned)
    min_y = min(pl.y for pl in positioned)
    max_x = max(pl.x + int(font.getlength(pl.text)) for pl in positioned)
    max_y = max(pl.y + lh for pl in positioned)

    # Create a transparent canvas for the text block
    block_w = max_x - min_x + outline_w * 2 + 4
    block_h = max_y - min_y + outline_w * 2 + 4
    canvas = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    cdraw = ID.Draw(canvas)

    # Draw text on canvas (offset to local coords)
    for pl in positioned:
        local_x = pl.x - min_x + outline_w + 2
        local_y = pl.y - min_y + outline_w + 2
        if outline_color and outline_w > 0:
            ow_sq = (outline_w + 0.5) ** 2
            for dx in range(-outline_w, outline_w + 1):
                for dy in range(-outline_w, outline_w + 1):
                    if dx == 0 and dy == 0:
                        continue
                    if dx * dx + dy * dy > ow_sq:
                        continue
                    cdraw.text((local_x + dx, local_y + dy), pl.text, font=font, fill=outline_color + (255,))
            cdraw.text((local_x, local_y), pl.text, font=font, fill=text_color + (255,))
        else:
            cdraw.text((local_x, local_y), pl.text, font=font, fill=text_color + (255,))

    # Rotate the canvas
    # detect_text_angle returns degrees counter-clockwise (text rising to the
    # right is positive), which is PIL's rotate convention: same sign. It used
    # to be negated, so tilted free text was drawn tilted the other way.
    rotated = canvas.rotate(angle, expand=True, resample=Image.BICUBIC)

    # Compute paste position (center rotated block on original text center)
    cx = (min_x + max_x) // 2
    cy = (min_y + max_y) // 2
    paste_x = cx - rotated.width // 2
    paste_y = cy - rotated.height // 2

    # Composite onto base image (handle RGB images by using temp RGBA conversion)
    if base_img.mode != "RGBA":
        # Convert to RGBA, paste, convert back
        rgba_img = base_img.convert("RGBA")
        rgba_img.paste(rotated, (paste_x, paste_y), rotated)
        # Copy pixels back to original image (maintains reference)
        base_img.paste(rgba_img.convert("RGB"))



def _expand_free_text_bbox(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    max_expand: int = 80,
    variance_threshold: float = 50.0,
) -> tuple[int, int, int, int]:
    """
    Expand a text_free bbox into surrounding homogeneous area.

    Checks strips of pixels outside the bbox in each direction.
    If the strip has low color variance (uniform background like a sign),
    expand the bbox in that direction.

    Only expands where the background is clearly uniform (not into detailed art).
    """
    arr = np.array(image)
    img_h, img_w = arr.shape[:2]
    x1, y1, x2, y2 = bbox

    def strip_std(strip: np.ndarray) -> float:
        """Compute std of a strip (lower = more uniform)."""
        if strip.size == 0:
            return 999.0
        return float(strip.astype(np.float32).std())

    # Try expanding LEFT
    new_x1 = x1
    for step in range(4, max_expand + 1, 4):
        check_x = max(0, x1 - step)
        strip = arr[y1:y2, check_x:check_x + 4]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_x1 = check_x
        else:
            break

    # Try expanding RIGHT
    new_x2 = x2
    for step in range(4, max_expand + 1, 4):
        check_end = min(img_w, x2 + step)
        check_start = check_end - 4
        if check_start < x2:
            check_start = x2
        strip = arr[y1:y2, check_start:check_end]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_x2 = check_end
        else:
            break

    # Try expanding UP (less aggressive)
    new_y1 = y1
    for step in range(4, max_expand // 2 + 1, 4):
        check_y = max(0, y1 - step)
        strip = arr[check_y:check_y + 4, x1:x2]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_y1 = check_y
        else:
            break

    # Try expanding DOWN
    new_y2 = y2
    for step in range(4, max_expand // 2 + 1, 4):
        check_end = min(img_h, y2 + step)
        check_start = check_end - 4
        if check_start < y2:
            check_start = y2
        strip = arr[check_start:check_end, x1:x2]
        if strip.size > 0 and strip_std(strip) < variance_threshold:
            new_y2 = check_end
        else:
            break

    # Grow the same on both sides so the text stays where it was: a one-sided
    # gain slid it off its spot — an SFX went out into the white page margin
    # because only the margin side was uniform.
    if x1 > 4 and x2 < img_w - 4:
        g = min(x1 - new_x1, new_x2 - x2)
        new_x1, new_x2 = x1 - g, x2 + g
    return (new_x1, new_y1, new_x2, new_y2)


