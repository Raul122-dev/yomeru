/**
 * DetectionPhase — Phase 1 UI.
 * Shows detection controls, per-page region counts, and progress.
 * DetectionEditor (Konva) will be added in a later phase.
 */
import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Scan,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronRight,
  Pencil,
  GitBranch,
} from "lucide-react";
import {
  getRun,
  getDetections,
  startDetection,
  connectWS,
  pageImageUrl,
  type Run,
} from "../lib/api";
import { DetectionEditor, type Region } from "./typeset/DetectionEditor";
import { cn } from "../lib/utils";

interface DetectionPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
  onDetectionDone?: () => void;
}

interface PageDetection {
  page_number: number;
  original_w: number;
  original_h: number;
  regions: {
    id: number;
    label: string;
    score: number;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  }[];
}

// ── per-page row ──────────────────────────────────────────────────────────────

function PageDetectionRow({
  page,
  detection,
  isActive,
  onEdit,
}: {
  page: { page: number; filename: string };
  detection?: PageDetection;
  isActive: boolean;
  onEdit?: () => void;
}) {
  const byLabel =
    detection?.regions.reduce<Record<string, number>>((acc, r) => {
      acc[r.label] = (acc[r.label] ?? 0) + 1;
      return acc;
    }, {}) ?? {};

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-2.5 border-b border-[hsl(var(--border))] last:border-0 text-[11px]",
        isActive && "bg-[hsl(var(--accent2)/.04)]",
      )}
    >
      <span className="font-mono text-[hsl(var(--text-muted))] w-6 text-right shrink-0">
        {page.page}
      </span>
      <span className="text-[hsl(var(--text-muted))] flex-1 truncate">
        {page.filename}
      </span>

      {isActive && (
        <Loader2
          size={10}
          className="animate-spin text-[hsl(var(--accent2))] shrink-0"
        />
      )}

      {detection ? (
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[hsl(var(--text))]">
            {detection.regions.length}
          </span>
          <span className="text-[hsl(var(--text-muted)/.6)]">regions</span>
          <div className="flex gap-1">
            {Object.entries(byLabel).map(([label, count]) => (
              <span
                key={label}
                className="rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))] px-1 text-[9px] font-mono text-[hsl(var(--text-muted))]"
              >
                {count} {label.replace("_", " ")}
              </span>
            ))}
          </div>
          <CheckCircle2
            size={10}
            className="text-[hsl(var(--success))] shrink-0"
          />
          {onEdit && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              className="rounded border border-[hsl(var(--border))] px-1.5 py-0.5 text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] hover:border-[hsl(var(--accent2)/.4)] transition-colors flex items-center gap-1"
            >
              <Pencil size={9} /> edit
            </button>
          )}
        </div>
      ) : (
        !isActive && (
          <span className="text-[hsl(var(--text-muted)/.4)] shrink-0">—</span>
        )
      )}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export function DetectionPhase({
  runId,
  pages,
  onDetectionDone,
}: DetectionPhaseProps) {
  const qc = useQueryClient();
  const [isRunning, setIsRunning] = useState(false);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [activePage, setActivePage] = useState<number | null>(null);
  const [editingPage, setEditingPage] = useState<{
    page: number;
    filename: string;
  } | null>(null);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: isRunning ? 1500 : false,
  });

  const { data: allDetections = [] } = useQuery<PageDetection[]>({
    queryKey: ["detections", runId],
    queryFn: () => getDetections(runId),
    enabled: run?.detection_status === "done",
    staleTime: 0,
  });

  const detByPage = allDetections.reduce<Record<number, PageDetection>>(
    (acc, d) => {
      acc[d.page_number] = d;
      return acc;
    },
    {},
  );

  const detectMutation = useMutation({
    mutationFn: () => startDetection(runId),
    onSuccess: () => {
      setIsRunning(true);
      setEvents([]);
      // Connect WS for live events
      const cleanup = connectWS(runId, (ev: Record<string, unknown>) => {
        setEvents((prev) => [...prev, ev]);
        const t = ev.type as string;
        if (t === "detect_page_start") setActivePage(ev.page as number);
        if (t === "detect_page_done") {
          setActivePage(null);
          qc.invalidateQueries({ queryKey: ["detections", runId] });
        }
        if (t === "detect_done" || t === "error") {
          setIsRunning(false);
          setActivePage(null);
          qc.invalidateQueries({ queryKey: ["run", runId] });
          qc.invalidateQueries({ queryKey: ["detections", runId] });
          cleanup();
          if (t === "detect_done") onDetectionDone?.();
        }
      });
    },
  });

  // If already running when component mounts, reconnect WS
  useEffect(() => {
    if (run?.detection_status === "running" && !isRunning) {
      setIsRunning(true);
      const cleanup = connectWS(runId, (ev: Record<string, unknown>) => {
        setEvents((prev) => [...prev, ev]);
        const t = ev.type as string;
        if (t === "detect_page_start") setActivePage(ev.page as number);
        if (t === "detect_page_done") setActivePage(null);
        if (t === "detect_done" || t === "error") {
          setIsRunning(false);
          setActivePage(null);
          qc.invalidateQueries({ queryKey: ["run", runId] });
          qc.invalidateQueries({ queryKey: ["detections", runId] });
          cleanup();
          if (t === "detect_done") onDetectionDone?.();
        }
      });
      return cleanup;
    }
  }, [run?.detection_status]);

  const isDone = run?.detection_status === "done";
  const isFailed = run?.detection_status === "failed";

  const doneCount = events.filter((e) => e.type === "detect_page_done").length;
  const progressPct =
    pages.length > 0 ? Math.round((doneCount / pages.length) * 100) : 0;

  return (
    <>
      <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
        {/* header */}
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
          <div className="flex items-center gap-2">
            <Scan size={13} className="text-[hsl(var(--accent2))]" />
            <span className="text-sm font-medium">Detection</span>
            {isDone && (
              <span className="text-[10px] text-[hsl(var(--success))]">
                {allDetections.reduce((s, d) => s + d.regions.length, 0)}{" "}
                regions across {allDetections.length} pages
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isFailed && (
              <XCircle size={13} className="text-[hsl(var(--danger))]" />
            )}
            <button
              onClick={() => detectMutation.mutate()}
              disabled={isRunning || detectMutation.isPending}
              className={cn(
                "flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs transition-colors",
                isRunning || detectMutation.isPending
                  ? "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] cursor-not-allowed"
                  : "border-[hsl(var(--accent2)/.4)] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)]",
              )}
            >
              {isRunning ? (
                <Loader2 size={11} className="animate-spin" />
              ) : (
                <Play size={11} />
              )}
              {isDone
                ? "re-detect"
                : isRunning
                  ? "detecting…"
                  : "run detection"}
            </button>
          </div>
        </div>

        {/* progress bar */}
        {(isRunning || (events.length > 0 && !isDone)) && (
          <div className="px-4 py-2.5 border-b border-[hsl(var(--border))] space-y-1.5">
            <div className="flex justify-between font-mono text-[10px] text-[hsl(var(--text-muted))]">
              <span>
                {doneCount} / {pages.length} pages
              </span>
              <span>{progressPct}%</span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-[hsl(var(--bg-subtle))]">
              <div
                className="h-full rounded-full bg-[hsl(var(--accent2))] transition-all duration-500"
                style={{ width: doneCount === 0 ? "2%" : `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        {/* page list */}
        <div>
          {pages.map((p) => (
            <PageDetectionRow
              key={p.page}
              page={p}
              detection={detByPage[p.page]}
              isActive={activePage === p.page}
              onEdit={detByPage[p.page] ? () => setEditingPage(p) : undefined}
            />
          ))}
        </div>

        {/* empty state */}
        {pages.length === 0 && (
          <div className="px-4 py-8 text-center text-xs text-[hsl(var(--text-muted))]">
            no pages uploaded
          </div>
        )}
      </div>

      {/* Detection Editor modal */}
      {editingPage &&
        detByPage[editingPage.page] &&
        (() => {
          const det = detByPage[editingPage.page];
          return (
            <div className="fixed inset-0 z-50 flex flex-col bg-[hsl(var(--bg)/.95)] backdrop-blur-sm p-4 gap-3">
              <div className="flex items-center gap-2 shrink-0">
                <Pencil size={13} className="text-[hsl(var(--accent2))]" />
                <span className="text-sm font-medium">Detection Editor</span>
                <span className="text-xs text-[hsl(var(--text-muted))]">
                  — edit regions, then run analysis to use refined detections
                </span>
              </div>
              <div className="flex-1 min-h-0">
                <DetectionEditor
                  runId={runId}
                  pageNum={editingPage.page}
                  filename={editingPage.filename}
                  initialRegions={det.regions as Region[]}
                  originalW={det.original_w}
                  originalH={det.original_h}
                  onClose={() => setEditingPage(null)}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ["detections", runId] });
                    // Do NOT close editor on save/revert — user closes explicitly with X
                  }}
                />
              </div>
            </div>
          );
        })()}
    </>
  );
}
