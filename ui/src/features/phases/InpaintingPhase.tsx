import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eraser, Loader2, Play } from "lucide-react";
import {
  debugImageUrl,
  getDebugImages,
  getRenderLog,
  getRun,
  maskDebugUrl,
  pageImageUrl,
} from "../../lib/api";
import type { PhaseStatus, Run, StageLog } from "../../lib/types";
import { getRunPhaseStatus, isPhaseComplete } from "../../lib/phase";
import { getStageDebugImage, groupDebugImages } from "../../lib/debug";
import { usePhaseRunner } from "../../hooks/usePhaseRunner";
import { MaskEditor } from "../editors/MaskEditor";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ImageViewer } from "../../components/ui/ImageViewer";

interface InpaintingPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
}

interface PageStageLog {
  page: number;
  filename: string;
  log: StageLog | null;
}

function getBadgeVariant(status: PhaseStatus) {
  return status === "partial" ? "failed" : status;
}

async function loadStageLogs(
  runId: string,
  pages: { page: number; filename: string }[],
): Promise<PageStageLog[]> {
  return Promise.all(
    pages.map(async (page) => {
      try {
        return {
          page: page.page,
          filename: page.filename,
          log: await getRenderLog(runId, page.page),
        } satisfies PageStageLog;
      } catch {
        return { page: page.page, filename: page.filename, log: null } satisfies PageStageLog;
      }
    }),
  );
}

export function InpaintingPhase({ runId, pages }: InpaintingPhaseProps) {
  const qc = useQueryClient();
  const { progress, start, listen } = usePhaseRunner(runId);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [showMaskDebug, setShowMaskDebug] = useState(false);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (query: { state: { data?: Run } }) =>
      query.state.data && getRunPhaseStatus(query.state.data, "inpainting") === "running"
        ? 2000
        : false,
  });

  const runStatus = run ? getRunPhaseStatus(run, "inpainting") : "pending";
  const phaseStatus: PhaseStatus =
    progress?.phase === "inpainting" && progress.status !== "idle"
      ? progress.status
      : runStatus;
  const isRunning = phaseStatus === "running";
  const isComplete = isPhaseComplete(phaseStatus);
  const canRun = run ? isPhaseComplete(getRunPhaseStatus(run, "matching")) : false;

  useEffect(() => {
    if (runStatus === "running" && !progress) listen("inpainting");
  }, [runStatus, progress, listen]);

  const phaseEvents = useMemo(
    () =>
      (progress?.events ?? []).filter(
        (event) => (event.phase as string | undefined) === "inpainting",
      ),
    [progress?.events],
  );

  const { data: debugImages } = useQuery({
    queryKey: ["debug-images", runId],
    queryFn: () => getDebugImages(runId),
    enabled: isComplete,
    staleTime: 0,
    retry: false,
  });

  const { data: pageLogs = [] } = useQuery({
    queryKey: ["inpainting-logs", runId, pages.map((page) => page.page).join(",")],
    queryFn: () => loadStageLogs(runId, pages),
    enabled: isComplete,
    staleTime: 0,
  });

  useEffect(() => {
    if (!progress || progress.phase !== "inpainting") return;
    if (progress.status !== "done" && progress.status !== "failed") return;

    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["inpainting-logs", runId] });
    qc.invalidateQueries({ queryKey: ["debug-images", runId] });
    setRefreshNonce((value) => value + 1);
  }, [progress, qc, runId]);

  useEffect(() => {
    if (selectedPage !== null && pageLogs.some((entry) => entry.page === selectedPage)) {
      return;
    }
    setSelectedPage(pageLogs[0]?.page ?? null);
  }, [pageLogs, selectedPage]);

  const debugGroups = useMemo(
    () => groupDebugImages(debugImages?.images ?? []),
    [debugImages?.images],
  );

  const selectedEntry = pageLogs.find((entry) => entry.page === selectedPage) ?? null;
  const selectedDebugImage = selectedEntry
    ? getStageDebugImage(debugGroups, selectedEntry.page, "s4_inpainted")
    : null;
  const total =
    progress?.phase === "inpainting" && progress.total > 0
      ? progress.total
      : pages.length;
  const processed =
    progress?.phase === "inpainting"
      ? Math.max(
          progress.processed,
          phaseEvents.filter((event) => event.type === "page_done").length,
        )
      : 0;
  const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Eraser size={14} className="text-[hsl(var(--accent2))]" />
            <h2 className="text-sm font-medium">Inpainting</h2>
            <Badge variant={getBadgeVariant(phaseStatus)}>{phaseStatus}</Badge>
          </div>
          <div className="ml-auto">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void start("inpainting")}
              disabled={!canRun || isRunning}
            >
              {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {isComplete ? "Run Inpainting Again" : "Run Inpainting"}
            </Button>
          </div>
        </div>

        {isRunning && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-[hsl(var(--text-muted))]">
              <span>
                {processed} / {total} pages
              </span>
              <span className="text-[hsl(var(--accent2))]">{progressPct}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[hsl(var(--bg-subtle))]">
              <div
                className="h-full rounded-full bg-[hsl(var(--accent2))] transition-all duration-500"
                style={{ width: `${Math.max(progressPct, 2)}%` }}
              />
            </div>
          </div>
        )}
      </Card>

      {isComplete ? (
        pageLogs.length > 0 ? (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {pageLogs.map((entry) => {
                const inpainting = entry.log?.s4_inpainting;
                const preview = getStageDebugImage(debugGroups, entry.page, "s4_inpainted");
                return (
                  <button
                    key={entry.page}
                    onClick={() => setSelectedPage(entry.page)}
                    className={`rounded-lg border p-4 text-left transition-colors ${
                      entry.page === selectedPage
                        ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.05)]"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] hover:border-[hsl(var(--accent2)/.35)]"
                    }`}
                  >
                    <div className="mb-3 flex items-center justify-between">
                      <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
                        p{String(entry.page).padStart(2, "0")}
                      </span>
                      <span className="text-xs text-[hsl(var(--text-muted))]">
                        {inpainting?.backend ?? "—"}
                      </span>
                    </div>
                    <div className="mb-3 grid grid-cols-2 gap-2">
                      <img
                        src={`${pageImageUrl(runId, entry.filename)}?v=${refreshNonce}`}
                        alt={entry.filename}
                        className="h-28 w-full rounded border border-[hsl(var(--border))] object-cover"
                      />
                      {preview ? (
                        <img
                          src={`${debugImageUrl(runId, preview)}?v=${refreshNonce}`}
                          alt={`inpainted ${entry.page}`}
                          className="h-28 w-full rounded border border-[hsl(var(--border))] object-cover"
                        />
                      ) : (
                        <div className="flex h-28 items-center justify-center rounded border border-dashed border-[hsl(var(--border))] text-xs text-[hsl(var(--text-muted))]">
                          no output
                        </div>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--accent2))]">
                          {inpainting?.coverage_pct ?? 0}%
                        </div>
                        <div className="text-[hsl(var(--text-muted))]">coverage</div>
                      </div>
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--text))]">
                          {inpainting?.skipped ? "yes" : "no"}
                        </div>
                        <div className="text-[hsl(var(--text-muted))]">skipped</div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {selectedEntry?.log && (
              <Card className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-medium">Page {selectedEntry.page}</h3>
                    <p className="text-xs text-[hsl(var(--text-muted))]">{selectedEntry.filename}</p>
                  </div>
                  <div className="flex gap-3 text-xs text-[hsl(var(--text-muted))]">
                    <span title="Inpainting backend used">{selectedEntry.log.s4_inpainting?.backend ?? "—"}</span>
                    <span title="Number of pixels in the mask">{((selectedEntry.log.s4_inpainting?.mask_pixels ?? 0) / 1000).toFixed(1)}k px masked</span>
                    <span title="% of image area covered by the mask — lower is better (only text should be masked)">{selectedEntry.log.s4_inpainting?.coverage_pct ?? 0}% coverage</span>
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                      before
                    </p>
                    <ImageViewer
                      src={`${pageImageUrl(runId, selectedEntry.filename)}?v=${refreshNonce}`}
                      alt={selectedEntry.filename}
                      label={`before · p${selectedEntry.page}`}
                    />
                  </div>
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                      after
                    </p>
                    {selectedDebugImage ? (
                      <ImageViewer
                        src={`${debugImageUrl(runId, selectedDebugImage)}?v=${refreshNonce}`}
                        alt={`inpainted p${selectedEntry.page}`}
                        label={`after · p${selectedEntry.page}`}
                      />
                    ) : (
                      <div className="flex h-full min-h-40 items-center justify-center rounded border border-dashed border-[hsl(var(--border))] text-sm text-[hsl(var(--text-muted))]">
                        no inpainted output
                      </div>
                    )}
                  </div>
                </div>

                {/* Mask Debug Toggle */}
                <div className="space-y-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowMaskDebug(!showMaskDebug)}
                  >
                    {showMaskDebug ? "Hide" : "Show"} Generated Masks
                  </Button>
                  {showMaskDebug && selectedEntry && (
                    <div className="space-y-1">
                      <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                        mask overlay — colored areas show what will be inpainted per region
                      </p>
                      <ImageViewer
                        src={`${maskDebugUrl(runId, selectedEntry.page)}?v=${refreshNonce}`}
                        alt={`mask debug p${selectedEntry.page}`}
                        label={`masks · p${selectedEntry.page}`}
                      />
                      <div className="flex gap-4 text-[10px] text-[hsl(var(--text-muted))]">
                        <span className="flex items-center gap-1">
                          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "#ff00ff" }} />
                          text_bubble
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "#00c8ff" }} />
                          text_free
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "#ffa500" }} />
                          sfx
                        </span>
                      </div>
                    </div>
                  )}
                </div>

                <MaskEditor
                  runId={runId}
                  pageNum={selectedEntry.page}
                  filename={selectedEntry.filename}
                  stageLog={selectedEntry.log}
                  originalW={selectedEntry.log.image_size?.w ?? 0}
                  originalH={selectedEntry.log.image_size?.h ?? 0}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ["inpainting-logs", runId] });
                    qc.invalidateQueries({ queryKey: ["debug-images", runId] });
                    setRefreshNonce((value) => value + 1);
                  }}
                />
              </Card>
            )}
          </>
        ) : (
          <Card className="text-sm text-[hsl(var(--text-muted))]">
            No inpainting logs available yet.
          </Card>
        )
      ) : (
        <Card className="text-sm text-[hsl(var(--text-muted))]">
          Run inpainting after matching completes to preview cleaned pages and adjust masks.
        </Card>
      )}
    </div>
  );
}
