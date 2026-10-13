"""
Chapter translation — the second step of Read & translate when separate
translation is on.

Input: what the reading step extracted for every page (original text, who
speaks to whom, tone, intent, characters with their speech register, scene,
summary). The translator never sees the images, so context is passed
explicitly in two passes:

  1. style guide (once per chapter): synopsis, a voice sheet per character
     (how they talk in the target language), glossary of names/terms and the
     honorific policy — built from ALL the original lines of the chapter.
  2. lines, in blocks of ~BLOCK lines: each block gets the style guide, the
     scene of each page it touches, the previous lines already translated
     (continuity), and per line: speaker → addressee, bubble type, tone,
     intent and a length hint. Localise, don't translate word by word.

Every model call goes through `ask(system, user, schema) -> str` so the same
code runs on an API connection or a local model, and tests use a fake.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

Ask = Callable[[str, str, dict], str]

BLOCK = 40          # lines per translation call
CONTINUITY = 6      # translated lines carried into the next block


@dataclass
class Line:
    key: str                     # "p{page}.d{index}"
    page: int
    index: int
    text: str
    speaker: str = ""
    addressee: str = ""
    bubble_type: str = "speech"
    tone: str = ""
    intent: str = ""
    max_chars: int | None = None


@dataclass
class ChapterInput:
    source_language: str
    target_language: str
    pages: list[dict]                         # page analyses (dicts, edits merged)
    global_context: str = ""                  # the user's notes for the series
    characters: list[dict] = field(default_factory=list)


@dataclass
class ChapterTranslation:
    lines: dict[str, str]                     # key → translation
    style: dict                               # synopsis, voices, glossary, honorifics
    review: dict[str, str] = field(default_factory=dict)   # key → why it needs a human look


def collect_lines(pages: list[dict]) -> list[Line]:
    out: list[Line] = []
    for p in sorted(pages, key=lambda x: x.get("page_number", 0)):
        pn = p.get("page_number", 0)
        for i, d in enumerate(p.get("dialogues", [])):
            text = (d.get("text") or "").strip()
            if not text or d.get("skip"):
                continue
            out.append(Line(
                key=f"p{pn}.d{i}", page=pn, index=i, text=text,
                speaker=d.get("speaker_id") or "", addressee=d.get("addressee") or "",
                bubble_type=d.get("bubble_type") or "speech", tone=d.get("tone") or "",
                intent=d.get("intent") or "",
                max_chars=max(12, int(len(text) * 1.6)) if d.get("bubble_type") == "sfx" or len(text) < 12 else None,
            ))
    return out


def merge_characters(pages: list[dict]) -> list[dict]:
    """Last known description per character id, with register/relations kept
    from whichever page had them."""
    chars: dict[str, dict] = {}
    for p in sorted(pages, key=lambda x: x.get("page_number", 0)):
        for c in p.get("characters_seen", []):
            cid = c.get("id") or "unknown"
            cur = chars.setdefault(cid, {"id": cid})
            for k in ("description", "speech_register", "relations"):
                if c.get(k):
                    cur[k] = c[k]
    return list(chars.values())


# ── pass 1: style guide ──────────────────────────────────────────────────────

STYLE_SYSTEM = """You are the lead translator of a published comic chapter into {target}. Before translating, you write the chapter's style guide for yourself. You do not see the art; the reader's notes below describe it.
Return JSON only.
- synopsis: 2-4 sentences — what happens, the genre and the overall tone.
- voices: for each character, how they speak in {target} (formality: tú/usted or equivalent; register: rough, polite, childish…; verbal tics; how strong their swearing is IN THE ORIGINAL — never stronger).
- glossary: names, places, techniques, invented terms and recurring words, with the {target} form to use (names usually stay as written).
- honorifics: one rule for Japanese/Korean honorifics and titles (-san, -kun, senpai, hyung, …): keep, adapt or drop — choose what reads naturally for a {target} manga reader and apply it consistently.
- notes: anything else to keep consistent (running jokes, a character's catchphrase).
Rules for the glossary — it will be applied to every line, so a wrong entry spreads everywhere:
- Never change meaning or values. Money keeps the currency the story uses (if the text says yen, it is yen; slang like "grand" or "k" means "thousand" of that same currency, e.g. "mil"). Never introduce dollars or any currency the source doesn't name.
- Only include terms that actually appear in the lines below."""

STYLE_SCHEMA = {
    "type": "object",
    "properties": {
        "synopsis": {"type": "string", "maxLength": 700},
        "voices": {"type": "array", "maxItems": 20, "items": {
            "type": "object",
            "properties": {"id": {"type": "string", "maxLength": 40}, "voice": {"type": "string", "maxLength": 240}},
            "required": ["id", "voice"]}},
        "glossary": {"type": "array", "maxItems": 40, "items": {
            "type": "object",
            "properties": {"source": {"type": "string", "maxLength": 60}, "target": {"type": "string", "maxLength": 60},
                           "note": {"type": "string", "maxLength": 120}},
            "required": ["source", "target"]}},
        "honorifics": {"type": "string", "maxLength": 240},
        "notes": {"type": "string", "maxLength": 400},
    },
    "required": ["synopsis", "voices", "glossary", "honorifics", "notes"],
}


def _style_user(ch: ChapterInput, lines: list[Line]) -> str:
    parts = [f"Source language: {ch.source_language}. Target language: {ch.target_language}."]
    if ch.global_context.strip():
        parts.append(f"## Notes from the reader\n{ch.global_context.strip()}")
    if ch.characters:
        parts.append("## Characters\n" + "\n".join(
            f"- {c['id']}: {c.get('description', '')}"
            + (f" | speaks: {c['speech_register']}" if c.get("speech_register") else "")
            + (f" | {c['relations']}" if c.get("relations") else "")
            for c in ch.characters))
    parts.append("## Pages")
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        by_page.setdefault(ln.page, []).append(ln)
    for p in sorted(ch.pages, key=lambda x: x.get("page_number", 0)):
        pn = p.get("page_number", 0)
        sc = p.get("scene") or {}
        parts.append(f"### Page {pn} — {sc.get('location', '')}, {sc.get('mood', '')}. {sc.get('narrative_beat', '')}")
        for ln in by_page.get(pn, []):
            parts.append(f"- {ln.speaker or '?'}: {ln.text}")
    return "\n".join(parts)


# ── pass 2: lines ────────────────────────────────────────────────────────────

LINES_SYSTEM = """You are a professional comic translator into {target}. You localise: the reader must get the same meaning, tone and effect as a native reader of the original — not the same words.
Rules:
- Follow the style guide: each character's voice, the glossary and the honorific rule.
- Use the context of each line (who speaks to whom, tone, what is happening) to choose the wording. A joke stays a joke, a threat stays a threat.
- Idioms and set phrases → the natural equivalent in {target}, never word by word.
- Never add swearing the original doesn't have; never soften the one it has.
- Numbers, money, units and currency: same values and same currency as the source.
- Sound effects (sfx): a short onomatopoeia used in {target} comics, 1-3 words.
- Captions and signs: concise. Respect max_chars when given (the text must fit its bubble).
- Keep "..." and "!!" style punctuation; use the {target} opening marks when the language has them (¿ ¡).
- If a line is ambiguous without the image, give your best translation and add it to `review` with a short reason.
Return JSON only: one entry per given key, nothing else."""


def _lines_schema(keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "translations": {"type": "array", "minItems": len(keys), "maxItems": len(keys), "items": {
                "type": "object",
                "properties": {"key": {"type": "string", "enum": keys}, "text": {"type": "string", "maxLength": 500}},
                "required": ["key", "text"]}},
            "review": {"type": "array", "maxItems": len(keys), "items": {
                "type": "object",
                "properties": {"key": {"type": "string", "enum": keys}, "reason": {"type": "string", "maxLength": 120}},
                "required": ["key", "reason"]}},
        },
        "required": ["translations", "review"],
    }


def _style_text(style: dict) -> str:
    out = [f"Synopsis: {style.get('synopsis', '')}"]
    if style.get("voices"):
        out.append("Voices:\n" + "\n".join(f"- {v['id']}: {v['voice']}" for v in style["voices"]))
    if style.get("glossary"):
        out.append("Glossary:\n" + "\n".join(
            f"- {g['source']} → {g['target']}" + (f" ({g['note']})" if g.get("note") else "") for g in style["glossary"]))
    if style.get("honorifics"):
        out.append(f"Honorifics: {style['honorifics']}")
    if style.get("notes"):
        out.append(f"Notes: {style['notes']}")
    return "\n".join(out)


def _block_user(ch: ChapterInput, style: dict, block: list[Line], prev: list[tuple[Line, str]]) -> str:
    pages = {p.get("page_number", 0): p for p in ch.pages}
    parts = [f"Translate from {ch.source_language} into {ch.target_language}.", "## Style guide", _style_text(style)]
    if prev:
        parts.append("## Just before (already translated — keep continuity)")
        parts += [f"- {ln.speaker or '?'}: {ln.text} → {tr}" for ln, tr in prev]
    for pn in sorted({ln.page for ln in block}):
        sc = (pages.get(pn) or {}).get("scene") or {}
        parts.append(f"## Page {pn} — {sc.get('location', '')}, {sc.get('mood', '')}. {sc.get('narrative_beat', '')}")
        for ln in (x for x in block if x.page == pn):
            who = f"{ln.speaker or '?'}" + (f" → {ln.addressee}" if ln.addressee else "")
            ctx = ", ".join(x for x in (ln.bubble_type, ln.tone, ln.intent) if x)
            hint = f" [max_chars {ln.max_chars}]" if ln.max_chars else ""
            parts.append(f"- key {ln.key} | {who} | {ctx}{hint}\n  {json.dumps(ln.text, ensure_ascii=False)}")
    return "\n".join(parts)


def _loads(raw: str) -> dict:
    from yomeru.core.analyzer import _parse
    return _parse(raw)


def translate_chapter(ch: ChapterInput, ask: Ask, *, block: int = BLOCK,
                      on_progress: Callable[[str], None] | None = None) -> ChapterTranslation:
    lines = collect_lines(ch.pages)
    if not lines:
        return ChapterTranslation(lines={}, style={})
    ch.characters = ch.characters or merge_characters(ch.pages)
    tgt = ch.target_language

    if on_progress:
        on_progress("style guide")
    style = _loads(ask(STYLE_SYSTEM.format(target=tgt), _style_user(ch, lines), STYLE_SCHEMA))
    print(f"  [translate] style guide: {len(style.get('voices', []))} voices, "
          f"{len(style.get('glossary', []))} glossary terms", file=sys.stderr)

    out: dict[str, str] = {}
    review: dict[str, str] = {}
    done: list[tuple[Line, str]] = []
    for start in range(0, len(lines), block):
        chunk = lines[start:start + block]
        if on_progress:
            on_progress(f"lines {start + 1}-{start + len(chunk)} of {len(lines)}")
        todo = chunk
        for attempt in range(2):   # second try only for keys the model dropped
            keys = [ln.key for ln in todo]
            data = _loads(ask(LINES_SYSTEM.format(target=tgt), _block_user(ch, style, todo, done[-CONTINUITY:]),
                              _lines_schema(keys)))
            got = {t["key"]: t["text"] for t in data.get("translations", [])
                   if isinstance(t, dict) and t.get("key") in keys and str(t.get("text", "")).strip()}
            for r in data.get("review", []) or []:
                if isinstance(r, dict) and r.get("key") in keys:
                    review[r["key"]] = r.get("reason", "")
            out.update(got)
            todo = [ln for ln in todo if ln.key not in got]
            if not todo:
                break
            print(f"  [translate] {len(todo)} lines missing, retrying", file=sys.stderr)
        done += [(ln, out[ln.key]) for ln in chunk if ln.key in out]
    missing = [ln.key for ln in lines if ln.key not in out]
    if missing:
        print(f"  [translate] WARNING: no translation for {missing}", file=sys.stderr)
    return ChapterTranslation(lines=out, style=style, review=review)
