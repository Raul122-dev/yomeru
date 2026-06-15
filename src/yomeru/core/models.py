from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


@dataclass(frozen=True)
class ComicFormat:
    name: str
    reading_order: str
    origin: str
    notes: str


COMIC_FORMATS: dict[str, ComicFormat] = {
    "manga": ComicFormat("Manga (Japanese)", "rtl", "Japan",
        "Right-to-left, top-to-bottom. Panel 0 is top-right. "
        "Jagged bubble=shouting, cloud=thinking, box=narration. SFX are kanji/kana in the art."),
    "manhwa": ComicFormat("Manhwa (Korean)", "ltr", "Korea",
        "Left-to-right, top-to-bottom. Often vertical scroll. SFX are hangul/romanized sounds."),
    "manhua": ComicFormat("Manhua (Chinese)", "ltr", "China",
        "Left-to-right (mainland). Traditional/HK may be RTL. Default LTR if unsure."),
    "comic": ComicFormat("Western Comic", "ltr", "Western",
        "Left-to-right, top-to-bottom. Panel 0 is top-left. Caption boxes at panel edges."),
    "auto": ComicFormat("Auto-detect", "auto", "unknown",
        "Detect from art style. Vertical Japanese text → manga RTL. Single strip → manhwa."),
}

DEFAULT_FORMAT = "auto"


def format_context_str(fmt_key: str) -> str:
    fmt = COMIC_FORMATS.get(fmt_key, COMIC_FORMATS["auto"])
    d = fmt.reading_order.upper() if fmt.reading_order != "auto" else "auto-detect"
    return f"Format: {fmt.name}. Reading: {d}. {fmt.notes}"


KNOWN_TONES = {
    "neutral","calm","happy","excited","angry","sad","scared","surprised",
    "whispering","shouting","thinking","serious","tense","sarcastic","eager",
    "melancholic","determined","nervous","relieved","confused","proud","hopeful",
}

_D_ALIASES = {
    "panel_number":"panel_index","panel_idx":"panel_index","panelIndex":"panel_index",
    "speaker":"speaker_id","character":"speaker_id","character_id":"speaker_id",
    "dialogue":"text","content":"text","speech":"text",
    "text_verbatim":"text","verbatim_text":"text","dialogue_text":"text","spoken_text":"text",
    "emotion":"tone","type":"bubble_type","bubble":"bubble_type","dialog_type":"bubble_type",
}
_C_ALIASES = {
    "character_number":"id","char_id":"id","character_id":"id","name":"id",
    "appearance":"description","visual_description":"description",
    "state":"emotional_state","emotion":"emotional_state",
    "action":"last_action","current_action":"last_action",
    "page":"last_seen_page","last_page":"last_seen_page",
}
_S_ALIASES = {
    "setting":"location","place":"location",
    "atmosphere":"mood","feeling":"mood",
    "beat":"narrative_beat","description":"narrative_beat",
}
_P_ALIASES = {
    "panels":"panel_count","total_panels":"panel_count",
    "panel_order":"reading_order","order":"reading_order",
    "dialogue":"dialogues","dialog":"dialogues","conversations":"dialogues",
    "characters":"characters_seen","character_list":"characters_seen",
    "scene_info":"scene","summary":"page_summary",
    "narrative_summary":"page_summary","page_description":"page_summary",
}

def _remap(d: dict, m: dict) -> dict:
    return {m.get(k, k): v for k, v in d.items()}


class Dialogue(BaseModel):
    panel_index: int = 0
    speaker_id: str | None = None
    text: str = ""
    text_translated: str | None = None   # populated when translation is enabled
    tone: str = "neutral"
    bubble_type: str = "narration"
    # region_id: set when detection-first flow is used.
    # References the numbered box drawn on the annotated image sent to VLM.
    # When present, matching is a direct lookup — no bbox scaling needed.
    region_id: int | None = None
    # font_style: visual style of the bubble text
    # bold=action/shout, regular=normal, thought=internal, narration=caption
    font_style: str | None = None
    # line_break_hint: VLM-suggested line breaks for translated text
    line_break_hint: str | None = None
    # skip: VLM or user decision to exclude this dialogue from typesetting.
    # When true, matching/inpainting/rendering will ignore this region.
    # The data is preserved for manual override if needed later.
    skip: bool = False
    skip_reason: str | None = None
    # bbox: legacy fallback (0.0–1.0 fractions of model-space image).
    # Still parsed if the VLM returns it, used as hint when region_id is absent.
    bbox: list[float] | None = None

    @field_validator("bbox", mode="before")
    @classmethod
    def sanitize_bbox(cls, v: object) -> list[float] | None:
        """Accept only valid [x1,y1,x2,y2] — drop extra values the model appended."""
        if v is None:
            return None
        if not isinstance(v, (list, tuple)):
            return None
        nums: list[float] = []
        for item in v:
            try:
                nums.append(float(item))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                break  # stop at first non-numeric
        if len(nums) < 4:
            return None
        return nums[:4]  # take only the first 4 values

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, d: Any) -> Any:
        return _remap(d, _D_ALIASES) if isinstance(d, dict) else d

    @field_validator("tone", mode="before")
    @classmethod
    def clean_tone(cls, v: object) -> str:
        return v.lower().strip() if isinstance(v, str) else "neutral"

    @field_validator("panel_index", mode="before")
    @classmethod
    def clean_idx(cls, v: object) -> int:
        try: return int(v)  # type: ignore[arg-type]
        except: return 0

    @field_validator("text", mode="before")
    @classmethod
    def detect_loop(cls, v: object) -> str:
        if not isinstance(v, str): return str(v) if v else ""
        if len(v) > 80:
            for n in range(1, 11):
                p = v[:n]; r = len(v) // n
                if p * r == v[:n*r] and r > 10:
                    return f"[LOOP: {v[:40]}…]"
        return v


class CharacterState(BaseModel):
    id: str = "unknown"
    description: str = ""
    emotional_state: str = "neutral"
    last_action: str = ""
    last_seen_page: int = 0

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, d: Any) -> Any:
        return _remap(d, _C_ALIASES) if isinstance(d, dict) else d

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> str:
        if isinstance(v, int): return f"char_{v}"
        return str(v).strip() if v else "unknown"

    @field_validator("last_seen_page", mode="before")
    @classmethod
    def coerce_page(cls, v: object) -> int:
        """Model sometimes returns null for last_seen_page — default to 0."""
        if v is None: return 0
        try: return int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError): return 0

    @field_validator("description", "emotional_state", "last_action", mode="before")
    @classmethod
    def coerce_str(cls, v: object) -> str:
        """Model sometimes returns null for optional string fields — coerce to empty string."""
        if v is None: return ""
        return str(v)


class Scene(BaseModel):
    location: str = "unknown"
    mood: str = "neutral"
    narrative_beat: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, d: Any) -> Any:
        return _remap(d, _S_ALIASES) if isinstance(d, dict) else d

    @field_validator("location", "mood", "narrative_beat", mode="before")
    @classmethod
    def coerce_str(cls, v: object) -> str:
        if v is None: return ""
        return str(v)


class PageAnalysis(BaseModel):
    page_number: int
    panel_count: int = 0
    reading_order: list[int] = Field(default_factory=list)
    dialogues: list[Dialogue] = Field(default_factory=list)
    characters_seen: list[CharacterState] = Field(default_factory=list)
    scene: Scene = Field(default_factory=Scene)
    page_summary: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, d: Any) -> Any:
        if not isinstance(d, dict): return d
        d = _remap(d, _P_ALIASES)
        if isinstance(d.get("scene"), str):
            d["scene"] = {"narrative_beat": d["scene"]}
        if not d.get("reading_order") and d.get("panel_count"):
            d["reading_order"] = list(range(int(d["panel_count"])))
        return d


class ContextObject(BaseModel):
    total_pages_processed: int = 0
    characters: dict[str, CharacterState] = Field(default_factory=dict)
    scene: Scene | None = None
    page_summaries: list[dict] = Field(default_factory=list)
    dialogue_history: list[dict] = Field(default_factory=list)
    chunk_summaries: list[str] = Field(default_factory=list)

    def update(self, a: PageAnalysis) -> None:
        self.total_pages_processed += 1
        for c in a.characters_seen:
            if c.id in self.characters:
                ex = self.characters[c.id]
                ex.emotional_state = c.emotional_state
                ex.last_action = c.last_action
                ex.last_seen_page = c.last_seen_page
            else:
                self.characters[c.id] = c
        self.scene = a.scene
        self.page_summaries.append({"page": a.page_number, "summary": a.page_summary})
        for d in a.dialogues:
            self.dialogue_history.append({"page": a.page_number, **d.model_dump()})

    def compress_chunk(self, analyses: list[PageAnalysis]) -> str:
        if not analyses: return ""
        pages = [a.page_number for a in analyses]
        chars = {c.id: c.description[:40] for a in analyses for c in a.characters_seen}
        summaries = " | ".join(a.page_summary[:60] for a in analyses)
        last = analyses[-1].scene
        return (f"[pp{pages[0]}-{pages[-1]}] chars: "
                f"{', '.join(f'{k} ({v})' for k,v in chars.items()) or 'none'}. "
                f"scene: {last.location}, {last.mood}. story: {summaries}")

    def build_context(self, recent: int = 2) -> str:
        lines: list[str] = []
        if self.characters:
            lines.append("characters:")
            for cid, c in self.characters.items():
                lines.append(f"  {cid}: {c.description[:50]} | {c.emotional_state} | {c.last_action[:40]}")
        if self.chunk_summaries:
            lines.append("story so far:")
            for s in self.chunk_summaries: lines.append(f"  · {s}")
        for ps in self.page_summaries[-recent:]:
            lines.append(f"  p{ps['page']}: {ps['summary'][:80]}")
        if self.scene:
            lines.append(f"scene: {self.scene.location} — {self.scene.mood}")
        return "\n".join(lines)