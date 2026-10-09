import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { getFormats } from "../../lib/api";
import type { PipelineSettings } from "../../lib/types";
import { SOURCE_LANGUAGES, TARGET_LANGUAGES } from "../../lib/languages";
import { Select } from "../../components/ui/input";
import { Switch } from "../../components/ui/Switch";
import { Slider } from "../../components/ui/Slider";
import { ModelPicker } from "./ModelPicker";

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

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Models</h3>
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
        <Select
          label="detector"
          value={value.detection.backend}
          onChange={(e) => set("detection", { backend: e.target.value as PipelineSettings["detection"]["backend"] })}
        >
          <option value="auto">Auto (CTD if downloaded, else ogkalu)</option>
          <option value="ogkalu">ogkalu RT-DETR — speech bubbles</option>
          <option value="ctd">CTD — text blocks with pixel masks</option>
        </Select>
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
        <Slider label="OCR weight" value={value.matching.ocr_weight} min={0} max={1} step={0.05}
          hint="How much the text read by OCR counts" onChange={(v) => set("matching", { ocr_weight: v })} />
        <Slider label="spatial weight" value={value.matching.spatial_weight} min={0} max={1} step={0.05}
          hint="How much the box position counts" onChange={(v) => set("matching", { spatial_weight: v })} />
        <Slider label="reading-order weight" value={value.matching.position_weight} min={0} max={1} step={0.05}
          onChange={(v) => set("matching", { position_weight: v })} />
        <Slider label="minimum score" value={value.matching.min_score} min={0} max={0.5} step={0.01}
          hint="Matches below this are discarded" onChange={(v) => set("matching", { min_score: v })} />
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Inpainting & rendering</h3>
        <Select
          label="inpainting"
          value={value.inpainting.backend}
          onChange={(e) => set("inpainting", { backend: e.target.value as PipelineSettings["inpainting"]["backend"] })}
        >
          <option value="auto">Auto (OpenCV for bubbles, LaMa for free text)</option>
          <option value="lama">LaMa</option>
          <option value="opencv">OpenCV only (fast)</option>
        </Select>
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
