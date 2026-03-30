import { Switch } from "../ui/Switch";
import { Slider } from "../ui/Slider";
import { cn } from "../../lib/utils";

export interface TypesetOpts {
  useTranslation: boolean;
  skipSfx: boolean;
  skipNarration: boolean;
  maxFontSize: number;
  detectorBackend: string;
  detectorThreshold: number;
  inpainterBackend: string;
  ocrWeight: number;
  spatialWeight: number;
  positionWeight: number;
  matchMinScore: number;
}

interface TypesetOptionsProps {
  opts: TypesetOpts;
  detectors: { key: string; label: string }[];
  onChange: (patch: Partial<TypesetOpts>) => void;
}

export function TypesetOptionsPanel({
  opts,
  detectors,
  onChange,
}: TypesetOptionsProps) {
  return (
    <div className="space-y-4 text-xs">
      <section>
        <p className="mb-2 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
          render
        </p>
        <div className="rounded-md border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))]">
          <div className="px-3">
            <Switch
              label="use translation"
              hint="render translated text; off = render original"
              checked={opts.useTranslation}
              onCheckedChange={(v) => onChange({ useTranslation: v })}
            />
          </div>
          <div className="px-3">
            <Switch
              label="skip SFX"
              checked={opts.skipSfx}
              onCheckedChange={(v) => onChange({ skipSfx: v })}
            />
          </div>
          <div className="px-3">
            <Switch
              label="skip narration"
              checked={opts.skipNarration}
              onCheckedChange={(v) => onChange({ skipNarration: v })}
            />
          </div>
        </div>
        <div className="mt-3">
          <Slider
            label="max font size"
            value={opts.maxFontSize}
            min={12}
            max={48}
            step={1}
            format={(v) => `${v}px`}
            hint="scales down to fit; set higher for larger bubbles"
            onChange={(v) => onChange({ maxFontSize: v })}
          />
        </div>
      </section>

      <section>
        <p className="mb-2 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
          inpainter
        </p>
        <div className="flex flex-wrap gap-1.5 mb-1">
          {[
            { key: "auto", label: "auto" },
            { key: "lama", label: "LaMa" },
            { key: "opencv", label: "OpenCV" },
          ].map((d) => (
            <button
              key={d.key}
              onClick={() => onChange({ inpainterBackend: d.key })}
              className={cn(
                "rounded border px-2.5 py-0.5 text-[11px] transition-colors",
                opts.inpainterBackend === d.key
                  ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.06)]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
              )}
            >
              {d.label}
            </button>
          ))}
        </div>
        <p className="text-[9px] text-[hsl(var(--text-muted))]">
          LaMa: best quality, needs big-lama.pt · OpenCV: always available,
          faster
        </p>
      </section>

      <section>
        <div className="flex flex-wrap gap-1.5 mb-3">
          {[{ key: "auto", label: "auto" }, ...detectors].map((d) => (
            <button
              key={d.key}
              onClick={() => onChange({ detectorBackend: d.key })}
              className={cn(
                "rounded border px-2.5 py-0.5 text-[11px] transition-colors",
                opts.detectorBackend === d.key
                  ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.06)]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
              )}
            >
              {d.label}
            </button>
          ))}
        </div>
        <Slider
          label="detection threshold"
          value={opts.detectorThreshold}
          min={0.2}
          max={0.9}
          step={0.05}
          hint="lower = more regions detected"
          onChange={(v) => onChange({ detectorThreshold: v })}
        />
      </section>

      <section>
        <p className="mb-2 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
          matching
          <span className="ml-1 normal-case font-normal opacity-60">
            (fallback only)
          </span>
        </p>
        <div className="space-y-2.5">
          <Slider
            label="spatial"
            value={opts.spatialWeight}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => onChange({ spatialWeight: v })}
          />
          <Slider
            label="OCR text"
            value={opts.ocrWeight}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => onChange({ ocrWeight: v })}
          />
          <Slider
            label="position zone"
            value={opts.positionWeight}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => onChange({ positionWeight: v })}
          />
          <Slider
            label="min score"
            value={opts.matchMinScore}
            min={0.01}
            max={0.3}
            step={0.01}
            hint="raise if seeing wrong matches"
            onChange={(v) => onChange({ matchMinScore: v })}
          />
        </div>
      </section>
    </div>
  );
}
