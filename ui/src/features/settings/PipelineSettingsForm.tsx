import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { getFormats } from "../../lib/api";
import type { PipelineSettings } from "../../lib/types";
import { SOURCE_LANGUAGES, TARGET_LANGUAGES } from "../../lib/languages";
import { Select } from "../../components/ui/input";
import { Switch } from "../../components/ui/Switch";
import { Slider } from "../../components/ui/Slider";
import { ModelPicker } from "./ModelPicker";
import { BackendPicker } from "./BackendPicker";

/** Editor for a full PipelineSettings — used for global settings and presets. */
export function PipelineSettingsForm({
  value,
  onChange,
}: {
  value: PipelineSettings;
  onChange: (v: PipelineSettings) => void;
}) {
  const { data: formats = [] } = useQuery({ queryKey: ["formats"], queryFn: getFormats });
  const set = <K extends keyof PipelineSettings>(k: K, patch: Partial<PipelineSettings[K]>) =>
    onChange({ ...value, [k]: { ...value[k], ...patch } });

  const matchOpt = (k: string, d: number) => Number(value.matching.options?.[k] ?? d);
  const setMatchOpt = (k: string, v: number) =>
    onChange({ ...value, matching: { ...value.matching, options: { ...value.matching.options, [k]: v } } });

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Models</h3>
        <BackendPicker
          phase="analysis"
          label="analysis technique"
          value={value.analysis ?? { backend: "vlm", options: {} }}
          onChange={(v) => onChange({ ...value, analysis: v })}
        />
        <ModelPicker
          label="analysis model"
          hint="Reads each page and translates. Must accept images."
          value={value.analysis_model}
          onChange={(m) => onChange({ ...value, analysis_model: m })}
          requireVision
        />
        <ModelPicker
          label="translation model (optional)"
          hint="A separate text model for the translation step. Leave empty to translate with the analysis model."
          value={value.translation_model}
          onChange={(m) => onChange({ ...value, translation_model: m })}
          allowNone
        />
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Language</h3>
        <div className="flex items-center gap-2">
          <Select label="source" value={value.language.source} onChange={(e) => set("language", { source: e.target.value })}>
            {SOURCE_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </Select>
          <ArrowRight size={16} className="mt-5 shrink-0 text-[hsl(var(--text-muted))]" />
          <Select label="target" value={value.language.target} onChange={(e) => set("language", { target: e.target.value })}>
            {TARGET_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </Select>
        </div>
        <Select
          label="format"
          value={value.language.comic_format}
          onChange={(e) => set("language", { comic_format: e.target.value })}
        >
          {formats.map((f) => (
            <option key={f.key} value={f.key}>{f.name}</option>
          ))}
        </Select>
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Detection</h3>
        <p className="text-xs text-[hsl(var(--text-muted))]">
          Detector: <span className="font-mono">ogkalu RT-DETR</span> — finds bubbles, text in bubbles and free text.
          Every later phase relies on these regions.
        </p>
        <Slider
          label="confidence threshold"
          value={value.detection.threshold}
          min={0.1}
          max={0.9}
          step={0.05}
          hint="Lower finds more regions, including false positives"
          onChange={(v) => set("detection", { threshold: v })}
        />
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Matching</h3>
        <BackendPicker
          phase="matching"
          label="matching"
          value={value.matching}
          onChange={(v) => onChange({ ...value, matching: v })}
        />
        {value.matching.backend === "cascade" && (
          <>
            <Slider label="OCR weight" value={matchOpt("ocr_weight", 0.4)} min={0} max={1} step={0.05}
              hint="How much the text read by OCR counts" onChange={(v) => setMatchOpt("ocr_weight", v)} />
            <Slider label="spatial weight" value={matchOpt("spatial_weight", 0.4)} min={0} max={1} step={0.05}
              hint="How much the box position counts" onChange={(v) => setMatchOpt("spatial_weight", v)} />
            <Slider label="minimum score" value={matchOpt("min_score", 0.05)} min={0} max={0.5} step={0.01}
              hint="Matches below this are discarded" onChange={(v) => setMatchOpt("min_score", v)} />
          </>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Inpainting & rendering</h3>
        <BackendPicker
          phase="inpainting"
          label="inpainting"
          value={value.inpainting}
          onChange={(v) => onChange({ ...value, inpainting: v })}
        />
        <BackendPicker
          phase="rendering"
          label="rendering"
          value={value.rendering}
          onChange={(v) => onChange({ ...value, rendering: { ...value.rendering, ...v } })}
        />
        <Switch
          label="Render translated text"
          hint="Off renders the original text (useful to check the layout)"
          checked={value.rendering.use_translation}
          onCheckedChange={(v) => set("rendering", { use_translation: v })}
        />
      </section>
    </div>
  );
}
