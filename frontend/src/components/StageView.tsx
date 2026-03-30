/**
 * StageView — focused view for a single typeset stage.
 *
 * Shows:
 *  S3 Match:   page nav + s3 debug image + match data + match editor
 *  S4 Inpaint: page nav + s4 debug image + inpaint stats + mask editor
 *  S5 Render:  page nav + final result (before/after) + render editor
 *
 * Used when the user navigates to an individual stage tab in the PhaseBar.
 */
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, Loader2, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../lib/utils";
import {
  getDebugImages,
  getRenderLog,
  getTypesetCapabilities,
  runMatchingStage,
  runInpaintingStage,
  runRenderingStage,
  debugImageUrl,
  pageImageUrl,
  typesetPageUrl,
  getRun,
  type StageLog,
} from "../lib/api";
import { ImageViewer } from "./ui/ImageViewer";
import { PipelineDebug } from "./typeset/PipelineDebug";
import { RenderEditor } from "./typeset/RenderEditor";

type Stage = "typeset_matching" | "typeset_inpainting" | "typeset_rendering";

interface StageViewProps {
  runId: string;
  pages: { page: number; filename: string }[];
  stage: Stage;
  onStageStatusChange?: (stage: Stage, status: string) => void;
}

// ── debug image grouping (same as TypesetSection) ─────────────────────────────

function groupDebugImages(
  images: string[],
): Record<string, Record<string, string>> {
  const groups: Record<string, Record<string, string>> = {};
  const map: Record<string, string> = {
    s2_detection: "s2_detection",
    s3_matching: "s3_matching",
    s4_inpainted: "s4_inpainted",
    s5_final: "s5_final",
  };
  for (const img of images) {
    const m = img.match(/^(p\d+)_(.+)\.(jpg|png)$/);
    if (!m) continue;
    const [, pageKey, rawKey] = m;
    const stageKey = Object.keys(map).find((k) => rawKey.includes(k)) ?? rawKey;
    if (!groups[pageKey]) groups[pageKey] = {};
    groups[pageKey][stageKey] = img;
  }
  return groups;
}

// ── stage config ──────────────────────────────────────────────────────────────

const STAGE_CONFIG = {
  typeset_matching: {
    label: "S3 — Matching",
    debugKey: "s3_matching",
    runFn: runMatchingStage,
    runLabel: "run matching",
    statusKey: "typeset_matching_status",
    nextStage: "typeset_inpainting" as Stage,
    nextLabel: "go to inpainting →",
  },
  typeset_inpainting: {
    label: "S4 — Inpainting",
    debugKey: "s4_inpainted",
    runFn: runInpaintingStage,
    runLabel: "run inpainting",
    statusKey: "typeset_inpainting_status",
    nextStage: "typeset_rendering" as Stage,
    nextLabel: "go to rendering →",
  },
  typeset_rendering: {
    label: "S5 — Rendering",
    debugKey: "s5_final",
    runFn: runRenderingStage,
    runLabel: "run rendering",
    statusKey: "typeset_rendering_status",
    nextStage: null,
    nextLabel: null,
  },
};

// ── main component ────────────────────────────────────────────────────────────

export function StageView({
  runId,
  pages,
  stage,
  onStageStatusChange,
}: StageViewProps) {
  const qc = useQueryClient();
  const cfg = STAGE_CONFIG[stage];
  const [pageIdx, setPageIdx] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [showEditor, setShowEditor] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentPage = pages[pageIdx];
  const currentPageNum = currentPage?.page ?? 0;
  const pageKey = `p${String(currentPageNum).padStart(2, "0")}`;

  const { data: capabilities } = useQuery({
    queryKey: ["typeset-capabilities"],
    queryFn: getTypesetCapabilities,
    staleTime: Infinity,
  });

  const { data: debugImages, refetch: refetchDebug } = useQuery({
    queryKey: ["debug-images", runId],
    queryFn: () => getDebugImages(runId),
    staleTime: 0,
    retry: false,
  });

  const { data: stageLog, refetch: refetchLog } = useQuery<StageLog>({
    queryKey: ["stage-log", runId, currentPageNum],
    queryFn: () => getRenderLog(runId, currentPageNum),
    enabled: currentPageNum > 0,
    staleTime: 0,
    retry: false,
  });

  const debugGroups = groupDebugImages(debugImages?.images ?? []);
  const debugStages = debugGroups[pageKey] ?? {};
  const stageImage = debugStages[cfg.debugKey];

  // Poll run status until stage completes
  const pollStatus = (onDone: () => void) => {
    const check = async () => {
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const run = await getRun(runId);
          const s = (run as unknown as Record<string, unknown>)[
            cfg.statusKey
          ] as string;
          if (s === "done" || s === "failed") {
            onDone();
            return;
          }
        } catch {
          /* keep polling */
        }
      }
      onDone();
    };
    check();
  };

  const runMutation = useMutation({
    mutationFn: () => cfg.runFn(runId),
    onMutate: () => {
      setIsRunning(true);
      setError(null);
    },
    onSuccess: () =>
      pollStatus(() => {
        setIsRunning(false);
        refetchDebug();
        refetchLog();
        qc.invalidateQueries({ queryKey: ["run", runId] });
        onStageStatusChange?.(stage, "done");
      }),
    onError: (e: Error) => {
      setIsRunning(false);
      setError(e.message);
    },
  });

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
        <span className="text-sm font-medium">{cfg.label}</span>
        {isRunning && (
          <Loader2
            size={12}
            className="animate-spin text-[hsl(var(--accent2))]"
          />
        )}
        {error && (
          <span className="text-[11px] text-[hsl(var(--danger))]">{error}</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {/* editor toggle — stage-specific */}
          {stage === "typeset_matching" && stageLog && (
            <button
              onClick={() => setShowEditor((v) => !v)}
              className={cn(
                "rounded border px-2.5 py-1 text-[11px] transition-colors",
                showEditor
                  ? "border-[hsl(var(--accent2)/.5)] text-[hsl(var(--accent2))]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))]",
              )}
            >
              {showEditor ? "hide match editor" : "edit matches"}
            </button>
          )}
          {stage === "typeset_inpainting" && stageLog && (
            <button
              onClick={() => setShowEditor((v) => !v)}
              className={cn(
                "rounded border px-2.5 py-1 text-[11px] transition-colors",
                showEditor
                  ? "border-[hsl(var(--accent2)/.5)] text-[hsl(var(--accent2))]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))]",
              )}
            >
              {showEditor ? "hide mask editor" : "edit mask"}
            </button>
          )}
          {stage === "typeset_rendering" && stageLog && (
            <button
              onClick={() => setShowEditor((v) => !v)}
              className={cn(
                "rounded border px-2.5 py-1 text-[11px] transition-colors",
                showEditor
                  ? "border-[hsl(var(--accent2)/.5)] text-[hsl(var(--accent2))]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))]",
              )}
            >
              {showEditor ? "hide render editor" : "edit renders"}
            </button>
          )}
          <button
            onClick={() => runMutation.mutate()}
            disabled={isRunning || !capabilities?.ready}
            className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.5)] px-3 py-1.5 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
          >
            {isRunning ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <Play size={11} />
            )}
            {isRunning ? "running…" : cfg.runLabel}
          </button>
        </div>
      </div>

      {/* page selector */}
      {pages.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[hsl(var(--border))]">
          <button
            onClick={() => setPageIdx((i) => Math.max(0, i - 1))}
            disabled={pageIdx === 0}
            className="rounded border border-[hsl(var(--border))] px-2 py-1 text-xs disabled:opacity-30 hover:border-[hsl(var(--accent2))] transition-colors"
          >
            <ChevronLeft size={12} />
          </button>
          <span className="flex-1 text-center font-mono text-xs text-[hsl(var(--text-muted))]">
            page {currentPageNum} of {pages.length}
          </span>
          <button
            onClick={() => setPageIdx((i) => Math.min(pages.length - 1, i + 1))}
            disabled={pageIdx === pages.length - 1}
            className="rounded border border-[hsl(var(--border))] px-2 py-1 text-xs disabled:opacity-30 hover:border-[hsl(var(--accent2))] transition-colors"
          >
            <ChevronRight size={12} />
          </button>
          {/* page thumbnails */}
          <div className="flex gap-1 overflow-x-auto ml-2">
            {pages.map((p, i) => (
              <button
                key={p.page}
                onClick={() => setPageIdx(i)}
                className={cn(
                  "shrink-0 rounded border overflow-hidden transition-all",
                  i === pageIdx
                    ? "border-[hsl(var(--accent2))] ring-1 ring-[hsl(var(--accent2)/.3)]"
                    : "border-[hsl(var(--border))] opacity-40 hover:opacity-70",
                )}
              >
                <img
                  src={pageImageUrl(runId, p.filename)}
                  className="h-10 w-[29px] object-cover"
                  alt={`p${p.page}`}
                />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* content */}
      <div className="p-4 space-y-4">
        {/* stage image */}
        {stageImage ? (
          <div className="space-y-1.5">
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              {cfg.label.split(" — ")[1]} output · p{currentPageNum}
            </p>
            {stage === "typeset_rendering" ? (
              /* S5: show before/after */
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <p className="text-[10px] text-[hsl(var(--text-muted))]">
                    original
                  </p>
                  <ImageViewer
                    src={pageImageUrl(runId, currentPage?.filename ?? "")}
                    alt="original"
                    label={`original · p${currentPageNum}`}
                  />
                </div>
                <div className="space-y-1.5">
                  <p className="text-[10px] text-[hsl(var(--text-muted))]">
                    rendered
                  </p>
                  <ImageViewer
                    src={typesetPageUrl(runId, currentPage?.filename ?? "")}
                    alt="rendered"
                    label={`rendered · p${currentPageNum}`}
                  />
                </div>
              </div>
            ) : (
              /* S3/S4: show the stage debug image */
              <ImageViewer
                src={debugImageUrl(runId, stageImage)}
                alt={cfg.label}
                label={`${cfg.label} · p${currentPageNum}`}
              />
            )}
          </div>
        ) : (
          <div className="rounded border border-dashed border-[hsl(var(--border))] px-4 py-10 text-center">
            <p className="text-xs text-[hsl(var(--text-muted))]">
              No output yet for this stage
            </p>
            <p className="mt-1 text-[10px] text-[hsl(var(--text-muted)/.6)]">
              Click "{cfg.runLabel}" to run this stage
            </p>
          </div>
        )}

        {/* stage data from render log */}
        {stageLog && (
          <PipelineDebug
            runId={runId}
            pageNum={currentPageNum}
            filename={currentPage?.filename}
            stages={debugStages}
            stageLog={stageLog}
            originalW={stageLog.image_size?.w}
            originalH={stageLog.image_size?.h}
            onStageUpdated={() => {
              refetchDebug();
              refetchLog();
            }}
          />
        )}

        {/* stage-specific editors */}
        {showEditor && stageLog && currentPage && (
          <>
            {stage === "typeset_rendering" && (
              <RenderEditor
                runId={runId}
                pageNum={currentPageNum}
                stageLog={stageLog}
                onReRendered={() => {
                  refetchDebug();
                  refetchLog();
                }}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
