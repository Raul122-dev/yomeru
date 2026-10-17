"""
Page edits — the user's edited page analyses (`output/edits.json`).

An edit replaces the model's analysis of that page as a whole (translations,
skip toggles, split dialogues…). page_analyses.json is never modified; the
effective analyses are resolved by `artifacts.load_analyses`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

EDITS = "edits.json"


class PageEdits:
    def __init__(self, output_dir: Path):
        self._file = output_dir / EDITS

    def get_edits(self) -> dict:
        """{page_number (str): edited page analysis}"""
        if not self._file.exists():
            return {}
        return json.loads(self._file.read_text())

    def save_edit(self, page_number: int, edited_analysis: dict) -> None:
        data = self.get_edits()
        edited_analysis["_edited_at"] = datetime.now(timezone.utc).isoformat()
        data[str(page_number)] = edited_analysis
        self._write(data)

    def revert(self, pages: Iterable[int]) -> bool:
        """Drop the edits of `pages` (back to the model's output). True if any existed."""
        data = self.get_edits()
        removed = [data.pop(str(p)) for p in pages if str(p) in data]
        if removed:
            self._write(data)
        return bool(removed)

    def merged_analyses(self, original_analyses: list[dict]) -> list[dict]:
        """Analyses with the user's edits applied."""
        edits = self.get_edits()
        return [edits.get(str(a.get("page_number", "")), a) for a in original_analyses]

    def _write(self, data: dict) -> None:
        from yomeru.core.artifacts import tmp_path
        tmp = tmp_path(self._file)
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(self._file)
