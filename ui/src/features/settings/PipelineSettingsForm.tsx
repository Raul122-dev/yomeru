import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { getFormats, getLanguages, type LanguageOption } from "../../lib/api";
import type { PipelineSettings, SeparateTranslation } from "../../lib/types";
import { Input, Select } from "../../components/ui/input";
import { Switch } from "../../components/ui/Switch";
import { Slider } from "../../components/ui/Slider";
import { ModelPicker } from "./ModelPicker";
import { FontStylesField } from "./FontStylesField";
import { BackendPicker } from "./BackendPicker";
import { LocalModelPanel } from "./LocalModelPanel";

/** Editor for a full PipelineSettings — used for global settings and presets. */
export function PipelineSettingsForm({
  value,
  onChange,
}: {
  value: PipelineSettings;
  onChange: (v: PipelineSettings) => void;
}) {
  const { data: formats = [] } = useQuery({ queryKey: ["formats"], queryFn: getFormats });
  const { data: languages = [] } = useQuery({ queryKey: ["languages"], queryFn: getLanguages, staleTime: Infinity });
  const sources = withCurrent(languages, value.language.source, "unknown");
  const targets = withCurrent(
    languages.filter((l) => l.name !== "auto" && l.has_font), value.language.target, "no font",
  );
  const set = <K extends keyof PipelineSettings>(k: K, patch: Partial<PipelineSettings[K]>) =>
    onChange({ ...value, [k]: { ...value[k], ...patch } });
  const analysis = value.analysis ?? { backend: "vlm", options: {} };
  const sep: SeparateTranslation = {
    enabled: false, local: false, local_model: "auto", local_server: "http://127.0.0.1:11434",
    ...analysis.separate_translation,
  };
  const setSep = (patch: Partial<SeparateTranslation>) =>
    onChange({ ...value, analysis: { ...analysis, separate_translation: { ...sep, ...patch } } });

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Models</h3>
        <BackendPicker
          phase="analysis"
          label="Read & translate technique"
          value={value.analysis ?? { backend: "vlm", options: {} }}
          onChange={(v) => onChange({ ...value, analysis: { ...analysis, ...v } })}
        />
        {value.analysis?.backend === "local" && (
          <LocalModelPanel
            server={value.analysis.options?.server as string | undefined}
            model={value.analysis.options?.model as string | undefined}
          />
        )}
        {value.analysis?.backend !== "local" && <ModelPicker
          label="Vision model"
          hint="Reads each page and translates. Must accept images."
          value={value.analysis_model}
          onChange={(m) => onChange({ ...value, analysis_model: m })}
          requireVision
        />}
        <Switch
          label="Separate reading and translation"
          hint="Off: one model reads and translates each page (default). On: the vision model only reads and notes the context (who speaks to whom, tone, intent, how each character talks); a text model then translates the whole chapter with a style guide and glossary. Helps smaller/local models; an extra model call."
          checked={!!sep.enabled}
          onCheckedChange={(on) => setSep({ enabled: on })}
        />
        {sep.enabled && (
          <div className="ml-1 flex flex-col gap-3 border-l border-[hsl(var(--border))] pl-4">
            <Select
              label="Translation model"
              value={sep.local ? "local" : "api"}
              onChange={(e) => setSep({ local: e.target.value === "local" })}
            >
              <option value="api">API (a connection)</option>
              <option value="local">Local (experimental)</option>
            </Select>
            {sep.local ? (
              <>
                <div className="flex flex-wrap gap-3">
                  <Input
                    label="Local model"
                    hint="'auto' picks one for your GPU; or an Ollama tag (e.g. qwen3.5:9b)"
                    value={sep.local_model}
                    onChange={(e) => setSep({ local_model: e.target.value || "auto" })}
                  />
                  <Input
                    label="Server"
                    value={sep.local_server}
                    onChange={(e) => setSep({ local_server: e.target.value })}
                  />
                </div>
                <LocalModelPanel server={sep.local_server} model={sep.local_model} />
              </>
            ) : (
              <ModelPicker
                label="Text model"
                hint="Translates the whole chapter from what the vision model read. Any chat model works; it doesn't need vision."
                value={value.translation_model}
                onChange={(m) => onChange({ ...value, translation_model: m })}
              />
            )}
            {!sep.local && !(value.translation_model.connection_id && value.translation_model.model) && (
              <p className="text-xs text-[hsl(var(--warning))]">Pick a text model — runs won't start without one.</p>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Language</h3>
        <div className="flex items-center gap-2">
          <Select label="Source" value={value.language.source} onChange={(e) => set("language", { source: e.target.value })}>
            {sources.map((l) => (
              <option key={l.name} value={l.name}>{l.label}</option>
            ))}
          </Select>
          <ArrowRight size={16} className="mt-5 shrink-0 text-[hsl(var(--text-muted))]" />
          <Select label="Target" value={value.language.target} onChange={(e) => set("language", { target: e.target.value })}>
            {targets.map((l) => (
              <option key={l.name} value={l.name}>{l.label}</option>
            ))}
          </Select>
        </div>
        <Select
          label="Format"
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
          label="Confidence threshold"
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
          label="Matching technique"
          value={value.matching}
          onChange={(v) => onChange({ ...value, matching: v })}
        />

      </section>

      <section className="flex flex-col gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Inpainting & rendering</h3>
        <BackendPicker
          phase="inpainting"
          label="Inpainting technique"
          value={value.inpainting}
          onChange={(v) => onChange({ ...value, inpainting: v })}
        />
        <BackendPicker
          phase="rendering"
          label="Rendering technique"
          value={value.rendering}
          onChange={(v) => onChange({ ...value, rendering: { ...value.rendering, ...v } })}
        />
        <Switch
          label="Render translated text"
          hint="Off renders the original text (useful to check the layout)"
          checked={value.rendering.use_translation}
          onCheckedChange={(v) => set("rendering", { use_translation: v })}
        />
        <FontStylesField value={value.rendering.fonts} onChange={(fonts) => set("rendering", { fonts })} />
      </section>
    </div>
  );
}

/** Keep a saved value the list no longer offers visible instead of blank. */
function withCurrent(list: LanguageOption[], current: string, why: string) {
  if (!current || list.length === 0 || list.some((l) => l.name === current)) return list;
  return [...list, { name: current, label: `${current} (${why})`, code: "", script: "", has_font: false }];
}
