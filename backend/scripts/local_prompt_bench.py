"""Bench of the local analysis prompt: same pages, prompt variants, compared
with the frozen Gemini analyses (reference) on what matters downstream.

    python scripts/local_prompt_bench.py full compact      # prompt variants
    python scripts/local_prompt_bench.py --out DIR full     # results dir (default data/prompt_bench)
Metrics per page: dialogues, ★ text regions covered, region ids that disagree
with OCR of the claimed box, false skips, seconds; plus every translation next
to Gemini's for review.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root (data/ lives here)
sys.path.insert(0, str(ROOT / "backend"))

CASES = [("data/goldens/d4c17c9bf8f5/input", (1, 2, 3), "manga"),
         ("data/goldens/zz_e2e_test/input", (2, 3), "manga")]
OUT = ROOT / "data" / "prompt_bench"


def run_variant(variant: str, model: str = "qwen3.5:9b") -> dict:
    import glob
    from PIL import Image
    from yomeru.stages.analysis import analyzer
    from yomeru.stages.analysis.analyzer import parse_reply, prepare
    from yomeru.pipeline.contracts import AnalysisRequest
    from yomeru.config.labels import is_text
    from yomeru.stages.analysis.local_models import chat_vision
    from yomeru.stages.matching.cascade import _text_containment_score
    from yomeru.stages.matching.ocr import ocr_region
    from yomeru.stages.analysis.plugins import _reply_schema

    res = {}
    if True:
        for src, pages, fmt in CASES:
            src = ROOT / src
            files = sorted(glob.glob(str(src / "pages" / "*")))
            dets = {e["page_number"]: e["regions"] for e in json.loads((src / "output/page_detections.json").read_text())}
            gem = {a["page_number"]: a for a in json.loads((src / "output/page_analyses.json").read_text())}
            for pn in pages:
                img = Image.open(files[pn - 1]).convert("RGB")
                req = AnalysisRequest(image=img, page_number=pn, regions=dets[pn], comic_format=fmt,
                                      source_language="auto", target_language="Spanish")
                p = prepare(req) if variant == "full" else prepare(req, system=analyzer._load(f"system_{variant}.md"))
                t = time.time()
                raw = chat_vision(model, p.system, p.user_text, p.image_b64, schema=_reply_schema(), num_ctx=16384)
                dt = time.time() - t
                a = parse_reply(raw, req, model)
                regs = {r["id"]: r for r in dets[pn]}
                text_regs = {k for k, r in regs.items() if is_text(r.get("label"))}
                covered = {d.region_id for d in a.dialogues if d.region_id in text_regs}
                wrong = 0
                for d in a.dialogues:
                    r = regs.get(d.region_id)
                    if r is None or not is_text(r.get("label")) or not d.text:
                        continue
                    o = (ocr_region(img, (r["x1"], r["y1"], r["x2"], r["y2"]), "auto") or "").strip()
                    if len(o) >= 4 and _text_containment_score(o, d.text) < 0.3:
                        wrong += 1
                g = {d.get("region_id"): d for d in gem[pn]["dialogues"]}
                key = f"{src.parent.name[:8]}/p{pn}"
                res[key] = {
                    "secs": round(dt, 1), "dialogues": len(a.dialogues), "text_regions": len(text_regs),
                    "covered": len(covered), "ocr_disagree": wrong,
                    "skipped": sum(d.skip for d in a.dialogues),
                    "pairs": [(d.region_id, d.text, d.text_translated, d.skip,
                               (g.get(d.region_id) or {}).get("text_translated")) for d in a.dialogues],
                }
                print(f"{variant} {key}: {res[key]['secs']}s dlg {res[key]['dialogues']} "
                      f"cov {res[key]['covered']}/{res[key]['text_regions']} ocr✗ {wrong} skip {res[key]['skipped']}",
                      file=sys.stderr)
    return res


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--out"]:
        OUT, args = Path(args[1]), args[2:]
    OUT.mkdir(parents=True, exist_ok=True)
    for v in args or ["full", "compact"]:
        (OUT / f"{v}.json").write_text(json.dumps(run_variant(v), ensure_ascii=False, indent=1))
