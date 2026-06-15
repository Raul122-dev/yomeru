import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Play, Scan } from "lucide-react";
import { getDetections, getRun } from "../../lib/api";
import type { PhaseStatus, Run } from "../../lib/types";
import { getRunPhaseStatus, isPhaseComplete } from "../../lib/phase";
import { cn } from "../../lib/utils";
import { usePhaseRunner, type PhaseEvent } from "../../hooks/usePhaseRunner";
import { DetectionEditor, type Region } from "../editors/DetectionEditor";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";

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

function getBadgeVariant(status: PhaseStatus) {
  return status === "partial" ? "failed" : status;
}

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
    detection?.regions.reduce<Record<string, number>>((acc, region) => {
      acc[region.label] = (acc[region.label] ?? 0) + 1;
      return acc;
    }, {}) ?? {};

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-3 border-b border-[hsl(var(--border))] last:border-0 text-xs",
        isActive && "bg-[hsl(var(--accent2)/.04)]",
      )}
    >
      <span className="w-7 shrink-0 text-right font-mono text-[hsl(var(--text-muted))]">
        {page.page}
      </span>
      <span className="min-w-0 flex-1 truncate text-[hsl(var(--text-muted))]">
        {page.filename}
      </span>

      {isActive && (
        <Loader2 size={12} className="shrink-0 animate-spin text-[hsl(var(--accent2))]" />
      )}

      {detection ? (
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[hsl(var(--text))]">
            {detection.regions.length}
          </span>
          <span className="text-[hsl(var(--text-muted))]">regions</span>
          <div className="hidden gap-1 md:flex">
            {Object.entries(byLabel).map(([label, count]) => (
              <span
                key={label}
                className="rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-1.5 py-0.5 text-[10px] font-mono text-[hsl(var(--text-muted))]"
              >
                {count} {label.replace(/_/g, " ")}
              </span>
            ))}
          </div>
          {onEdit && (
            <button
              onClick={(event) => {
                event.stopPropagation();
                onEdit();
              }}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] transition-colors hover:border-[hsl(var(--accent2)/.4)] hover:text-[hsl(var(--accent2))]"
            >
              <Pencil size={10} /> edit
            </button>
          )}
        </div>
      ) : (
        !isActive && <span className="shrink-0 text-[hsl(var(--text-muted)/.45)]">—</span>
      )}
    </div>
  );
}

export function DetectionPhase({
  runId,
  pages,
  onDetectionDone,
}: DetectionPhaseProps) {
  const qc = useQueryClient();
  const { progress, start, listen } = usePhaseRunner(runId);
  const [editingPage, setEditingPage] = useState<{
    page: number;
    filename: string;
  } | null>(null);

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (query: { state: { data?: Run } }) =>
      query.state.data &&
      getRunPhaseStatus(query.state.data, "detection") === "running"
        ? 2000
        : false,
  });

  const runStatus = run ? getRunPhaseStatus(run, "detection") : "pending";
  const phaseStatus: PhaseStatus =
    progress?.phase === "detection" && progress.status !== "idle"
      ? progress.status
      : runStatus;
  const isRunning = phaseStatus === "running";
  const isComplete = isPhaseComplete(phaseStatus);

  // Auto-connect WS when phase is already running (auto_start)
  useEffect(() => {
    if (runStatus === "running" && !progress) {
      listen("detection");
    }
  }, [runStatus, progress, listen]);

  const phaseEvents = useMemo(
    () =>
      (progress?.events ?? []).filter(
        (event) => (event.phase as string | undefined) === "detection",
      ),
    [progress?.events],
  );

  const activePages = useMemo(() => {
    const active = new Set<number>();
    for (const event of phaseEvents) {
      if (event.type === "page_start" && typeof event.page === "number") {
        active.add(event.page);
      }
      if (
        (event.type === "page_done" || event.type === "page_error") &&
        typeof event.page === "number"
      ) {
        active.delete(event.page);
      }
    }
    return active;
  }, [phaseEvents]);

  const doneCount =
    progress?.phase === "detection"
      ? Math.max(
          progress.processed,
          phaseEvents.filter((event) => event.type === "page_done").length,
        )
      : 0;
  const total =
    progress?.phase === "detection" && progress.total > 0
      ? progress.total
      : pages.length;
  const progressPct = total > 0 ? Math.round((doneCount / total) * 100) : 0;

  const { data: allDetections = [] } = useQuery<PageDetection[]>({
    queryKey: ["detections", runId],
    queryFn: () => getDetections(runId),
    enabled: isComplete,
    staleTime: 0,
  });

  const detectionsByPage = useMemo(
    () =>
      allDetections.reduce<Record<number, PageDetection>>((acc, detection) => {
        acc[detection.page_number] = detection;
        return acc;
      }, {}),
    [allDetections],
  );

  useEffect(() => {
    if (!progress || progress.phase !== "detection") return;
    if (progress.status !== "done" && progress.status !== "failed") return;

    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["detections", runId] });

    if (progress.status === "done") {
      onDetectionDone?.();
    }
  }, [onDetectionDone, progress, qc, runId]);

  const totalRegions = allDetections.reduce(
    (sum, detection) => sum + detection.regions.length,
    0,
  );

  return (
    <>
      <Card className="p-0 overflow-hidden">
        <CardHeader className="mb-0 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-4 py-3">
          <div className="flex items-center gap-2">
            <Scan size={14} className="text-[hsl(var(--accent2))]" />
            <CardTitle className="text-sm">Detection</CardTitle>
            <Badge variant={getBadgeVariant(phaseStatus)}>{phaseStatus}</Badge>
            {isComplete && totalRegions > 0 && (
              <span className="text-xs text-[hsl(var(--text-muted))]">
                {totalRegions} regions across {allDetections.length} pages
              </span>
            )}
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void start("detection")}
            disabled={isRunning}
          >
            {isRunning ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Play size={12} />
            )}
            {isComplete ? "Run Detection Again" : "Run Detection"}
          </Button>
        </CardHeader>

        <CardContent className="p-0">
          {isRunning && (
            <div className="border-b border-[hsl(var(--border))] px-4 py-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-[hsl(var(--text-muted))]">
                <span>
                  {doneCount} / {total} pages
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
                {phaseEvents.length === 0 && <div>waiting for detection events…</div>}
                {phaseEvents.map((event, index) => {
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
                        ✓ p{event.page}
                      </div>
                    );
                  }
                  if (event.type === "page_error") {
                    return (
                      <div key={index} className="text-[hsl(var(--danger))]">
                        ✗ p{event.page} {String(event.error ?? "failed")}
                      </div>
                    );
                  }
                  if (event.type === "phase_error") {
                    return (
                      <div key={index} className="text-[hsl(var(--danger))]">
                        error: {String(event.error ?? "detection failed")}
                      </div>
                    );
                  }
                  if (event.type === "phase_done") {
                    return (
                      <div key={index} className="text-[hsl(var(--accent2))]">
                        ✓ detection complete
                      </div>
                    );
                  }
                  return null;
                })}
              </div>
            </div>
          )}

          {isComplete ? (
            pages.length > 0 ? (
              <div>
                {pages.map((page) => (
                  <PageDetectionRow
                    key={page.page}
                    page={page}
                    detection={detectionsByPage[page.page]}
                    isActive={activePages.has(page.page)}
                    onEdit={
                      detectionsByPage[page.page]
                        ? () => setEditingPage(page)
                        : undefined
                    }
                  />
                ))}
              </div>
            ) : (
              <div className="px-4 py-8 text-center text-sm text-[hsl(var(--text-muted))]">
                no pages uploaded
              </div>
            )
          ) : (
            <div className="px-4 py-10 text-center text-sm text-[hsl(var(--text-muted))]">
              Run detection to populate saved regions for each page.
            </div>
          )}
        </CardContent>
      </Card>

      {editingPage && detectionsByPage[editingPage.page] && (
        <DetectionEditor
          runId={runId}
          pageNum={editingPage.page}
          filename={editingPage.filename}
          initialRegions={detectionsByPage[editingPage.page].regions as Region[]}
          originalW={detectionsByPage[editingPage.page].original_w}
          originalH={detectionsByPage[editingPage.page].original_h}
          allPages={pages}
          allDetections={detectionsByPage}
          onClose={() => setEditingPage(null)}
          onNavigate={(page) => {
            const target = pages.find((p) => p.page === page);
            if (target && detectionsByPage[page]) {
              setEditingPage(target);
            }
          }}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["detections", runId] });
          }}
        />
      )}
    </>
  );
}
