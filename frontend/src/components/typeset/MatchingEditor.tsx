/**
 * MatchingEditor — visual reassignment of dialogues to detected regions.
 *
 * Shows all detected regions color-coded by status:
 *   green  = correctly matched dialogue
 *   red    = orphaned (detected, VLM missed)
 *   yellow = dialogue assigned but no region (shouldn't happen with direct mode)
 *
 * Click a region → sidebar shows its dialogue + reassign options.
 * Save → PUT /runs/{id}/typeset/matches/{page}
 */
import { useRef, useState, useEffect } from "react";
import {
  Stage,
  Layer,
  Rect,
  Text,
  Image as KonvaImage,
  Group,
} from "react-konva";
import useImage from "use-image";
import type Konva from "konva";
import {
  Save,
  RotateCcw,
  RefreshCw,
  ArrowRight,
  AlertTriangle,
} from "lucide-react";
import {
  savePageMatches,
  revertPageMatches,
  reRunMatching,
  pageImageUrl,
} from "../../lib/api";
import { cn } from "../../lib/utils";
import type { StageLog, MatchEvent, OrphanedRegion } from "../../lib/api";

// ── types ─────────────────────────────────────────────────────────────────────

interface EditableMatch {
  dialogue_index: number;
  region_id: number;
  match_type: "direct" | "fallback" | "manual";
  dialogue_text: string;
  region: { x1: number; y1: number; x2: number; y2: number; label: string };
  scores?: { spatial: number; text: number; position: number; total: number };
  ocr_text?: string | null;
}

interface RegionDisplay {
  id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: string;
  score: number;
  status: "matched" | "orphaned";
  dialogue_index?: number;
  dialogue_text?: string;
  ocr_text?: string | null;
}

// ── colors ────────────────────────────────────────────────────────────────────

const STATUS_COLOR = {
  matched: "#22c55e", // green
  orphaned: "#ef4444", // red
} as const;

// ── main component ────────────────────────────────────────────────────────────

interface MatchingEditorProps {
  runId: string;
  pageNum: number;
  filename: string;
  stageLog: StageLog;
  originalW: number;
  originalH: number;
  onSaved?: () => void;
}

export function MatchingEditor({
  runId,
  pageNum,
  filename,
  stageLog,
  originalW,
  originalH,
  onSaved,
}: MatchingEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);

  const imgUrl = pageImageUrl(runId, filename);
  const [bgImage] = useImage(imgUrl, "anonymous");

  const [containerW, setContainerW] = useState(600);
  useEffect(() => {
    if (!containerRef.current) return;
    const ob = new ResizeObserver((e) => setContainerW(e[0].contentRect.width));
    ob.observe(containerRef.current);
    return () => ob.disconnect();
  }, []);

  const scale = Math.min(containerW / (originalW || 1), 1);
  const dispH = (originalH || 600) * scale;

  // Build editable matches from stage log
  const s2 = stageLog.s2_detection;
  const s3 = stageLog.s3_matching;

  const [matches, setMatches] = useState<EditableMatch[]>(() =>
    (s3.matches ?? []).map((m) => ({
      dialogue_index: m.dialogue_index,
      region_id: m.region_id ?? 0,
      match_type: m.match_type,
      dialogue_text: m.dialogue_text,
      region: m.region,
      scores: m.scores,
      ocr_text: m.ocr_text,
    })),
  );

  // All detected regions with their status
  const regions: RegionDisplay[] = (s2.regions ?? []).map((r) => {
    const match = matches.find((m) => m.region_id === r.id);
    const orphan = (s3.orphaned ?? []).find(
      (o: OrphanedRegion) => o.region_id === r.id,
    );
    return {
      id: r.id,
      x1: r.bbox[0],
      y1: r.bbox[1],
      x2: r.bbox[2],
      y2: r.bbox[3],
      label: r.label,
      score: r.score,
      status: match ? "matched" : "orphaned",
      dialogue_index: match?.dialogue_index,
      dialogue_text: match?.dialogue_text,
      ocr_text: orphan?.ocr_text ?? match?.ocr_text,
    };
  });

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedRegion = regions.find((r) => r.id === selectedId);
  const selectedMatch = matches.find((m) => m.region_id === selectedId);

  // Unmatched dialogues (available to reassign)
  const matchedDlgIndices = new Set(matches.map((m) => m.dialogue_index));
  const unmatched = (s3.unmatched ?? []).filter(
    (u) => !matchedDlgIndices.has(u.dialogue_index),
  );
  const allDialogues = [
    ...matches.map((m) => ({
      dialogue_index: m.dialogue_index,
      text: m.dialogue_text,
    })),
    ...unmatched,
  ];

  // Reassign a region to a different dialogue
  const reassign = (regionId: number, dialogueIndex: number) => {
    setMatches((prev) => {
      const next = prev.filter(
        (m) => m.region_id !== regionId && m.dialogue_index !== dialogueIndex,
      );
      const dlg = allDialogues.find((d) => d.dialogue_index === dialogueIndex);
      const reg = regions.find((r) => r.id === regionId);
      if (!reg || !dlg) return next;
      return [
        ...next,
        {
          dialogue_index: dialogueIndex,
          region_id: regionId,
          match_type: "manual",
          dialogue_text: dlg.text,
          region: {
            x1: reg.x1,
            y1: reg.y1,
            x2: reg.x2,
            y2: reg.y2,
            label: reg.label,
          },
        },
      ];
    });
    setIsDirty(true);
  };

  // Remove a match (make region orphaned)
  const unmatch = (regionId: number) => {
    setMatches((prev) => prev.filter((m) => m.region_id !== regionId));
    setIsDirty(true);
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await savePageMatches(runId, pageNum, { matches });
      setIsDirty(false);
      onSaved?.();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setIsSaving(false);
    }
  };

  const handleRevert = async () => {
    await revertPageMatches(runId, pageNum);
    setMatches(
      (s3.matches ?? []).map((m) => ({
        dialogue_index: m.dialogue_index,
        region_id: m.region_id ?? 0,
        match_type: m.match_type,
        dialogue_text: m.dialogue_text,
        region: m.region,
      })),
    );
    setIsDirty(false);
    onSaved?.();
  };

  const handleReRun = async () => {
    setIsRunning(true);
    setError(null);
    try {
      await reRunMatching(runId, pageNum);
      onSaved?.();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex min-h-0 h-full overflow-hidden rounded-lg border border-[hsl(var(--border))]">
      {/* canvas */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
          <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
            matching · p{pageNum}
          </span>
          <div className="flex items-center gap-2 text-[10px]">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-green-500" /> matched
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-red-500" /> orphaned
            </span>
          </div>
          {isDirty && (
            <span className="text-[9px] text-[hsl(var(--accent2))]">
              unsaved
            </span>
          )}
          {error && (
            <span className="text-[10px] text-[hsl(var(--danger))] truncate">
              {error}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={handleRevert}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
            >
              <RotateCcw size={10} /> revert
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-[11px] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            >
              <Save size={10} /> {isSaving ? "saving…" : "save matches"}
            </button>
          </div>
        </div>

        {/* konva stage */}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto bg-[hsl(var(--bg))] p-2"
        >
          <Stage ref={stageRef} width={containerW} height={dispH}>
            <Layer>
              {bgImage && (
                <KonvaImage
                  image={bgImage}
                  width={containerW}
                  height={dispH}
                  listening={false}
                />
              )}
            </Layer>
            <Layer>
              {regions.map((r) => {
                const col = STATUS_COLOR[r.status];
                const sel = r.id === selectedId;
                const kx = r.x1 * scale,
                  ky = r.y1 * scale;
                const kw = (r.x2 - r.x1) * scale,
                  kh = (r.y2 - r.y1) * scale;

                return (
                  <Group
                    key={r.id}
                    onClick={() => setSelectedId(sel ? null : r.id)}
                  >
                    <Rect
                      x={kx}
                      y={ky}
                      width={kw}
                      height={kh}
                      fill={`${col}22`}
                      stroke={col}
                      strokeWidth={sel ? 2.5 : 1.5}
                      dash={r.status === "orphaned" ? [4, 3] : undefined}
                    />
                    {/* id badge */}
                    <Rect
                      x={kx}
                      y={ky - 9}
                      width={18}
                      height={18}
                      fill={col}
                      cornerRadius={9}
                    />
                    <Text
                      x={kx}
                      y={ky - 9}
                      width={18}
                      height={18}
                      text={String(r.id)}
                      fontSize={10}
                      fontStyle="bold"
                      fill="white"
                      align="center"
                      verticalAlign="middle"
                      listening={false}
                    />
                    {/* dialogue index if matched */}
                    {r.dialogue_index !== undefined && (
                      <Text
                        x={kx + 20}
                        y={ky - 8}
                        text={`dlg ${r.dialogue_index}`}
                        fontSize={9}
                        fill={col}
                        listening={false}
                      />
                    )}
                  </Group>
                );
              })}
            </Layer>
          </Stage>
        </div>
      </div>

      {/* sidebar */}
      <div className="w-64 shrink-0 border-l border-[hsl(var(--border))] flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
          <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
            {selectedRegion ? `region [${selectedId}]` : "click a region"}
          </p>
        </div>

        {selectedRegion ? (
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {/* region info */}
            <div className="space-y-1 text-[11px]">
              <div className="flex justify-between">
                <span className="text-[hsl(var(--text-muted))]">label</span>
                <span className="font-mono">{selectedRegion.label}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[hsl(var(--text-muted))]">status</span>
                <span
                  className={cn(
                    "font-mono",
                    selectedRegion.status === "orphaned" &&
                      "text-[hsl(var(--danger))]",
                  )}
                >
                  {selectedRegion.status}
                </span>
              </div>
              {selectedRegion.ocr_text && (
                <div>
                  <p className="text-[hsl(var(--text-muted))]">ocr</p>
                  <p className="font-mono text-[10px] mt-0.5 p-1.5 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">
                    "{selectedRegion.ocr_text}"
                  </p>
                </div>
              )}
            </div>

            {/* current match */}
            {selectedMatch && (
              <div className="rounded border border-[hsl(var(--success)/.3)] bg-[hsl(var(--success)/.04)] p-2 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[hsl(var(--success))]">
                    matched → dlg {selectedMatch.dialogue_index}
                  </span>
                  <button
                    onClick={() => unmatch(selectedId!)}
                    className="text-[10px] text-[hsl(var(--danger)/.7)] hover:text-[hsl(var(--danger))] transition-colors"
                  >
                    unmatch
                  </button>
                </div>
                <p className="text-[11px] text-[hsl(var(--text-muted))] leading-relaxed truncate">
                  "{selectedMatch.dialogue_text}"
                </p>
                {selectedMatch.scores &&
                  selectedMatch.match_type !== "direct" && (
                    <div className="flex gap-2 text-[10px] font-mono text-[hsl(var(--text-muted)/.6)]">
                      <span>sp:{selectedMatch.scores.spatial.toFixed(2)}</span>
                      <span>tx:{selectedMatch.scores.text.toFixed(2)}</span>
                      <span>to:{selectedMatch.scores.total.toFixed(2)}</span>
                    </div>
                  )}
                {selectedMatch.match_type === "manual" && (
                  <span className="text-[9px] text-[hsl(var(--accent2))]">
                    manual
                  </span>
                )}
              </div>
            )}

            {/* orphaned warning */}
            {selectedRegion.status === "orphaned" && (
              <div className="rounded border border-[hsl(var(--danger)/.3)] bg-[hsl(var(--danger)/.04)] p-2">
                <div className="flex items-center gap-1.5 text-[10px] text-[hsl(var(--danger))]">
                  <AlertTriangle size={10} />
                  VLM missed this bubble
                </div>
              </div>
            )}

            {/* reassign */}
            <div>
              <p className="mb-1.5 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                assign dialogue
              </p>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {allDialogues.map((d) => {
                  const isCurrentlyAssigned =
                    selectedMatch?.dialogue_index === d.dialogue_index;
                  const isTakenByOther = matches.some(
                    (m) =>
                      m.dialogue_index === d.dialogue_index &&
                      m.region_id !== selectedId,
                  );
                  return (
                    <button
                      key={d.dialogue_index}
                      onClick={() => reassign(selectedId!, d.dialogue_index)}
                      disabled={isCurrentlyAssigned}
                      className={cn(
                        "w-full text-left rounded border px-2 py-1.5 text-[11px] transition-colors",
                        isCurrentlyAssigned
                          ? "border-[hsl(var(--success)/.5)] bg-[hsl(var(--success)/.06)] text-[hsl(var(--success))]"
                          : isTakenByOther
                            ? "border-[hsl(var(--border))] text-[hsl(var(--text-muted)/.5)] hover:border-[hsl(var(--accent2)/.3)] hover:text-[hsl(var(--text-muted))]"
                            : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--accent2)/.4)] hover:text-[hsl(var(--text))]",
                      )}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[9px] shrink-0">
                          dlg {d.dialogue_index}
                        </span>
                        {isCurrentlyAssigned && <ArrowRight size={9} />}
                        {isTakenByOther && (
                          <span className="text-[9px]">(taken)</span>
                        )}
                      </div>
                      <p className="truncate mt-0.5">{d.text}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col">
            {/* stats */}
            <div className="p-3 space-y-2 border-b border-[hsl(var(--border))]">
              {[
                {
                  label: "matched",
                  count: regions.filter((r) => r.status === "matched").length,
                  color: "text-[hsl(var(--success))]",
                },
                {
                  label: "orphaned",
                  count: regions.filter((r) => r.status === "orphaned").length,
                  color: "text-[hsl(var(--danger))]",
                },
                { label: "total regions", count: regions.length, color: "" },
              ].map(({ label, count, color }) => (
                <div key={label} className="flex justify-between text-[11px]">
                  <span className="text-[hsl(var(--text-muted))]">{label}</span>
                  <span className={cn("font-mono", color)}>{count}</span>
                </div>
              ))}
            </div>

            {/* re-run matching */}
            <div className="p-3">
              <button
                onClick={handleReRun}
                disabled={isRunning}
                className="w-full flex items-center justify-center gap-1.5 rounded border border-[hsl(var(--border))] py-2 text-xs text-[hsl(var(--text-muted))] hover:border-[hsl(var(--accent2)/.4)] hover:text-[hsl(var(--accent2))] disabled:opacity-40 transition-colors"
              >
                <RefreshCw
                  size={11}
                  className={isRunning ? "animate-spin" : ""}
                />
                {isRunning ? "re-running…" : "re-run matching"}
              </button>
              <p className="mt-1.5 text-[9px] text-[hsl(var(--text-muted)/.5)] leading-relaxed">
                Re-runs S3 matching with current detections (refined if saved).
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
