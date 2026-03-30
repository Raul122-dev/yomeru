/**
 * StageInfo — collapsible panel showing what each pipeline stage does,
 * its inputs, outputs, and what backend was used.
 */
import { useState } from "react";
import { Info, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";

export interface StageSpec {
  name: string;
  description: string;
  inputs: { field: string; type: string; desc: string }[];
  outputs: { field: string; type: string; desc: string }[];
  backend?: string;
  backendNote?: string;
}

const STAGE_SPECS: Record<string, StageSpec> = {
  s2_detection: {
    name: "Detection",
    description:
      "Locates all text-containing regions in the page image. Runs during the analysis phase and saves results to page_detections.json — typesetting reuses these saved detections without re-running the detector.",
    inputs: [
      { field: "image", type: "PIL.Image", desc: "Full page image" },
      {
        field: "threshold",
        type: "float",
        desc: "Confidence threshold (0–1). Lower = more regions.",
      },
    ],
    outputs: [
      {
        field: "regions",
        type: "list[TextRegion]",
        desc: "Bounding boxes (x1,y1,x2,y2), label, score, optional pixel mask",
      },
      {
        field: "page_detections.json",
        type: "file",
        desc: "Persisted per-page detection results reused during typesetting",
      },
    ],
  },
  s3_matching: {
    name: "Matching",
    description:
      "Assigns each dialogue entry from the VLM analysis to its corresponding detected region. Primary path: direct lookup by region_id (the number the VLM saw on the annotated image). Fallback: Hungarian algorithm optimizing a score matrix of spatial overlap + OCR text similarity + position zone.",
    inputs: [
      {
        field: "dialogues",
        type: "list[dict]",
        desc: "VLM-parsed dialogue entries (with region_id, bbox, text, text_position)",
      },
      {
        field: "saved_detections",
        type: "dict[int, region]",
        desc: "Regions from page_detections.json, indexed by id",
      },
      {
        field: "image",
        type: "PIL.Image",
        desc: "Used for OCR scoring in fallback matching only",
      },
    ],
    outputs: [
      {
        field: "matches",
        type: "dict[int, MatchResult]",
        desc: "dialogue_index → region, with spatial/text/position scores",
      },
    ],
  },
  s4_inpainted: {
    name: "Inpainting",
    description:
      "Erases source text from the page, leaving clean background for re-typesetting. Builds a combined binary mask across all matched regions using Otsu thresholding, then fills masked pixels with reconstructed background.",
    inputs: [
      { field: "image", type: "PIL.Image", desc: "Original page image" },
      {
        field: "mask",
        type: "np.ndarray uint8",
        desc: "Combined binary mask (255 = erase, 0 = keep), same HxW as image",
      },
    ],
    outputs: [
      {
        field: "inpainted",
        type: "PIL.Image",
        desc: "Page with text pixels filled. Same size as input.",
      },
    ],
  },
  s5_final: {
    name: "Rendering",
    description:
      "Draws translated text into each clean bubble. Font size scales down to fit. Embedded \\n in text_translated are used as semantic break hints; pyphen handles syllabic hyphenation for any remaining long words. Vertical text mode activates automatically for narrow tall bubbles (Japanese).",
    inputs: [
      {
        field: "inpainted",
        type: "PIL.Image",
        desc: "Clean page from the inpainting stage",
      },
      {
        field: "text",
        type: "str",
        desc: "Translated text (may contain \\n for semantic breaks)",
      },
      {
        field: "bbox",
        type: "tuple[int,int,int,int]",
        desc: "Bubble bounding box in pixel coords",
      },
      {
        field: "tone / bubble_type / font_style",
        type: "str",
        desc: "Determines font weight, size range, and text color",
      },
    ],
    outputs: [
      {
        field: "result",
        type: "PIL.Image",
        desc: "Final typeset page with text drawn",
      },
      {
        field: "RenderResult",
        type: "dataclass",
        desc: "status, lines, font_size, font_style, line_source, skip_reason",
      },
    ],
  },
};

interface StageInfoProps {
  stageKey: string;
  backend?: string;
}

export function StageInfo({ stageKey, backend }: StageInfoProps) {
  const [open, setOpen] = useState(false);
  const spec = STAGE_SPECS[stageKey];
  if (!spec) return null;

  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-[9px] text-[hsl(var(--text-muted)/.7)] hover:text-[hsl(var(--accent2))] transition-colors"
      >
        <Info size={9} />
        {open ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
        what this stage does
      </button>

      {open && (
        <div className="mt-1.5 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] p-2.5 text-[10px] space-y-2.5">
          <p className="text-[hsl(var(--text))] leading-relaxed">
            {spec.description}
          </p>

          {backend && (
            <div className="flex items-center gap-1.5">
              <span className="text-[hsl(var(--text-muted))]">backend:</span>
              <code className="font-mono text-[hsl(var(--accent2))] bg-[hsl(var(--bg))] px-1 rounded">
                {backend}
              </code>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="mb-1 font-medium uppercase tracking-widest text-[9px] text-[hsl(var(--text-muted))]">
                inputs
              </p>
              <div className="space-y-1">
                {spec.inputs.map((inp) => (
                  <div key={inp.field}>
                    <code className="font-mono text-[hsl(var(--accent2))]">
                      {inp.field}
                    </code>
                    <span className="text-[hsl(var(--text-muted))] ml-1">
                      ({inp.type})
                    </span>
                    <p className="text-[hsl(var(--text-muted))] leading-snug">
                      {inp.desc}
                    </p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-1 font-medium uppercase tracking-widest text-[9px] text-[hsl(var(--text-muted))]">
                outputs
              </p>
              <div className="space-y-1">
                {spec.outputs.map((out) => (
                  <div key={out.field}>
                    <code className="font-mono text-[hsl(var(--success))]">
                      {out.field}
                    </code>
                    <span className="text-[hsl(var(--text-muted))] ml-1">
                      ({out.type})
                    </span>
                    <p className="text-[hsl(var(--text-muted))] leading-snug">
                      {out.desc}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
