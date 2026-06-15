from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path


class AnnotationStore:
    """
    Manages user annotations and edits for a run's page analyses.

    Files:
      {run_output_dir}/annotations.json  — notes per page (never modifies original)
      {run_output_dir}/edits.json        — user-edited page analyses (full objects)

    The original page_analyses.json is never touched.
    When rendering, edits.json takes precedence over page_analyses.json for edited pages.
    """

    def __init__(self, output_dir: Path):
        self._ann_file  = output_dir / "annotations.json"
        self._edit_file = output_dir / "edits.json"

    # ── annotations (notes, not data edits) ───────────────────────────────────

    def get_annotations(self) -> dict:
        """Returns {page_number: [annotation, ...]}"""
        if not self._ann_file.exists():
            return {}
        return json.loads(self._ann_file.read_text())

    def add_annotation(self, page_number: int, field: str, note: str, original_value: str = "") -> dict:
        data = self.get_annotations()
        key = str(page_number)
        if key not in data:
            data[key] = []
        annotation = {
            "id": uuid.uuid4().hex[:8],
            "page": page_number,
            "field": field,
            "note": note,
            "original_value": original_value,
            "created_at": datetime.utcnow().isoformat(),
        }
        data[key].append(annotation)
        self._ann_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return annotation

    def delete_annotation(self, page_number: int, annotation_id: str) -> bool:
        data = self.get_annotations()
        key = str(page_number)
        if key not in data:
            return False
        before = len(data[key])
        data[key] = [a for a in data[key] if a["id"] != annotation_id]
        self._ann_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return len(data[key]) < before

    # ── edits (user-modified page analyses) ───────────────────────────────────

    def get_edits(self) -> dict:
        """Returns {page_number: edited_page_analysis}"""
        if not self._edit_file.exists():
            return {}
        return json.loads(self._edit_file.read_text())

    def save_edit(self, page_number: int, edited_analysis: dict) -> None:
        """Save a user-edited version of a page analysis."""
        data = self.get_edits()
        edited_analysis["_edited_at"] = datetime.utcnow().isoformat()
        data[str(page_number)] = edited_analysis
        self._edit_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def revert_edit(self, page_number: int) -> None:
        """Remove user edit, reverting to original model output."""
        data = self.get_edits()
        data.pop(str(page_number), None)
        self._edit_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_page(self, page_number: int, original_analyses: list[dict]) -> dict | None:
        """Return edited version if exists, else original."""
        edits = self.get_edits()
        if str(page_number) in edits:
            return edits[str(page_number)]
        return next((a for a in original_analyses if a.get("page_number") == page_number), None)

    def merged_analyses(self, original_analyses: list[dict]) -> list[dict]:
        """Return analyses with user edits applied."""
        edits = self.get_edits()
        result = []
        for a in original_analyses:
            pn = str(a.get("page_number", ""))
            result.append(edits[pn] if pn in edits else a)
        return result

    def summary(self) -> dict:
        """Quick stats for the UI."""
        annotations = self.get_annotations()
        edits = self.get_edits()
        total_ann = sum(len(v) for v in annotations.values())
        return {
            "annotation_count": total_ann,
            "edited_pages": list(edits.keys()),
            "annotated_pages": [k for k, v in annotations.items() if v],
        }