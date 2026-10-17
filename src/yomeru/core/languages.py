"""
Language profiles — every language-dependent rule of the pipeline in one place.

Layers, each one only overriding what differs:

    GENERAL (all languages)  →  SCRIPT (latin, cjk, hangul, …)  →  LANGUAGE (es, ja, …)

Two kinds of lookups:
  * `profile(name)`  — by the run's language setting ("Spanish", "Japanese",
    "auto"): the SOURCE profile says how the original is lettered and read
    (OCR, reading direction); the TARGET profile how we draw (hyphenation).
  * `text_rules(text)` — by the script the text is actually written in
    (a Japanese tagline in an English run is still vertical CJK lettering).

Adding a language = one entry in LANGUAGES with its differences (+ its pages
in the test set). Adding a tuning = a field here (default in GENERAL), then
read it where the decision is made — never `if lang in (...)` in the code.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class LanguageProfile:
    name: str = "auto"
    script: str = "latin"
    iso: str = ""                               # ISO 639-1 (export metadata)
    # ── reading the original ──
    ocr_engine: str = "easyocr"                 # easyocr | manga_ocr
    ocr_codes: tuple[str, ...] = ("en", "es", "pt")
    ocr_boxes: bool = True                      # page OCR with word boxes (locate missed text, split repeated SFX)
    reads_right_to_left: bool = False           # only used when the comic format is 'auto'
    # ── drawing ──
    hyphenation: str | None = "en_US"           # pyphen dictionary, None = no syllable breaks
    vertical_native: bool = False               # short text may be stacked one glyph per line
    stack_shouts: bool = True                   # one-word capital shout in a tall narrow bubble → stacked letters
    turn_vertical_source: bool = True           # vertical CJK lettering translated to this script → turned 90°
    caps_follow_source: bool = True             # all-caps lettering stays all-caps (cased scripts only)


GENERAL = LanguageProfile()

SCRIPTS: dict[str, dict] = {
    "latin": {},
    "cyrillic": {},
    "cjk": dict(script="cjk", ocr_boxes=False, hyphenation=None, vertical_native=True,
                stack_shouts=False, turn_vertical_source=False, caps_follow_source=False),
    "hangul": dict(script="hangul", ocr_boxes=False, hyphenation=None, vertical_native=True,
                   stack_shouts=False, turn_vertical_source=False, caps_follow_source=False),
    "other": dict(script="other", hyphenation=None),   # thai, arabic, vietnamese… (no rules yet)
}

LANGUAGES: dict[str, tuple[str, dict]] = {
    # name (as in settings): (script, overrides)
    "auto": ("latin", {}),
    "English": ("latin", dict(iso="en", ocr_codes=("en",), hyphenation="en_US")),
    "Spanish": ("latin", dict(iso="es", ocr_codes=("es", "en"), hyphenation="es")),
    "Portuguese": ("latin", dict(iso="pt", ocr_codes=("pt", "en"), hyphenation="pt_BR")),
    "French": ("latin", dict(iso="fr", ocr_codes=("fr", "en"), hyphenation="fr")),
    "German": ("latin", dict(iso="de", ocr_codes=("de", "en"), hyphenation="de")),
    "Italian": ("latin", dict(iso="it", ocr_codes=("it", "en"), hyphenation="it")),
    "Dutch": ("latin", dict(iso="nl", hyphenation="nl")),
    "Polish": ("latin", dict(iso="pl", hyphenation="pl")),
    "Turkish": ("latin", dict(iso="tr", hyphenation="tr")),
    "Indonesian": ("latin", dict(iso="id", hyphenation="id")),
    "Russian": ("cyrillic", dict(iso="ru", hyphenation="ru")),
    "Japanese": ("cjk", dict(iso="ja", ocr_engine="manga_ocr", ocr_codes=("ja",), reads_right_to_left=True)),
    "Chinese (Simplified)": ("cjk", dict(iso="zh", ocr_codes=("ch_sim",))),
    "Chinese (Traditional)": ("cjk", dict(iso="zh", ocr_codes=("ch_tra",), reads_right_to_left=True)),
    "Korean": ("hangul", dict(iso="ko", ocr_codes=("ko",))),
    "Thai": ("other", dict(iso="th")),
    "Vietnamese": ("other", dict(iso="vi")),
    "Arabic": ("other", dict(iso="ar")),
}


def _build(name: str, script: str, overrides: dict) -> LanguageProfile:
    allowed = {f.name for f in fields(LanguageProfile)}
    for layer in (SCRIPTS[script], overrides):
        unknown = set(layer) - allowed
        if unknown:
            raise ValueError(f"language profile {name!r}: unknown fields {sorted(unknown)}")
    return replace(GENERAL, **{**SCRIPTS[script], **overrides, "name": name, "script": script})


_PROFILES = {name: _build(name, script, ov) for name, (script, ov) in LANGUAGES.items()}


def profile(name: str | None) -> LanguageProfile:
    """Profile of a language setting; unknown names get the general one."""
    return _PROFILES.get(name or "auto") or _PROFILES["auto"]


def text_rules(text: str) -> LanguageProfile:
    """Rules of the script `text` is written in (content, not settings)."""
    from yomeru.lib.rendering.text_layout import is_cjk_text
    if not is_cjk_text(text or ""):
        return _SCRIPT_RULES["latin"]
    hangul = sum(0xAC00 <= ord(c) <= 0xD7AF for c in text)
    return _SCRIPT_RULES["hangul" if hangul > len(text) / 4 else "cjk"]


_SCRIPT_RULES = {s: _build(s, s, {}) for s in SCRIPTS}


# Scripts the shipped fonts can letter (ComicNeue covers Latin, including
# Turkish İ/ğ through the raqm layout; Vietnamese is "other"). A target outside
# them renders as tofu, so the UI does not offer it.
SHIPPED_FONT_SCRIPTS = frozenset({"latin"})


def language_options() -> list[dict]:
    """The languages the UI offers, from the profiles (GET /config/languages)."""
    return [
        {"name": name, "label": "Auto-detect" if name == "auto" else name,
         "code": p.iso, "script": p.script, "has_font": p.script in SHIPPED_FONT_SCRIPTS}
        for name, p in _PROFILES.items()
    ]
