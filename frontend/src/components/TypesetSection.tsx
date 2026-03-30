import { useEffect, useReducer, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Wand2,
  ChevronDown,
  ChevronUp,
  Download,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  getTypesetStatus,
  getTypesetCapabilities,
  startTypeset,
  getRun,
  runMatchingStage,
  runInpaintingStage,
  runRenderingStage,
  typesetPageUrl,
  pageImageUrl,
  getDebugImages,
  debugImageUrl,
  connectWS,
  getRenderLog,
  type StageLog,
} from "../lib/api";
import { cn } from "../lib/utils";
import { ImageViewer } from "./ui/ImageViewer";
import {
  TypesetOptionsPanel,
  type TypesetOpts,
} from "./typeset/TypesetOptions";
import { PipelineDebug } from "./typeset/PipelineDebug";
import { RenderEditor } from "./typeset/RenderEditor";

type TypesetStage =
  | "typeset_matching"
  | "typeset_inpainting"
  | "typeset_rendering";

interface TypesetSectionProps {
  runId: string;
  pages: { page: number; filename: string }[];
  runStatus: string;
  activeStage?: TypesetStage;
  onStageStatusChange?: (stage: TypesetStage, status: string) => void;
}

function groupDebugImages(
  images: string[],
): Record<string, Record<string, string>> {
  const groups: Record<string, Record<string, string>> = {};
  for (const name of images) {
    const m = name.match(/^p(\d+)_(s\d+_.+)\.jpg$/);
    if (!m) continue;
    const [, page, stage] = m;
    if (!groups[page]) groups[page] = {};
    groups[page][stage] = name;
  }
  return groups;
}

const DEFAULT_OPTS: TypesetOpts = {
  useTranslation: true,
  skipSfx: true,
  skipNarration: false,
  maxFontSize: 30,
  detectorBackend: "auto",
  detectorThreshold: 0.5,
  inpainterBackend: "auto",
  ocrWeight: 0.4,
  spatialWeight: 0.4,
  positionWeight: 0.2,
  matchMinScore: 0.05,
};

function optsReducer(
  state: TypesetOpts,
  patch: Partial<TypesetOpts>,
): TypesetOpts {
  return { ...state, ...patch };
}

export function TypesetSection({
  runId,
  pages,
  runStatus,
  activeStage,
  onStageStatusChange,
}: TypesetSectionProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [pageIdx, setPageIdx] = useState(0);
  const [showDebug, setShowDebug] = useState(false);
  const [showRenderEditor, setShowRenderEditor] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [opts, setOpts] = useReducer(optsReducer, DEFAULT_OPTS);

  const { data: runData } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    staleTime: Infinity,
  });

  const { data: capabilities } = useQuery({
    queryKey: ["typeset-capabilities"],
    queryFn: getTypesetCapabilities,
    staleTime: Infinity,
  });

  const { data: typesetStatus, refetch: refetchTypeset } = useQuery({
    queryKey: ["typeset-status", runId],
    queryFn: () => getTypesetStatus(runId),
    enabled: runStatus === "done",
    refetchInterval: isProcessing ? 2000 : 10000, // always poll slowly, fast when active
  });

  const { data: debugImages, refetch: refetchDebug } = useQuery({
    queryKey: ["debug-images", runId],
    queryFn: () => getDebugImages(runId),
    enabled: showDebug && typesetStatus?.status === "done",
  });

  const currentPage = pages[pageIdx];
  const currentPageNum = currentPage?.page ?? 0;
  const debugPageKey = String(currentPageNum).padStart(2, "0");

  const { data: stageLog } = useQuery<StageLog>({
    queryKey: ["stage-log", runId, currentPageNum],
    queryFn: () => getRenderLog(runId, currentPageNum),
    enabled:
      showDebug && typesetStatus?.status === "done" && currentPageNum > 0,
  });

  const doneCount = events.filter((e) => e.type === "typeset_page_done").length;
  const progressPct =
    pages.length > 0 ? Math.round((doneCount / pages.length) * 100) : 0;

  // isProcessing is only reset by the WS handler (typeset_done/typeset_error)
  // NOT by a useEffect polling typesetStatus — that fires prematurely

  // Polling helper for fast stages (matching, inpainting finish in seconds —
  // faster than WS can connect). Polls run status until the stage key changes.
  const pollStageStatus = async (
    stageKey: string,
    onDone: () => void,
    timeoutMs = 120_000,
  ) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const run = await getRun(runId);
        const status = (run as unknown as Record<string, unknown>)[
          stageKey
        ] as string;
        if (status === "done" || status === "failed") {
          onDone();
          return;
        }
      } catch {
        /* continue polling */
      }
    }
    // Timeout — still call onDone to unlock UI
    onDone();
  };

  // Per-stage mutations — use polling (not WS) since these stages finish fast
  const matchingMutation = useMutation({
    mutationFn: async () => {
      setEvents([]);
      setIsProcessing(true);
      await runMatchingStage(runId);
    },
    onSuccess: () =>
      pollStageStatus("typeset_matching_status", () => {
        setIsProcessing(false);
        refetchTypeset();
        refetchDebug();
        onStageStatusChange?.("typeset_matching", "done");
      }),
    onError: () => setIsProcessing(false),
  });
  const inpaintingMutation = useMutation({
    mutationFn: async () => {
      setEvents([]);
      setIsProcessing(true);
      await runInpaintingStage(runId);
    },
    onSuccess: () =>
      pollStageStatus("typeset_inpainting_status", () => {
        setIsProcessing(false);
        refetchTypeset();
        refetchDebug();
        onStageStatusChange?.("typeset_inpainting", "done");
      }),
    onError: () => setIsProcessing(false),
  });
  const renderingMutation = useMutation({
    mutationFn: async () => {
      setEvents([]);
      setIsProcessing(true);
      await runRenderingStage(runId);
    },
    onSuccess: () =>
      pollStageStatus("typeset_rendering_status", () => {
        setIsProcessing(false);
        setPageIdx(0);
        refetchTypeset();
        refetchDebug();
        onStageStatusChange?.("typeset_rendering", "done");
      }),
    onError: () => setIsProcessing(false),
  });

  const typeset = useMutation({
    mutationFn: async () => {
      setEvents([]);
      setPageIdx(0);
      setIsProcessing(true);
      // Safety: reset isProcessing after 5 min even if WS never sends done
      const safetyTimer = setTimeout(
        () => {
          setIsProcessing(false);
          setPageIdx(0);
          refetchTypeset();
          refetchDebug();
        },
        5 * 60 * 1000,
      );

      const cleanup = connectWS(runId, (ev: Record<string, unknown>) => {
        setEvents((prev) => [...prev, ev]);
        if (ev.type === "typeset_done" || ev.type === "typeset_error") {
          clearTimeout(safetyTimer);
          setTimeout(() => {
            cleanup();
            setIsProcessing(false);
            setPageIdx(0);
            refetchTypeset();
            refetchDebug();
          }, 1500);
        }
      });
      return startTypeset(runId, {
        use_translation: opts.useTranslation,
        skip_sfx: opts.skipSfx,
        skip_narration: opts.skipNarration,
        max_font_size: opts.maxFontSize,
        detector_backend: opts.detectorBackend,
        detector_threshold: opts.detectorThreshold,
        inpainter_backend: opts.inpainterBackend,
        ocr_weight: opts.ocrWeight,
        spatial_weight: opts.spatialWeight,
        position_weight: opts.positionWeight,
        match_min_score: opts.matchMinScore,
      });
    },
    onError: () => setIsProcessing(false),
  });

  if (runStatus !== "done") return null;

  const isActive = isProcessing || !!typesetStatus?.active;
  const isDone =
    typesetStatus?.status === "done" && typesetStatus.pages.length > 0;

  // Stage mode: we have content to show even without a finished full typeset
  const hasTypeset =
    currentPage && typesetStatus?.pages.includes(currentPage.filename);
  const debugGroups = groupDebugImages(debugImages?.images ?? []);
  const debugStages = debugGroups[debugPageKey] ?? {};

  const handleDownload = () => {
    if (!currentPage) return;
    const a = document.createElement("a");
    a.href = typesetPageUrl(runId, currentPage.filename);
    a.download = `typeset_p${currentPageNum}_${currentPage.filename}`;
    a.click();
  };

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
      {/* ── toolbar ───────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
        <div className="flex items-center gap-2">
          <Wand2 size={13} className="text-[hsl(var(--accent2))]" />
          <span className="text-sm font-medium">typesetting</span>
          {isDone && (
            <span className="text-[10px] text-[hsl(var(--text-muted))]">
              {typesetStatus.pages.length} pages
            </span>
          )}
          {capabilities && (
            <span className="hidden sm:inline text-[10px] text-[hsl(var(--text-muted)/.6)] ml-1">
              {capabilities.device.toUpperCase()} · {capabilities.inpainter}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowOptions((o) => !o)}
            className={cn(
              "flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] transition-colors",
              showOptions
                ? "border-[hsl(var(--accent2)/.5)] text-[hsl(var(--accent2))]"
                : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
            )}
          >
            <SlidersHorizontal size={11} />
            options
          </button>
          {/* Stage-specific run button based on activeStage */}
          {activeStage === "typeset_matching" && (
            <button
              onClick={() => matchingMutation.mutate()}
              disabled={
                isActive || matchingMutation.isPending || !capabilities?.ready
              }
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.5)] px-3 py-1 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            >
              <Wand2
                size={11}
                className={matchingMutation.isPending ? "animate-pulse" : ""}
              />
              {matchingMutation.isPending ? "matching…" : "run matching"}
            </button>
          )}
          {activeStage === "typeset_inpainting" && (
            <button
              onClick={() => inpaintingMutation.mutate()}
              disabled={
                isActive || inpaintingMutation.isPending || !capabilities?.ready
              }
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.5)] px-3 py-1 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            >
              <Wand2
                size={11}
                className={inpaintingMutation.isPending ? "animate-pulse" : ""}
              />
              {inpaintingMutation.isPending ? "inpainting…" : "run inpainting"}
            </button>
          )}
          {activeStage === "typeset_rendering" && (
            <button
              onClick={() => renderingMutation.mutate()}
              disabled={
                isActive || renderingMutation.isPending || !capabilities?.ready
              }
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.5)] px-3 py-1 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            >
              <Wand2
                size={11}
                className={renderingMutation.isPending ? "animate-pulse" : ""}
              />
              {renderingMutation.isPending ? "rendering…" : "run rendering"}
            </button>
          )}
          {/* Full pipeline button (when on rendering phase or no specific stage) */}
          <button
            onClick={() => typeset.mutate()}
            disabled={isActive || !capabilities?.ready}
            title={!capabilities?.ready ? capabilities?.message : undefined}
            className="flex items-center gap-1.5 rounded border border-[hsl(var(--border))] px-3 py-1 text-xs text-[hsl(var(--text-muted))] hover:border-[hsl(var(--accent2)/.4)] hover:text-[hsl(var(--accent2))] transition-colors disabled:opacity-40"
          >
            <Wand2 size={11} className={isActive ? "animate-pulse" : ""} />
            {isActive
              ? "processing…"
              : isDone
                ? "run all again"
                : "run all stages"}
          </button>
        </div>
      </div>

      {/* ── setup warning ─────────────────────────────────────────────── */}
      {capabilities && !capabilities.ready && (
        <div className="px-4 py-2.5 text-xs text-[hsl(var(--danger))] bg-[hsl(var(--danger)/.05)] border-b border-[hsl(var(--danger)/.2)]">
          {capabilities.message ||
            "Run python backend/setup_typesetting.py to enable typesetting"}
        </div>
      )}

      {/* ── progress ──────────────────────────────────────────────────── */}
      {(isActive || events.length > 0) && (
        <div className="px-4 py-3 border-b border-[hsl(var(--border))] space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-[hsl(var(--text-muted))]">
              {doneCount} / {pages.length} pages
            </span>
            <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
              {progressPct}%
            </span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-[hsl(var(--bg-subtle))]">
            <div
              className="h-full rounded-full bg-[hsl(var(--accent2))] transition-all duration-700"
              style={{ width: doneCount === 0 ? "2%" : `${progressPct}%` }}
            />
          </div>
          <div className="max-h-20 overflow-y-auto font-mono text-[10px] space-y-0.5 text-[hsl(var(--text-muted))]">
            {events
              .filter((e) =>
                [
                  "typeset_page_start",
                  "typeset_page_done",
                  "typeset_page_error",
                  "typeset_done",
                ].includes(e.type as string),
              )
              .slice(-8)
              .map((ev, i) => {
                const t = ev.type as string;
                if (t === "typeset_page_start")
                  return (
                    <div key={i} className="text-[hsl(var(--text-muted)/.7)]">
                      → p{ev.page as number} {ev.filename as string}
                    </div>
                  );
                if (t === "typeset_page_done")
                  return (
                    <div key={i} className="text-[hsl(var(--success))]">
                      ✓ p{ev.page as number} {(ev.renders_ok as number) ?? 0}{" "}
                      rendered
                      {((ev.renders_skipped as number) ?? 0) > 0 &&
                        ` · ${ev.renders_skipped} skipped`}
                    </div>
                  );
                if (t === "typeset_page_error")
                  return (
                    <div key={i} className="text-[hsl(var(--danger))]">
                      ✗ p{ev.page as number} {ev.error as string}
                    </div>
                  );
                if (t === "typeset_done")
                  return (
                    <div key={i} className="text-[hsl(var(--accent))]">
                      ✓ done {ev.processed as number}/{ev.total as number}
                    </div>
                  );
                return null;
              })}
          </div>
        </div>
      )}

      {/* ── main body: options sidebar + content ──────────────────────── */}
      <div
        className={cn(
          "flex",
          showOptions && "divide-x divide-[hsl(var(--border))]",
        )}
      >
        {/* options sidebar */}
        {showOptions && (
          <div className="w-64 shrink-0 p-4 bg-[hsl(var(--bg-subtle))] overflow-y-auto max-h-[75vh]">
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                options
              </span>
              <button
                onClick={() => setShowOptions(false)}
                className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
              >
                <X size={13} />
              </button>
            </div>
            <TypesetOptionsPanel
              opts={opts}
              detectors={capabilities?.detectors ?? []}
              onChange={(patch) => setOpts(patch)}
            />
          </div>
        )}

        {/* right content */}
        <div className="flex-1 min-w-0 p-4 space-y-4">
          {/* stage editor quick access — when typeset done */}
          {isDone && currentPage && (
            <div className="flex items-center gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 py-2">
              <span className="text-[10px] text-[hsl(var(--text-muted))] shrink-0">
                p{currentPageNum} editors:
              </span>
              <button
                onClick={() => {
                  setShowRenderEditor((v) => !v);
                  setShowDebug(true);
                }}
                className={cn(
                  "rounded border px-2.5 py-1 text-[10px] transition-colors",
                  showRenderEditor
                    ? "border-[hsl(var(--accent2)/.5)] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.06)]"
                    : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))]",
                )}
              >
                S5 renders
              </button>
              <button
                onClick={() => setShowDebug((v) => !v)}
                className="rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] transition-colors"
              >
                {showDebug ? "hide" : "S3 matching · S4 mask"}
              </button>
            </div>
          )}

          {/* gallery — only when done */}
          {isDone && currentPage && (
            <>
              {/* page nav + thumbnails */}
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPageIdx((i) => Math.max(0, i - 1))}
                    disabled={pageIdx === 0}
                    className="rounded border border-[hsl(var(--border))] px-2.5 py-1 text-xs disabled:opacity-30 hover:border-[hsl(var(--accent2))] transition-colors"
                  >
                    ←
                  </button>
                  <span className="flex-1 text-center font-mono text-xs text-[hsl(var(--text-muted))]">
                    page {currentPage.page} of {pages.length}
                  </span>
                  <button
                    onClick={() =>
                      setPageIdx((i) => Math.min(pages.length - 1, i + 1))
                    }
                    disabled={pageIdx === pages.length - 1}
                    className="rounded border border-[hsl(var(--border))] px-2.5 py-1 text-xs disabled:opacity-30 hover:border-[hsl(var(--accent2))] transition-colors"
                  >
                    →
                  </button>
                </div>

                <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
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
                        className="h-12 w-[34px] object-cover"
                        alt={`p${p.page}`}
                      />
                    </button>
                  ))}
                </div>
              </div>

              {/* before / after comparison */}
              {hasTypeset ? (
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                      original
                    </p>
                    <ImageViewer
                      src={pageImageUrl(runId, currentPage.filename)}
                      alt="original"
                      label={`original · p${currentPageNum}`}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--accent2))]">
                        typeset
                      </p>
                      <button
                        onClick={handleDownload}
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] hover:bg-[hsl(var(--bg-subtle))] transition-colors"
                      >
                        <Download size={10} /> save
                      </button>
                    </div>
                    <ImageViewer
                      src={typesetPageUrl(runId, currentPage.filename)}
                      alt="typeset"
                      label={`typeset · p${currentPageNum}`}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex h-28 items-center justify-center rounded border border-dashed border-[hsl(var(--border))] text-xs text-[hsl(var(--text-muted))]">
                  no typeset for this page
                </div>
              )}

              {/* debug */}
              <div>
                <button
                  onClick={() => {
                    setShowDebug((d) => !d);
                    if (!showDebug) refetchDebug();
                  }}
                  className="flex items-center gap-1.5 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
                >
                  {showDebug ? (
                    <ChevronUp size={11} />
                  ) : (
                    <ChevronDown size={11} />
                  )}
                  pipeline debug · p{currentPageNum}
                </button>

                {showDebug && (
                  <div className="mt-3">
                    <PipelineDebug
                      runId={runId}
                      pageNum={currentPageNum}
                      filename={pages[pageIdx]?.filename}
                      stages={debugStages}
                      stageLog={stageLog}
                      originalW={stageLog?.image_size?.w}
                      originalH={stageLog?.image_size?.h}
                      onStageUpdated={() => {
                        refetchDebug();
                        refetchTypeset();
                      }}
                    />
                    {stageLog && (
                      <div>
                        <button
                          onClick={() => setShowRenderEditor((v) => !v)}
                          className="flex items-center gap-1.5 rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] hover:border-[hsl(var(--accent2)/.3)] transition-colors"
                        >
                          {showRenderEditor
                            ? "hide render editor"
                            : "✏ edit renders"}
                        </button>
                      </div>
                    )}
                    {showRenderEditor && stageLog && (
                      <RenderEditor
                        runId={runId}
                        pageNum={currentPageNum}
                        stageLog={stageLog}
                        onReRendered={() => {
                          refetchDebug();
                          refetchTypeset();
                        }}
                      />
                    )}
                  </div>
                )}
              </div>
            </>
          )}

          {/* empty state */}
          {!isDone && !isActive && (
            <div className="flex h-32 items-center justify-center text-xs text-[hsl(var(--text-muted))]">
              run typesetting to see results
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
