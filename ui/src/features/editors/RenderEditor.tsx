/**
 * RenderEditor — edit render parameters per dialogue and re-render individual regions.
 *
 * For each matched dialogue the user can:
 *  - Edit translated text
 *  - Override font_size, font_style, tone
 *  - Re-render a single region without re-running the whole pipeline
 *  - Mark a dialogue as "skip" (won't be rendered)
 *
 * Overrides saved to: typeset/debug/p{N:02}_render_overrides.json
 * Consumed by: stages/rendering/pil.py per-dialogue render
 */
import { useState, useCallback } from "react";
import {
  RefreshCw,
  Save,
  RotateCcw,
  Eye,
  EyeOff,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { useScopedPhaseRunner } from "../../hooks/useScopedPhaseRunner";
import type { RenderEvent, StageLog } from "../../lib/types";

// ── types ─────────────────────────────────────────────────────────────────────

export interface RenderOverride {
  dialogue_index: number;
  text_translated?: string;
  font_style?: string;
  font_size_override?: number | null;
  tone?: string;
  skip?: boolean;
}

interface DialogueRow {
  dialogue_index: number;
  region_id: number | null;
  text: string;
  text_translated: string;
  status: "ok" | "skip";
  skip_reason?: string;
  font_size?: number;
  font_style?: string;
  tone?: string;
  lines?: string[];
  bbox?: number[];
}

const FONT_STYLES = ["auto", "regular", "bold", "thought", "narration"];
const TONES = [
  "neutral",
  "shouting",
  "whispering",
  "laughing",
  "crying",
  "thinking",
];

// ── save overrides ─────────────────────────────────────────────────────────────

async function saveRenderOverrides(
  runId: string,
  pageNum: number,
  overrides: RenderOverride[],
) {
  const res = await fetch(`/api/runs/${runId}/typeset/renders/${pageNum}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ render_overrides: overrides }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── dialogue row ──────────────────────────────────────────────────────────────

function DialogueEditRow({
  row,
  override,
  onChange,
}: {
  row: DialogueRow;
  override: Partial<RenderOverride>;
  onChange: (fields: Partial<RenderOverride>) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isSkipped = override.skip ?? row.status === "skip";
  const displayText = override.text_translated ?? row.text_translated;
  const displayStyle = override.font_style ?? row.font_style ?? "auto";
  const displayTone = override.tone ?? row.tone ?? "neutral";

  return (
    <div
      className={cn(
        "border-b border-[hsl(var(--border))] last:border-0",
        isSkipped && "opacity-50",
      )}
    >
      {/* row header */}
      <div className="flex items-start gap-2 px-3 py-2">
        {/* status + region */}
        <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
          <span
            className={cn(
              "text-[10px] font-mono",
              isSkipped
                ? "text-[hsl(var(--text-muted)/.4)]"
                : "text-[hsl(var(--success))]",
            )}
          >
            {isSkipped ? "—" : "✓"}
          </span>
          <span className="font-mono text-[10px] text-[hsl(var(--accent2))] w-5">
            r{row.region_id}
          </span>
        </div>

        {/* translated text (editable) */}
        <textarea
          value={displayText}
          onChange={(e) => onChange({ text_translated: e.target.value })}
          rows={2}
          className="flex-1 min-w-0 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-1 text-[11px] leading-relaxed resize-none focus:border-[hsl(var(--accent2))] focus:outline-none"
        />

        {/* controls */}
        <div className="flex flex-col items-end gap-1 shrink-0">
          <button
            onClick={() => onChange({ skip: !isSkipped })}
            className="text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--text))] transition-colors"
            title={isSkipped ? "enable render" : "skip render"}
          >
            {isSkipped ? <EyeOff size={11} /> : <Eye size={11} />}
          </button>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--text))] transition-colors"
            title="style options"
          >
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>

      {/* original text + render info */}
      <div className="px-3 pb-1 flex gap-3 text-[10px] text-[hsl(var(--text-muted)/.6)]">
        <span className="truncate flex-1">{row.text}</span>
        {row.font_size && <span>{row.font_size}px</span>}
        {row.font_style && <span>{row.font_style}</span>}
        {row.lines && <span>{row.lines.length}L</span>}
      </div>

      {/* expanded style controls */}
      {expanded && (
        <div className="px-3 pb-2.5 pt-0 flex flex-wrap gap-3">
          {/* font style */}
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              style
            </p>
            <div className="flex gap-1">
              {FONT_STYLES.map((s) => (
                <button
                  key={s}
                  onClick={() =>
                    onChange({ font_style: s === "auto" ? undefined : s })
                  }
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[10px] transition-colors",
                    displayStyle === s || (s === "auto" && !override.font_style)
                      ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                      : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* tone */}
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              tone
            </p>
            <div className="flex flex-wrap gap-1">
              {TONES.map((t) => (
                <button
                  key={t}
                  onClick={() => onChange({ tone: t })}
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[10px] transition-colors",
                    displayTone === t
                      ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                      : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* font size override */}
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              size override
              {override.font_size_override && (
                <button
                  onClick={() => onChange({ font_size_override: null })}
                  className="ml-2 text-[hsl(var(--danger)/.6)]"
                >
                  ✕
                </button>
              )}
            </p>
            <input
              type="number"
              min={6}
              max={60}
              value={override.font_size_override ?? ""}
              placeholder={String(row.font_size ?? "auto")}
              onChange={(e) =>
                onChange({
                  font_size_override: e.target.value
                    ? parseInt(e.target.value)
                    : null,
                })
              }
              className="w-16 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-0.5 text-[11px] font-mono focus:border-[hsl(var(--accent2))] focus:outline-none"
            />
          </div>

          {/* reset override for this row */}
          {Object.keys(override).length > 0 && (
            <div className="self-end">
              <button
                onClick={() => onChange({})}
                className="text-[10px] text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--danger))] transition-colors"
              >
                reset this
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

interface RenderEditorProps {
  runId: string;
  pageNum: number;
  stageLog: StageLog;
  onReRendered?: () => void;
}

export function RenderEditor({
  runId,
  pageNum,
  stageLog,
  onReRendered,
}: RenderEditorProps) {
  const renders = stageLog.s5_rendering?.renders ?? [];
  const matches = stageLog.s3_matching?.matches ?? [];

  // Build dialogue rows from stage log
  const rows: DialogueRow[] = renders.map((r: RenderEvent) => {
    const match = matches.find((m) => m.dialogue_index === r.dialogue_index);
    return {
      dialogue_index: r.dialogue_index,
      region_id: r.region_id ?? match?.region_id ?? null,
      text: r.text ?? "",
      text_translated: r.text ?? "",
      status: r.status ?? "ok",
      skip_reason: r.skip_reason,
      font_size: r.font_size,
      font_style: r.font_style,
      tone: r.tone,
      lines: r.lines,
      bbox: r.bbox,
    };
  });

  // Per-dialogue overrides: { [dialogue_index]: Partial<RenderOverride> }
  const [overrides, setOverrides] = useState<
    Record<number, Partial<RenderOverride>>
  >({});
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { progress: rerunProgress, start: startRerun } = useScopedPhaseRunner({
    runId,
    phase: "rendering",
    onComplete: () => {
      setIsDirty(false);
      onReRendered?.();
    },
    onError: (msg) => setError(msg),
  });
  const isReRendering = rerunProgress.status === "running";

  const updateOverride = (idx: number, fields: Partial<RenderOverride>) => {
    setOverrides((prev) => ({
      ...prev,
      [idx]:
        Object.keys(fields).length === 0
          ? {} // reset
          : { ...(prev[idx] ?? {}), ...fields },
    }));
    setIsDirty(true);
  };

  const buildOverrideList = useCallback((): RenderOverride[] =>
    Object.entries(overrides)
      .filter(([, v]) => Object.keys(v).length > 0)
      .map(([k, v]) => ({ dialogue_index: parseInt(k), ...v })),
    [overrides],
  );

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await saveRenderOverrides(runId, pageNum, buildOverrideList());
      setIsDirty(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  };

  const handleReRender = async () => {
    setError(null);
    try {
      // Always save overrides before re-rendering
      if (isDirty) {
        await saveRenderOverrides(runId, pageNum, buildOverrideList());
      }
      await startRerun([pageNum]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRevert = () => {
    setOverrides({});
    setIsDirty(false);
    setError(null);
  };

  if (rows.length === 0) {
    return (
      <div className="rounded border border-[hsl(var(--border))] px-4 py-6 text-center text-xs text-[hsl(var(--text-muted))]">
        no render data for p{pageNum} — run typesetting first
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
      {/* toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
        <span className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
          render editor · p{pageNum}
        </span>
        {isDirty && (
          <span className="text-[9px] text-[hsl(var(--accent2))]">
            unsaved changes
          </span>
        )}
        {error && (
          <span className="text-[10px] text-[hsl(var(--danger))]">{error}</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={handleRevert}
            disabled={!isDirty}
            className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
          >
            <RotateCcw size={10} /> revert
          </button>
          <button
            onClick={handleSave}
            disabled={!isDirty || isSaving}
            className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
          >
            <Save size={10} /> {isSaving ? "saving…" : "save"}
          </button>
          <button
            onClick={handleReRender}
            disabled={isReRendering}
            className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-[11px] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
          >
            <RefreshCw
              size={10}
              className={isReRendering ? "animate-spin" : ""}
            />
            {isReRendering ? "re-rendering…" : "▶ re-render page"}
          </button>
        </div>
      </div>

      {/* dialogue rows */}
      <div>
        {rows.map((row) => (
          <DialogueEditRow
            key={row.dialogue_index}
            row={row}
            override={overrides[row.dialogue_index] ?? {}}
            onChange={(fields) => updateOverride(row.dialogue_index, fields)}
          />
        ))}
      </div>
    </div>
  );
}
