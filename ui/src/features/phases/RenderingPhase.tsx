import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Brush, Loader2, Play } from "lucide-react";
import {
  getRenderLog,
  getRun,
  pageImageUrl,
  typesetPageUrl,
} from "../../lib/api";
import type { PhaseStatus, Run, StageLog } from "../../lib/types";
import { getRunPhaseStatus, isPhaseComplete } from "../../lib/phase";
import { usePhaseRunner } from "../../hooks/usePhaseRunner";
import { RenderEditor } from "../editors/RenderEditor";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ImageViewer } from "../../components/ui/ImageViewer";

interface RenderingPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
}

interface PageStageLog {
  page: number;
  filename: string;
  log: StageLog | null;
}

function getBadgeVariant(status: PhaseStatus) {
  return status === "partial" ? "pending" : status;
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

export function RenderingPhase({ runId, pages }: RenderingPhaseProps) {
  const qc = useQueryClient();
  const { progress, start, listen } = usePhaseRunner(runId);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (query: { state: { data?: Run } }) =>
      query.state.data && getRunPhaseStatus(query.state.data, "rendering") === "running"
        ? 2000
        : false,
  });

  const runStatus = run ? getRunPhaseStatus(run, "rendering") : "pending";
  const phaseStatus: PhaseStatus =
    progress?.phase === "rendering" && progress.status !== "idle"
      ? progress.status
      : runStatus;
  const isRunning = phaseStatus === "running";
  const isComplete = isPhaseComplete(phaseStatus);
  const canRun = run ? isPhaseComplete(getRunPhaseStatus(run, "inpainting")) : false;

  useEffect(() => {
    if (runStatus === "running" && !progress) listen("rendering");
  }, [runStatus, progress, listen]);

  const phaseEvents = (progress?.events ?? []).filter(
    (event) => (event.phase as string | undefined) === "rendering",
  );

  const { data: pageLogs = [] } = useQuery({
    queryKey: ["rendering-logs", runId, pages.map((page) => page.page).join(",")],
    queryFn: () => loadStageLogs(runId, pages),
    enabled: isComplete,
    staleTime: 0,
  });

  useEffect(() => {
    if (!progress || progress.phase !== "rendering") return;
    if (progress.status !== "done" && progress.status !== "failed") return;

    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["rendering-logs", runId] });
    qc.invalidateQueries({ queryKey: ["typeset-status", runId] });
    setRefreshNonce((value) => value + 1);
  }, [progress, qc, runId]);

  useEffect(() => {
    if (selectedPage !== null && pageLogs.some((entry) => entry.page === selectedPage)) {
      return;
    }
    setSelectedPage(pageLogs[0]?.page ?? null);
  }, [pageLogs, selectedPage]);

  const selectedEntry = pageLogs.find((entry) => entry.page === selectedPage) ?? null;
  const total =
    progress?.phase === "rendering" && progress.total > 0
      ? progress.total
      : pages.length;
  const processed =
    progress?.phase === "rendering"
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
            <Brush size={14} className="text-[hsl(var(--accent2))]" />
            <h2 className="text-sm font-medium">Rendering</h2>
            <Badge variant={getBadgeVariant(phaseStatus)}>{phaseStatus}</Badge>
          </div>
          <div className="ml-auto">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void start("rendering")}
              disabled={!canRun || isRunning}
            >
              {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {isComplete ? "Run Rendering Again" : "Run Rendering"}
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
                const rendering = entry.log?.s5_rendering;
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
                      <span className="text-xs text-[hsl(var(--text-muted))]">{entry.filename}</span>
                    </div>
                    <img
                      src={`${typesetPageUrl(runId, entry.filename)}?v=${refreshNonce}`}
                      alt={`rendered ${entry.filename}`}
                      className="mb-3 h-40 w-full rounded border border-[hsl(var(--border))] object-cover"
                    />
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--success))]">{rendering?.ok ?? 0}</div>
                        <div className="text-[hsl(var(--text-muted))]">ok</div>
                      </div>
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--warning))]">{rendering?.skipped ?? 0}</div>
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
                    <span>{selectedEntry.log.s5_rendering?.ok ?? 0} ok</span>
                    <span>{selectedEntry.log.s5_rendering?.skipped ?? 0} skipped</span>
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                      original
                    </p>
                    <ImageViewer
                      src={`${pageImageUrl(runId, selectedEntry.filename)}?v=${refreshNonce}`}
                      alt={selectedEntry.filename}
                      label={`original · p${selectedEntry.page}`}
                    />
                  </div>
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                      rendered
                    </p>
                    <ImageViewer
                      src={`${typesetPageUrl(runId, selectedEntry.filename)}?v=${refreshNonce}`}
                      alt={`rendered ${selectedEntry.filename}`}
                      label={`rendered · p${selectedEntry.page}`}
                    />
                  </div>
                </div>

                <RenderEditor
                  runId={runId}
                  pageNum={selectedEntry.page}
                  stageLog={selectedEntry.log}
                  onReRendered={() => {
                    qc.invalidateQueries({ queryKey: ["rendering-logs", runId] });
                    qc.invalidateQueries({ queryKey: ["typeset-status", runId] });
                    setRefreshNonce((value) => value + 1);
                  }}
                />
              </Card>
            )}
          </>
        ) : (
          <Card className="text-sm text-[hsl(var(--text-muted))]">
            No rendering logs available yet.
          </Card>
        )
      ) : (
        <Card className="text-sm text-[hsl(var(--text-muted))]">
          Run rendering after inpainting completes to review final output and override dialogues.
        </Card>
      )}
    </div>
  );
}
