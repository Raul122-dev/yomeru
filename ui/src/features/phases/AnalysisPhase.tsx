import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";
import { FlowDiagram } from "../run/FlowDiagram";
import { PageDetail } from "../run/PageDetail";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { getAnalyses, getContext, getRun, reanalyzeWithCorrections } from "../../lib/api";
import type { PhaseStatus, Run } from "../../lib/types";
import { getRunPhaseStatus, isPhaseComplete } from "../../lib/phase";
import { parsePartialJson, type PartialPageData } from "../../lib/partialJson";
import { usePhaseRunner, type PhaseEvent } from "../../hooks/usePhaseRunner";

export interface AnalysisPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
  showRunButton?: boolean;
  onAnalysisDone?: () => void;
}

function getBadgeVariant(status: PhaseStatus) {
  return status === "partial" ? "failed" : status;
}

function LiveLog({
  events,
  tokenBuffers,
  activePage,
  isRunning,
}: {
  events: PhaseEvent[];
  tokenBuffers: Record<number, string>;
  activePage: number | null;
  isRunning: boolean;
}) {
  const structural = events.filter((event) =>
    ["page_start", "page_done", "page_error", "phase_done", "phase_error"].includes(
      event.type ?? "",
    ),
  );

  if (!isRunning && structural.length === 0) return null;

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs uppercase tracking-widest text-[hsl(var(--text-muted))]">
          {isRunning && (
            <span className="h-2 w-2 animate-pulse rounded-full bg-[hsl(var(--accent2))]" />
          )}
          live log
        </div>
        {activePage && tokenBuffers[activePage] && (
          <span className="text-xs text-[hsl(var(--accent2))]">p{activePage} streaming</span>
        )}
      </div>
      <div className="max-h-52 space-y-1 overflow-y-auto rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-2 font-mono text-[11px] leading-relaxed text-[hsl(var(--text-muted))]">
        {structural.length === 0 && <div>waiting for analysis events…</div>}
        {structural.map((event, index) => {
          if (event.type === "page_start") {
            return (
              <div key={index}>
                → p{event.page} {String(event.filename ?? "")}
              </div>
            );
          }
          if (event.type === "page_done") {
            return (
              <div key={index} className="text-[hsl(var(--success))]">
                ✓ p{event.page} · {Number(event.dialogues ?? 0)}d {Number(event.characters ?? 0)}c
              </div>
            );
          }
          if (event.type === "page_error") {
            return (
              <div key={index} className="text-[hsl(var(--danger))]">
                ✗ p{event.page} · {String(event.error ?? "failed")}
              </div>
            );
          }
          if (event.type === "phase_done") {
            const failed = Array.isArray(event.failed) ? event.failed.length : 0;
            return (
              <div key={index} className="text-[hsl(var(--accent2))]">
                ✓ analysis complete · {Number(event.processed ?? 0)} processed
                {failed > 0 ? ` · ${failed} failed` : ""}
              </div>
            );
          }
          if (event.type === "phase_error") {
            return (
              <div key={index} className="text-[hsl(var(--danger))]">
                error: {String(event.error ?? "analysis failed")}
              </div>
            );
          }
          return null;
        })}
        {activePage && tokenBuffers[activePage] && (
          <div className="border-t border-[hsl(var(--border))] pt-2 text-[hsl(var(--accent2))]">
            <span>p{activePage} token stream: </span>
            <span className="whitespace-pre-wrap break-all text-[hsl(var(--text-muted))]">
              {tokenBuffers[activePage]}
            </span>
            <span className="animate-pulse">▊</span>
          </div>
        )}
      </div>
    </Card>
  );
}

function ContextSummary({ context }: { context: Record<string, unknown> }) {
  const characters = context.characters as
    | Record<
        string,
        { description: string; emotional_state: string; last_action: string }
      >
    | undefined;
  const scene = context.scene as
    | { location: string; mood: string; narrative_beat: string }
    | undefined;
  const summaries = (
    context.page_summaries as { page: number; summary: string }[] | undefined
  )?.slice(-5);
  const totalPages = (context.total_pages_processed as number) ?? 0;

  if (!characters && !scene) return null;

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
          Context Summary
        </h3>
        <span className="text-[10px] text-[hsl(var(--text-muted))]">
          {totalPages} pages processed
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* Characters */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--accent))]">
            Characters ({characters ? Object.keys(characters).length : 0})
          </h4>
          <div className="space-y-1.5">
            {characters &&
              Object.entries(characters)
                .slice(0, 8)
                .map(([id, character]) => (
                  <div key={id} className="rounded bg-[hsl(var(--bg-subtle))] px-2.5 py-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-medium text-[hsl(var(--text))]">{id}</span>
                      <span className="text-[10px] text-[hsl(var(--accent2))]">
                        {character.emotional_state}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-[10px] text-[hsl(var(--text-muted))]">
                      {character.description}
                    </p>
                  </div>
                ))}
            {(!characters || Object.keys(characters).length === 0) && (
              <p className="text-[11px] text-[hsl(var(--text-muted))]">No characters tracked yet</p>
            )}
          </div>
        </div>

        {/* Scene */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--accent2))]">
            Current Scene
          </h4>
          {scene ? (
            <div className="rounded bg-[hsl(var(--bg-subtle))] p-3 space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-medium">{scene.location}</span>
                <span className="text-[hsl(var(--accent2))]">{scene.mood}</span>
              </div>
              {scene.narrative_beat && (
                <p className="text-[10px] italic leading-relaxed text-[hsl(var(--text-muted))]">
                  {scene.narrative_beat}
                </p>
              )}
            </div>
          ) : (
            <p className="text-[11px] text-[hsl(var(--text-muted))]">—</p>
          )}
        </div>

        {/* Recent page summaries */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
            Story Progress
          </h4>
          <div className="space-y-1.5">
            {summaries?.map((summary) => (
              <div key={summary.page} className="flex gap-2 text-[11px]">
                <span className="shrink-0 font-mono text-[10px] text-[hsl(var(--accent2))]">
                  p{String(summary.page).padStart(2, "0")}
                </span>
                <p className="line-clamp-2 text-[10px] leading-relaxed text-[hsl(var(--text-muted))]">
                  {summary.summary}
                </p>
              </div>
            ))}
            {(!summaries || summaries.length === 0) && (
              <p className="text-[11px] text-[hsl(var(--text-muted))]">No summaries yet</p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

export function AnalysisPhase({
  runId,
  pages,
  showRunButton,
  onAnalysisDone,
}: AnalysisPhaseProps) {
  const qc = useQueryClient();
  const { progress, start, listen } = usePhaseRunner(runId);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [selectedFilename, setSelectedFilename] = useState("");

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (query: { state: { data?: Run } }) =>
      query.state.data && getRunPhaseStatus(query.state.data, "analysis") === "running"
        ? 2000
        : false,
  });

  const runStatus = run ? getRunPhaseStatus(run, "analysis") : "pending";
  const phaseStatus: PhaseStatus =
    progress?.phase === "analysis" && progress.status !== "idle"
      ? progress.status
      : runStatus;
  const canRun = run ? isPhaseComplete(getRunPhaseStatus(run, "detection")) : false;
  const isRunning = phaseStatus === "running";
  const isComplete = isPhaseComplete(phaseStatus);

  // Auto-connect WS when phase is already running (e.g. auto_start)
  useEffect(() => {
    if (runStatus === "running" && !progress) {
      listen("analysis");
    }
  }, [runStatus, progress, listen]);

  const phaseEvents = useMemo(
    () =>
      (progress?.events ?? []).filter((event) => {
        if (event.type === "token") return true;
        return (event.phase as string | undefined) === "analysis";
      }),
    [progress?.events],
  );

  const liveState = useMemo(() => {
    const tokenBuffers: Record<number, string> = {};
    const partialData: Record<number, PartialPageData> = {};
    const failedFromEvents = new Set<number>();
    let activePage: number | null = null;

    for (const event of phaseEvents) {
      const page = typeof event.page === "number" ? event.page : undefined;

      if (event.type === "page_start" && page) {
        activePage = page;
        tokenBuffers[page] = "";
      }

      if (event.type === "token" && page) {
        const nextBuffer = `${tokenBuffers[page] ?? ""}${String(event.token ?? "")}`;
        tokenBuffers[page] = nextBuffer;
        const parsed = parsePartialJson(nextBuffer);
        if (parsed && Object.keys(parsed).length > 0) {
          partialData[page] = parsed;
        }
      }

      if (event.type === "page_done" && page) {
        activePage = activePage === page ? null : activePage;
        delete tokenBuffers[page];
      }

      if (event.type === "page_error" && page) {
        activePage = activePage === page ? null : activePage;
        delete tokenBuffers[page];
        failedFromEvents.add(page);
      }

      if (event.type === "phase_done" && Array.isArray(event.failed)) {
        for (const failedPage of event.failed) {
          failedFromEvents.add(failedPage);
        }
      }
    }

    return {
      tokenBuffers,
      partialData,
      activePage,
      failedPages: [...failedFromEvents].sort((a, b) => a - b),
    };
  }, [phaseEvents]);

  const { data: analyses = [] } = useQuery({
    queryKey: ["analyses", runId],
    queryFn: () => getAnalyses(runId) as Promise<Record<string, unknown>[]>,
    enabled: phaseStatus !== "pending",
    staleTime: 0,
  });

  const { data: context } = useQuery({
    queryKey: ["context", runId],
    queryFn: () => getContext(runId) as Promise<Record<string, unknown>>,
    enabled: isComplete,
  });

  useEffect(() => {
    if (!progress || progress.phase !== "analysis") return;
    if (progress.status !== "done" && progress.status !== "failed") return;

    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["analyses", runId] });
    qc.invalidateQueries({ queryKey: ["context", runId] });

    if (progress.status === "done") {
      onAnalysisDone?.();
    }
  }, [onAnalysisDone, progress, qc, runId]);

  const mergedAnalyses = useMemo(() => {
    const merged = [...analyses];
    for (const [pageStr, partial] of Object.entries(liveState.partialData)) {
      const pageNumber = Number(pageStr);
      if (
        !merged.find(
          (analysis) =>
            (analysis as { page_number?: number }).page_number === pageNumber,
        )
      ) {
        merged.push({ page_number: pageNumber, ...partial } as Record<string, unknown>);
      }
    }
    return merged;
  }, [analyses, liveState.partialData]);

  const analysisPages = new Set(
    analyses.map((analysis) => Number((analysis as { page_number: number }).page_number)),
  );
  const failedPages =
    liveState.failedPages.length > 0
      ? liveState.failedPages
      : phaseStatus !== "done" && phaseStatus !== "partial" && phaseStatus !== "failed"
        ? []
        : pages
            .map((page) => page.page)
            .filter((pageNumber) => !analysisPages.has(pageNumber));

  const selectedAnalysis =
    selectedPage !== null
      ? (analyses.find(
          (analysis) =>
            (analysis as { page_number: number }).page_number === selectedPage,
        ) as Record<string, unknown> | undefined)
      : undefined;

  const total =
    progress?.phase === "analysis" && progress.total > 0
      ? progress.total
      : pages.length;
  const processed =
    progress?.phase === "analysis"
      ? Math.max(
          progress.processed,
          phaseEvents.filter((event) => event.type === "page_done").length,
        )
      : analyses.length;
  const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-medium">Analysis</h2>
          <Badge variant={getBadgeVariant(phaseStatus)}>{phaseStatus}</Badge>
          <span className="text-xs text-[hsl(var(--text-muted))]">
            {run?.model} · {run?.comic_format}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {showRunButton && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void start("analysis")}
                disabled={!canRun || isRunning}
              >
                {isRunning ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : null}
                {phaseStatus === "done" ? "Run Analysis Again" : "Run Analysis"}
              </Button>
            )}
            {failedPages.length > 0 && (
              <Button
                size="sm"
                variant="danger"
                onClick={() => void start("analysis", { page_scope: failedPages })}
                disabled={isRunning}
              >
                <RefreshCw size={12} className={isRunning ? "animate-spin" : ""} />
                Retry Failed ({failedPages.length})
              </Button>
            )}
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

      {(isComplete || mergedAnalyses.length > 0) && pages.length > 0 && (
        <div className="space-y-4">
          <FlowDiagram
            runId={runId}
            pages={pages}
            analyses={mergedAnalyses}
            events={phaseEvents}
            onPageSelect={(page, filename) => {
              setSelectedPage(page);
              setSelectedFilename(filename);
            }}
          />

          {selectedAnalysis && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] shadow-sm overflow-hidden"
              style={{ height: "calc(100vh - 280px)", minHeight: "550px" }}
            >
              <PageDetail
                runId={runId}
                analysis={selectedAnalysis as unknown as Parameters<typeof PageDetail>[0]["analysis"]}
                filename={selectedFilename}
                onClose={() => setSelectedPage(null)}
                isPhaseRunning={isRunning}
                onRequestReanalysis={(corrections) => {
                  const pageNum = (selectedAnalysis as any).page_number;
                  const strCorrections: Record<string, string> = {};
                  for (const [k, v] of Object.entries(corrections)) {
                    strCorrections[String(k)] = v;
                  }
                  // Connect WS BEFORE firing request to not miss events
                  listen("analysis");
                  reanalyzeWithCorrections(runId, pageNum, strCorrections);
                }}
              />
            </div>
          )}
        </div>
      )}

      <LiveLog
        events={phaseEvents}
        tokenBuffers={liveState.tokenBuffers}
        activePage={liveState.activePage}
        isRunning={isRunning}
      />

      {context && <ContextSummary context={context} />}
    </div>
  );
}
