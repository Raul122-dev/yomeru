"""
Golden harness for behaviour-preserving refactors.

Freezes real runs and checks that matching, inpainting and rendering (and
detection) produce exactly the same outputs after a change.

    uv run python scripts/golden.py capture <run_id> [<run_id> ...]   # freeze
    uv run python scripts/golden.py check                              # compare

Goldens live in data/goldens/<run_id>/ (data/ is gitignored: real manga pages
must not be committed):
    input/            pages + meta.json + page_detections.json + page_analyses.json
                      + any user edit files (refined/edits/overrides/masks)
    expected/         detections.json, matches.json, inpaint/pNN.npy, render/pNN.npy
                      (decoded pixels of the phase outputs, not JPEG bytes)

`check` copies input/ into a throwaway run, runs the phases there (analysis is
frozen — no model calls) and compares. Exit code 1 on any difference.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]          # repo root (data/ lives here)
sys.path.insert(0, str(ROOT / "backend"))

EDIT_FILES = ["page_detections_refined.json", "edits.json"]
DEBUG_EDIT_GLOBS = ["p*_matches_refined.json", "p*_mask_refined.png", "p*_render_overrides.json"]


def _deterministic() -> None:
    """LaMa on CUDA picks cuDNN kernels per run (autotune / TF32), which flips a
    few pixels by ±4–6 between processes. Goldens need bit-exact repeats."""
    try:
        import torch
    except ImportError:
        return
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    # TorchScript (big-lama.pt) runs the first calls of a process through the
    # profiling executor and switches to a fused graph afterwards: page 1 then
    # differs from later pages by a few levels. One fixed path for every call.
    torch._C._jit_set_profiling_executor(False)
    torch._C._jit_set_profiling_mode(False)


def _paths():
    import yomeru.core.paths as paths
    return paths


def golden_dir() -> Path:
    return _paths().DATA_DIR / "goldens"


def _copy_inputs(src_run: Path, dst: Path) -> None:
    (dst / "output" / "typeset" / "debug").mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_run / "pages", dst / "pages", dirs_exist_ok=True)
    shutil.copy2(src_run / "meta.json", dst / "meta.json")
    for name in ["page_detections.json", "page_analyses.json", "context.json", *EDIT_FILES]:
        if (src_run / "output" / name).exists():
            shutil.copy2(src_run / "output" / name, dst / "output" / name)
    for pat in DEBUG_EDIT_GLOBS:
        for f in (src_run / "output" / "typeset" / "debug").glob(pat):
            shutil.copy2(f, dst / "output" / "typeset" / "debug" / f.name)


def _px(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def _execute(work: Path, run_id: str) -> dict:
    """Run detection→rendering (analysis frozen) inside `work` as data dir."""
    import yomeru.core.runs as runs
    runs_dir = work / "runs"
    run_dir = runs_dir / run_id
    original_runs_dir = runs.RUNS_DIR
    runs.RUNS_DIR = runs_dir
    try:
        run = runs.Run.load(run_id)
        assert run is not None, f"cannot load {run_id}"
        # Phase functions are called directly (not through the runner): the
        # runner's dependency/stale bookkeeping is not what goldens protect.
        from yomeru.phases.runner import _get_phase_fn
        from yomeru.api.routes.phases import _phase_options

        def go(phase: str):
            res = _get_phase_fn(phase)(run, _phase_options(run, phase))
            assert res.status == "done", f"{phase}: {res.status} {res.error}"
            return res

        # Detection runs, but the frozen detections stay the pipeline input
        # (the frozen analysis' region_ids refer to them).
        frozen_det = (run_dir / "output" / "page_detections.json").read_text()
        go("detection")
        detected = json.loads((run_dir / "output" / "page_detections.json").read_text())
        (run_dir / "output" / "page_detections.json").write_text(frozen_det)

        out: dict = {"detections": detected}
        for phase in ("matching", "inpainting", "rendering"):
            go(phase)
        dbg = run_dir / "output" / "typeset" / "debug"
        out["matches"] = {}
        out["inpaint"] = {}
        out["render"] = {}
        for log in sorted(dbg.glob("p*_render_log.json")):
            p = log.name[1:3]
            data = json.loads(log.read_text())
            # Assignment set (order of the log list is not behaviour)
            out["matches"][p] = sorted(
                [m["dialogue_index"], m["region_id"], m["match_type"]] for m in data["s3_matching"]["matches"]
            )
            out["inpaint"][p] = _px(dbg / f"p{p}_s4_inpainted.png")
            out["render"][p] = _px(dbg / f"p{p}_scanline_production.png")
        return out
    finally:
        runs.RUNS_DIR = original_runs_dir


def _strip_scores(dets: list[dict]) -> list:
    # boxes + labels + ids must match exactly; scores to 3 decimals (GPU float noise)
    return [
        (p["page_number"], [(r["id"], r["label"], r["x1"], r["y1"], r["x2"], r["y2"], round(r["score"], 3))
                            for r in p["regions"]])
        for p in sorted(dets, key=lambda d: d["page_number"])
    ]


def capture(run_ids: list[str]) -> None:
    paths = _paths()
    for rid in run_ids:
        src = paths.DATA_DIR / "runs" / rid
        g = golden_dir() / rid
        if g.exists():
            shutil.rmtree(g)
        _copy_inputs(src, g / "input")
        with tempfile.TemporaryDirectory(dir=paths.DATA_DIR) as tmp:
            work = Path(tmp)
            _copy_inputs(g / "input", work / "runs" / rid)
            out = _execute(work, rid)
        exp = g / "expected"
        (exp / "inpaint").mkdir(parents=True)
        (exp / "render").mkdir()
        (exp / "detections.json").write_text(json.dumps(_strip_scores(out["detections"])))
        (exp / "matches.json").write_text(json.dumps(out["matches"]))
        for p, a in out["inpaint"].items():
            np.save(exp / "inpaint" / f"p{p}.npy", a)
        for p, a in out["render"].items():
            np.save(exp / "render" / f"p{p}.npy", a)
        print(f"captured {rid}: {len(out['matches'])} pages")


def check() -> int:
    paths = _paths()
    failures: list[str] = []
    goldens = sorted(d for d in golden_dir().iterdir() if d.is_dir()) if golden_dir().exists() else []
    if not goldens:
        print("no goldens — run `capture` first")
        return 1
    for g in goldens:
        rid = g.name
        with tempfile.TemporaryDirectory(dir=paths.DATA_DIR) as tmp:
            work = Path(tmp)
            _copy_inputs(g / "input", work / "runs" / rid)
            out = _execute(work, rid)
        exp = g / "expected"
        if json.loads(json.dumps(_strip_scores(out["detections"]))) != json.loads((exp / "detections.json").read_text()):
            failures.append(f"{rid}: detections differ")
        exp_matches = {k: sorted(v) for k, v in json.loads((exp / "matches.json").read_text()).items()}
        got_matches = json.loads(json.dumps(out["matches"]))
        if got_matches != exp_matches:
            failures.append(f"{rid}: matches differ\n   expected {exp_matches}\n   got      {got_matches}")
        for kind in ("inpaint", "render"):
            for f in sorted((exp / kind).glob("p*.npy")):
                p = f.stem[1:]
                want = np.load(f)
                got = out[kind].get(p)
                if got is None:
                    failures.append(f"{rid}: {kind} p{p} missing")
                elif got.shape != want.shape:
                    failures.append(f"{rid}: {kind} p{p} shape {got.shape} != {want.shape}")
                else:
                    d = int(np.abs(got.astype(int) - want.astype(int)).max())
                    if d:
                        n = int((np.abs(got.astype(int) - want.astype(int)).max(axis=2) > 0).sum())
                        failures.append(f"{rid}: {kind} p{p} max diff {d} ({n} px)")
        print(f"checked {rid}")
    if failures:
        print("\nGOLDEN FAILURES:\n- " + "\n- ".join(failures))
        return 1
    print(f"\nall goldens identical ({len(goldens)} runs)")
    return 0


if __name__ == "__main__":
    _deterministic()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "capture":
        capture(sys.argv[2:])
    elif cmd == "check":
        sys.exit(check())
    else:
        print(__doc__)
        sys.exit(2)
