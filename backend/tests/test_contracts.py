"""Phase contracts round-trip real data unchanged."""
import json
from pathlib import Path

import pytest

from yomeru.core.contracts import PageDetections

GOLDENS = Path(__file__).resolve().parents[2] / "data" / "goldens"
RUNS = Path(__file__).resolve().parents[2] / "data" / "runs"


def _detection_files():
    files = sorted(GOLDENS.glob("*/input/output/page_detections*.json"))
    files += sorted(RUNS.glob("*/output/page_detections*.json"))[:40]
    return files


@pytest.mark.parametrize("path", _detection_files(), ids=lambda p: p.parts[-4])
def test_page_detections_round_trip(path):
    raw = json.loads(path.read_text())
    for entry in raw:
        assert PageDetections.model_validate(entry).model_dump() == entry


def test_unknown_label_is_rejected():
    with pytest.raises(Exception):
        PageDetections.model_validate({"page_number": 1, "original_w": 10, "original_h": 10, "regions": [
            {"id": 1, "x1": 0, "y1": 0, "x2": 5, "y2": 5, "label": "sfx", "score": 0.9}]})
