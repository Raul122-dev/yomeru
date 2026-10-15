/**
 * RenderEditor — edit render parameters per dialogue and re-render individual regions.
 *
 * For each matched dialogue the user can:
 *  - Edit translated text
 *  - Override font_size, font_style, tone
 *  - Re-render a single region without re-running the whole pipeline
 *  - Mark a dialogue as "skip" (won't be rendered)
 *
 * With the image-edit backend each line also shows who drew it (the model or
 * scanline, and why), can be forced to either, and can be asked again from the
 * model (new seed) — one line or the whole page.
 *
 * Overrides saved to: typeset/debug/p{N:02}_render_overrides.json
 */
import { useState, useCallback, useEffect } from "react";
import {
  RefreshCw,
  Save,
  RotateCcw,
  Eye,
  EyeOff,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from "lucide-react";
import { rerenderWithModel, type ReviewItem } from "../../lib/api";
import { ReviewBadge } from "../../lib/review";
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
  /** image-edit backend: who draws this line (absent = follow the backend's scope) */
  engine?: "ai" | "scanline";
  /** image-edit backend: bumped by "ask the model again" (server side) */
  seed?: number;
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
  ai: boolean;
  provider?: string;
  cost_usd?: number;
  cache_hit?: boolean;
  fallback?: string[];
}

const ENGINES: { value: RenderOverride["engine"]; label: string }[] = [
  { value: undefined, label: "Auto" },
  { value: "ai", label: "Image model" },
  { value: "scanline", label: "Scanline" },
];

const FONT_STYLES = ["auto", "regular", "bold", "thought", "narration"];
// Only these change the drawing (shouting → bold, short shouts grow).
const TONES = ["neutral", "shouting"];

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

async function loadRenderOverrides(runId: string, pageNum: number): Promise<RenderOverride[]> {
  const res = await fetch(`/api/runs/${runId}/typeset/renders/${pageNum}`);
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()).render_overrides ?? [];
}

// ── dialogue row ──────────────────────────────────────────────────────────────

function DialogueEditRow({
  row,
  override,
  onChange,
  flags,
  aiRender,
  onAskModel,
  busy,
}: {
  row: DialogueRow;
  override: Partial<RenderOverride>;
  onChange: (fields: Partial<RenderOverride>) => void;
  flags?: ReviewItem["kind"][];
  /** the run renders with the image-edit backend */
  aiRender: boolean;
  onAskModel: () => void;
  busy: boolean;
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
              "text-xs font-mono",
              isSkipped
                ? "text-[hsl(var(--text-muted)/.4)]"
                : "text-[hsl(var(--success))]",
            )}
          >
            {isSkipped ? "—" : "✓"}
          </span>
          <span className="font-mono text-xs text-[hsl(var(--accent2))] w-5" title={`Region ${row.region_id}`}>
            r{row.region_id}
          </span>
          {flags?.map((k) => <ReviewBadge key={k} kind={k} />)}
          {aiRender && <EngineBadge row={row} />}
        </div>

        {/* translated text (editable) */}
        <textarea
          value={displayText}
          onChange={(e) => onChange({ text_translated: e.target.value })}
          rows={2}
          className="flex-1 min-w-0 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-1 text-xs leading-relaxed resize-none focus:border-[hsl(var(--accent2))] focus:outline-none"
        />

        {/* controls */}
        <div className="flex flex-col items-end gap-1 shrink-0">
          {aiRender && (
            <button
              onClick={onAskModel}
              disabled={busy || isSkipped}
              className="text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--accent2))] disabled:opacity-40 transition-colors"
              title="Ask the image model again for this line (a new attempt, paid again)"
            >
              <Sparkles size={11} />
            </button>
          )}
          <button
            onClick={() => onChange({ skip: !isSkipped })}
            className="text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--text))] transition-colors"
            title={isSkipped ? "Draw this line" : "Don't draw this line"}
          >
            {isSkipped ? <EyeOff size={11} /> : <Eye size={11} />}
          </button>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--text))] transition-colors"
            title="Style options"
          >
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>

      {/* original text + render info */}
      <div className="px-3 pb-1 flex gap-3 text-xs text-[hsl(var(--text-muted)/.6)]">
        <span className="truncate flex-1">{row.text}</span>
        {row.ai ? (
          <span title={row.provider}>
            {[row.provider?.split(" · ").pop(), row.cache_hit ? "kept" : row.cost_usd ? `$${row.cost_usd.toFixed(3)}` : null]
              .filter(Boolean).join(" · ")}
          </span>
        ) : (row.font_size || row.font_style || row.lines) && (
          <span>
            {[
              row.font_size ? `${row.font_size} px` : null,
              row.font_style,
              row.lines ? `${row.lines.length} ${row.lines.length === 1 ? "line" : "lines"}` : null,
            ].filter(Boolean).join(" · ")}
          </span>
        )}
      </div>

      {/* expanded style controls */}
      {expanded && (
        <div className="px-3 pb-2.5 pt-0 flex flex-wrap gap-3">
          {aiRender && (
            <div>
              <p className="mb-1 text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
                Drawn by
              </p>
              <div className="flex gap-1">
                {ENGINES.map((e) => (
                  <button
                    key={e.label}
                    onClick={() => onChange({ engine: e.value })}
                    title={e.value === undefined ? "Image model for the dialogues the backend's setting picks" : undefined}
                    className={cn(
                      "rounded border px-1.5 py-0.5 text-xs transition-colors",
                      override.engine === e.value
                        ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                        : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
                    )}
                  >
                    {e.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {/* font style */}
          <div>
            <p className="mb-1 text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
              Style
            </p>
            <div className="flex gap-1">
              {FONT_STYLES.map((s) => (
                <button
                  key={s}
                  onClick={() =>
                    onChange({ font_style: s === "auto" ? undefined : s })
                  }
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-xs transition-colors",
                    displayStyle === s || (s === "auto" && !override.font_style)
                      ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                      : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
                  )}
                >
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* tone */}
          <div>
            <p className="mb-1 text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
              Tone
            </p>
            <div className="flex flex-wrap gap-1">
              {TONES.map((t) => (
                <button
                  key={t}
                  onClick={() => onChange({ tone: t })}
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-xs transition-colors",
                    displayTone === t
                      ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                      : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
                  )}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* font size override */}
          <div>
            <p className="mb-1 text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
              Font size
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
              placeholder={String(row.font_size ?? "Auto")}
              onChange={(e) =>
                onChange({
                  font_size_override: e.target.value
                    ? parseInt(e.target.value)
                    : null,
                })
              }
              className="w-16 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-0.5 text-xs font-mono focus:border-[hsl(var(--accent2))] focus:outline-none"
            />
          </div>

          {/* reset override for this row */}
          {Object.keys(override).length > 0 && (
            <div className="self-end">
              <button
                onClick={() => onChange({})}
                className="text-xs text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--danger))] transition-colors"
              >
                Reset this line
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EngineBadge({ row }: { row: DialogueRow }) {
  if (row.ai) {
    return (
      <span className="rounded border border-[hsl(var(--accent2)/.4)] px-1 text-[10px] uppercase tracking-wide text-[hsl(var(--accent2))]"
        title={`Lettered by ${row.provider}${row.fallback?.length ? `\nBefore: ${row.fallback.join("\n")}` : ""}`}>
        AI
      </span>
    );
  }
  if (row.fallback?.length) {
    return (
      <span className="rounded border border-[hsl(var(--warning)/.5)] px-1 text-[10px] uppercase tracking-wide text-[hsl(var(--warning))]"
        title={`Drawn by scanline:\n${row.fallback.join("\n")}`}>
        Scanline
      </span>
    );
  }
  return null;
}

// ── main component ────────────────────────────────────────────────────────────

interface RenderEditorProps {
  runId: string;
  pageNum: number;
  stageLog: StageLog;
  onReRendered?: () => void;
  /** Why re-rendering is not possible now (same rule as the phase header). */
  blockedReason?: string | null;
  /** Review flags of this page (see lib/review). */
  review?: ReviewItem[];
  /** The run renders with the image-edit backend. */
  aiRender?: boolean;
}

export function RenderEditor({
  runId,
  pageNum,
  stageLog,
  onReRendered,
  blockedReason,
  review,
  aiRender = false,
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
      ai: r.engine === "ai",
      provider: r.provider,
      cost_usd: r.cost_usd,
      cache_hit: r.cache_hit,
      fallback: r.fallback,
    };
  });
  const askedModel = rows.filter((r) => r.ai || r.fallback?.length).length;
  const pageCost = rows.reduce((sum, r) => sum + (r.ai && !r.cache_hit ? r.cost_usd ?? 0 : 0), 0);

  // Per-dialogue overrides: { [dialogue_index]: Partial<RenderOverride> }
  const [overrides, setOverrides] = useState<
    Record<number, Partial<RenderOverride>>
  >({});
  const [saved, setSaved] = useState<Record<number, Partial<RenderOverride>>>({});
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadKey, setLoadKey] = useState(0);

  // Start from what is saved: a save sends the full list, so starting empty
  // used to silently erase earlier overrides.
  useEffect(() => {
    let alive = true;
    loadRenderOverrides(runId, pageNum)
      .then((list) => {
        if (!alive) return;
        const map = Object.fromEntries(list.map(({ dialogue_index, ...rest }) => [dialogue_index, rest]));
        setSaved(map);
        setOverrides(map);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => { alive = false; };
  }, [runId, pageNum, loadKey]);

  const { progress: rerunProgress, start: startRerun } = useScopedPhaseRunner({
    runId,
    phase: "rendering",
    onComplete: () => {
      setIsDirty(false);
      setLoadKey((k) => k + 1);   // "ask the model again" bumps seeds server side
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
      setSaved(overrides);
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

  const handleAskModel = async (dialogues: number[] | null) => {
    setError(null);
    try {
      if (isDirty) {
        await saveRenderOverrides(runId, pageNum, buildOverrideList());
      }
      await startRerun([pageNum], undefined, () => rerenderWithModel(runId, pageNum, dialogues));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRevert = () => {
    setOverrides(saved);
    setIsDirty(false);
    setError(null);
  };

  if (rows.length === 0) {
    return (
      <div className="rounded border border-[hsl(var(--border))] px-4 py-6 text-center text-xs text-[hsl(var(--text-muted))]">
        No render data for page {pageNum} — run rendering first
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
      {/* toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
        <span className="text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
          Render editor · page {pageNum}
        </span>
        {isDirty && (
          <span className="text-xs text-[hsl(var(--accent2))]">
            Unsaved changes
          </span>
        )}
        {error && (
          <span className="text-xs text-[hsl(var(--danger))]">{error}</span>
        )}
        {aiRender && askedModel > 0 && (
          <span className="text-xs text-[hsl(var(--text-muted))]">
            {rows.filter((r) => r.ai).length} by the image model{pageCost > 0 ? ` · $${pageCost.toFixed(3)}` : ""}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {aiRender && (
            <button
              onClick={() => void handleAskModel(null)}
              disabled={isReRendering || !!blockedReason || askedModel === 0}
              title={blockedReason ?? "New attempt from the image model for every line it drew or tried on this page (paid again)"}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
            >
              <Sparkles size={10} /> Ask the model again
            </button>
          )}
          <button
            onClick={handleRevert}
            disabled={!isDirty}
            className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
          >
            <RotateCcw size={10} /> Revert
          </button>
          <button
            onClick={handleSave}
            disabled={!isDirty || isSaving}
            className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
          >
            <Save size={10} /> {isSaving ? "Saving…" : "Save"}
          </button>
          <button
            onClick={handleReRender}
            disabled={isReRendering || !!blockedReason}
            title={blockedReason ?? undefined}
            className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
          >
            <RefreshCw
              size={10}
              className={isReRendering ? "animate-spin" : ""}
            />
            {isReRendering ? "Rendering…" : "Render this page again"}
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
            flags={review?.filter((r) => r.region_id === row.region_id).map((r) => r.kind)}
            aiRender={aiRender}
            onAskModel={() => void handleAskModel([row.dialogue_index])}
            busy={isReRendering || !!blockedReason}
          />
        ))}
      </div>
    </div>
  );
}
