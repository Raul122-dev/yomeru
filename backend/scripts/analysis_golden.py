"""Analysis golden: what the analysis phase SENDS to the model and what it SAVES,
with a fake model (no API calls, no cost).

The fake model answers each page with that page's frozen analysis from the
golden runs, so parsing, context carry-over and saving are exercised too.

    python scripts/analysis_golden.py capture   # freeze current behaviour
    python scripts/analysis_golden.py check     # compare against it
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root (data/ lives here)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

RUNS = ("d4c17c9bf8f5", "496bb1f8a2aa", "zz_e2e_test")
OUT = ROOT / "data" / "goldens" / "_analysis.json"


def _exec(run_id: str, work: Path) -> dict:
    import golden
    import yomeru.core.llm as llm
    import yomeru.core.runs as runs
    from yomeru.api.routes.phases import _phase_options
    from yomeru.phases.analysis import run as analysis

    src = golden.golden_dir() / run_id / "input"
    golden._copy_inputs(src, work / "runs" / run_id)
    frozen = {a["page_number"]: a for a in json.loads((src / "output" / "page_analyses.json").read_text())}
    calls: list[dict] = []

    class RM:
        label = "fake · model"

    def fake_stream(rm, system, text, b64, mime, on_token=None):
        page = len(calls) + 1
        calls.append({"system_sha": hashlib.sha256(system.encode()).hexdigest()[:16],
                      "user_text": text,
                      "image_sha": hashlib.sha256(b64.encode()).hexdigest()[:16], "mime": mime})
        reply = {k: v for k, v in frozen[page].items()
                 if k not in ("page_number", "analysis_image_w", "analysis_image_h", "source_language")}
        return json.dumps(reply, ensure_ascii=False)

    saved = (llm.stream_vision, llm.resolve_model, runs.RUNS_DIR)
    llm.stream_vision, llm.resolve_model, runs.RUNS_DIR = fake_stream, (lambda ref: RM()), work / "runs"
    try:
        run = runs.Run.load(run_id)
        opts = _phase_options(run, "analysis")
        res = analysis(run, opts)
        out_dir = work / "runs" / run_id / "output"
        return {
            "status": res.status,
            "calls": calls,
            "page_analyses": json.loads((out_dir / "page_analyses.json").read_text()),
            "context": json.loads((out_dir / "context.json").read_text()),
        }
    finally:
        llm.stream_vision, llm.resolve_model, runs.RUNS_DIR = saved


def collect() -> dict:
    import golden
    golden._deterministic()
    data_dir = golden._paths().DATA_DIR
    out = {}
    for rid in RUNS:
        with tempfile.TemporaryDirectory(dir=data_dir) as t:
            out[rid] = _exec(rid, Path(t))
    return out


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    got = collect()
    if cmd == "capture":
        OUT.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True))
        print(f"captured analysis golden: {', '.join(f'{k}={len(v['calls'])} calls' for k, v in got.items())}")
        return 0
    want = json.loads(OUT.read_text())
    got = json.loads(json.dumps(got, ensure_ascii=False, sort_keys=True))
    bad = []
    for rid in RUNS:
        for key in ("status", "calls", "page_analyses", "context"):
            if got[rid][key] != want[rid][key]:
                bad.append(f"{rid}: {key} differs")
    if bad:
        print("ANALYSIS GOLDEN FAILURES:\n- " + "\n- ".join(bad))
        return 1
    print(f"analysis golden identical ({len(RUNS)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
