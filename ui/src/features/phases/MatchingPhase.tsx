import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Loader2, Play } from "lucide-react";
import {
  debugImageUrl,
  getDebugImages,
  getRenderLog,
  getRun,
  pageImageUrl,
} from "../../lib/api";
import type { PhaseStatus, Run, StageLog } from "../../lib/types";
import { getRunPhaseStatus, isPhaseComplete } from "../../lib/phase";
import { getStageDebugImage, groupDebugImages } from "../../lib/debug";
import { usePhaseRunner, type PhaseEvent } from "../../hooks/usePhaseRunner";
import { MatchingEditor } from "../editors/MatchingEditor";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { ImageViewer } from "../../components/ui/ImageViewer";

interface MatchingPhaseProps {
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
  const results = await Promise.all(
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

  return results;
}

export function MatchingPhase({ runId, pages }: MatchingPhaseProps) {
  const qc = useQueryClient();
  const { progress, start, listen } = usePhaseRunner(runId);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (query: { state: { data?: Run } }) =>
      query.state.data && getRunPhaseStatus(query.state.data, "matching") === "running"
        ? 2000
        : false,
  });

  const runStatus = run ? getRunPhaseStatus(run, "matching") : "pending";
  const phaseStatus: PhaseStatus =
    progress?.phase === "matching" && progress.status !== "idle"
      ? progress.status
      : runStatus;
  const isRunning = phaseStatus === "running";
  const isComplete = isPhaseComplete(phaseStatus);
  const canRun = run ? isPhaseComplete(getRunPhaseStatus(run, "analysis")) : false;

  useEffect(() => {
    if (runStatus === "running" && !progress) listen("matching");
  }, [runStatus, progress, listen]);

  const phaseEvents = useMemo(
    () =>
      (progress?.events ?? []).filter(
        (event) => (event.phase as string | undefined) === "matching",
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
    queryKey: ["matching-logs", runId, pages.map((page) => page.page).join(",")],
    queryFn: () => loadStageLogs(runId, pages),
    enabled: isComplete,
    staleTime: 0,
  });

  useEffect(() => {
    if (!progress || progress.phase !== "matching") return;
    if (progress.status !== "done" && progress.status !== "failed") return;

    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["matching-logs", runId] });
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
    ? getStageDebugImage(debugGroups, selectedEntry.page, "s3_matching")
    : null;
  const total =
    progress?.phase === "matching" && progress.total > 0
      ? progress.total
      : pages.length;
  const processed =
    progress?.phase === "matching"
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
            <Link2 size={14} className="text-[hsl(var(--accent2))]" />
            <h2 className="text-sm font-medium">Matching</h2>
            <Badge variant={getBadgeVariant(phaseStatus)}>{phaseStatus}</Badge>
          </div>
          <div className="ml-auto">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void start("matching")}
              disabled={!canRun || isRunning}
            >
              {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {isComplete ? "Run Matching Again" : "Run Matching"}
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
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-2 font-mono text-[11px] text-[hsl(var(--text-muted))]">
              {phaseEvents.map((event, index) => {
                if (event.type === "page_start") {
                  return <div key={index}>→ p{event.page} {String(event.filename ?? "")}</div>;
                }
                if (event.type === "page_done") {
                  return <div key={index} className="text-[hsl(var(--success))]">✓ p{event.page}</div>;
                }
                if (event.type === "page_error") {
                  return (
                    <div key={index} className="text-[hsl(var(--danger))]">
                      ✗ p{event.page} {String(event.error ?? "failed")}
                    </div>
                  );
                }
                return null;
              })}
            </div>
          </div>
        )}
      </Card>

      {isComplete ? (
        pageLogs.length > 0 ? (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {pageLogs.map((entry) => {
                const matching = entry.log?.s3_matching;
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
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
                        p{String(entry.page).padStart(2, "0")}
                      </span>
                      <span className="text-xs text-[hsl(var(--text-muted))] truncate">
                        {entry.filename}
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--success))]">{matching?.matched ?? 0}</div>
                        <div className="text-[hsl(var(--text-muted))]">matched</div>
                      </div>
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--warning))]">{matching?.unmatched_dialogues ?? 0}</div>
                        <div className="text-[hsl(var(--text-muted))]">unmatched</div>
                      </div>
                      <div className="rounded border border-[hsl(var(--border))] px-2 py-2">
                        <div className="font-mono text-[hsl(var(--danger))]">{matching?.orphaned_regions ?? 0}</div>
                        <div className="text-[hsl(var(--text-muted))]">orphaned</div>
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
                  <div className="flex gap-2 text-xs text-[hsl(var(--text-muted))]">
                    <span>{selectedEntry.log.s3_matching?.direct ?? 0} direct</span>
                    <span>{selectedEntry.log.s3_matching?.fallback ?? 0} fallback</span>
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
                      matching debug
                    </p>
                    {selectedDebugImage ? (
                      <ImageViewer
                        src={`${debugImageUrl(runId, selectedDebugImage)}?v=${refreshNonce}`}
                        alt={`matching p${selectedEntry.page}`}
                        label={`matching · p${selectedEntry.page}`}
                      />
                    ) : (
                      <div className="flex h-full min-h-40 items-center justify-center rounded border border-dashed border-[hsl(var(--border))] text-sm text-[hsl(var(--text-muted))]">
                        no matching debug image
                      </div>
                    )}
                  </div>
                </div>

                <MatchingEditor
                  runId={runId}
                  pageNum={selectedEntry.page}
                  filename={selectedEntry.filename}
                  stageLog={selectedEntry.log}
                  originalW={selectedEntry.log.image_size?.w ?? 0}
                  originalH={selectedEntry.log.image_size?.h ?? 0}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ["matching-logs", runId] });
                    qc.invalidateQueries({ queryKey: ["debug-images", runId] });
                    setRefreshNonce((value) => value + 1);
                  }}
                />
              </Card>
            )}
          </>
        ) : (
          <Card className="text-sm text-[hsl(var(--text-muted))]">
            No matching logs available yet.
          </Card>
        )
      ) : (
        <Card className="text-sm text-[hsl(var(--text-muted))]">
          Run matching after analysis completes to review dialogue-region assignments.
        </Card>
      )}
    </div>
  );
}
