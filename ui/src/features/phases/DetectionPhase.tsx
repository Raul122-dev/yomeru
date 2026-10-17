import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { getDetections, pageImageUrl } from "../../lib/api";
import { Img } from "../../components/ui/Img";
import { usePhaseView } from "../../hooks/usePhaseView";
import { DetectionEditor, type Region } from "../editors/DetectionEditor";
import { cn } from "../../lib/utils";
import { EmptyState, PhaseHeader } from "./PhaseShell";

interface DetectionPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
  onDetectionDone?: () => void;
}

interface PageDetection {
  page_number: number;
  original_w: number;
  original_h: number;
  regions: { id: number; label: string; score: number; x1: number; y1: number; x2: number; y2: number }[];
}

const LABEL_NAMES: Record<string, string> = {
  bubble: "bubble",
  text_bubble: "text in bubble",
  text_free: "free text",
};

export function DetectionPhase({ runId, pages }: DetectionPhaseProps) {
  const qc = useQueryClient();
  const v = usePhaseView(runId, "detection", pages, { invalidate: ["detections"] });
  const [editing, setEditing] = useState<{ page: number; filename: string } | null>(null);

  const { data: all = [] } = useQuery<PageDetection[]>({
    queryKey: ["detections", runId],
    queryFn: () => getDetections(runId),
    enabled: v.hasOutput,
    staleTime: 0,
  });
  const byPage = useMemo(
    () => Object.fromEntries(all.map((d) => [d.page_number, d])) as Record<number, PageDetection>,
    [all],
  );

  // Pages being processed right now (live)
  const activePages = useMemo(() => {
    const s = new Set<number>();
    for (const e of v.progress?.events ?? []) {
      if (e.phase !== "detection" || typeof e.page !== "number") continue;
      if (e.type === "page_start") s.add(e.page);
      if (e.type === "page_done" || e.type === "page_error") s.delete(e.page);
    }
    return s;
  }, [v.progress?.events]);

  useEffect(() => {
    if (v.status !== "running") qc.invalidateQueries({ queryKey: ["detections", runId] });
  }, [v.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalRegions = all.reduce((n, d) => n + d.regions.length, 0);

  return (
    <div className="flex flex-col gap-4">
      <PhaseHeader
        runId={runId}
        title="Detection"
        description="Finds speech bubbles and text on every page. Fix boxes before reading for better results."
        status={v.status}
        canRun={v.canRun}
        onRun={() => void v.start()}
        processed={v.processed}
        total={v.total}
      />

      {!v.hasOutput && !v.isRunning ? (
        <EmptyState>Run detection to find the bubbles and text on each page.</EmptyState>
      ) : (
        <>
          {totalRegions > 0 && (
            <p className="font-mono text-xs text-[hsl(var(--text-muted))]">
              {totalRegions} regions across {all.length} pages · click a page to edit its boxes
            </p>
          )}
          <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
            {pages.map((p) => {
              const det = byPage[p.page];
              const active = activePages.has(p.page);
              const counts = det?.regions.reduce<Record<string, number>>((acc, r) => {
                acc[r.label] = (acc[r.label] ?? 0) + 1;
                return acc;
              }, {});
              return (
                <button
                  key={p.page}
                  disabled={!det}
                  onClick={() => det && setEditing(p)}
                  className={cn(
                    "group flex flex-col rounded-[var(--radius-sm)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] p-1.5 text-left transition-colors",
                    det ? "hover:border-[hsl(var(--accent2))]" : "cursor-default",
                    active && "ring-2 ring-[hsl(var(--accent2))]",
                  )}
                  title={counts ? Object.entries(counts).map(([l, n]) => `${n} ${LABEL_NAMES[l] ?? l}`).join(" · ") : undefined}
                >
                  <div className="relative aspect-[5/7] overflow-hidden rounded-[4px] bg-[hsl(var(--bg-subtle))]">
                    <Img src={pageImageUrl(runId, p.filename)} alt={`Page ${p.page}`} loading="lazy" sizes="160px" maxWidth={320}
                         className="size-full" imgClassName={cn("object-cover object-top", active && "opacity-60")} />
                    {det && (
                      <span className="absolute inset-x-1.5 bottom-1.5 flex items-center justify-center gap-1 rounded-[4px] bg-[hsl(var(--bg-surface)/.92)] py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100">
                        <Pencil size={11} /> Edit boxes
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 flex items-baseline justify-between px-0.5">
                    <span className="font-mono text-xs font-medium">p{String(p.page).padStart(2, "0")}</span>
                    <span className="font-mono text-[11px] text-[hsl(var(--text-muted))]">
                      {active ? "Detecting…" : det ? `${det.regions.length} regions` : "—"}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </>
      )}

      {editing && byPage[editing.page] && (
        <DetectionEditor
          runId={runId}
          pageNum={editing.page}
          filename={editing.filename}
          initialRegions={byPage[editing.page].regions as Region[]}
          originalW={byPage[editing.page].original_w}
          originalH={byPage[editing.page].original_h}
          allPages={pages}
          allDetections={byPage}
          onClose={() => setEditing(null)}
          onNavigate={(page) => {
            const target = pages.find((x) => x.page === page);
            if (target && byPage[page]) setEditing(target);
          }}
          onSaved={() => qc.invalidateQueries({ queryKey: ["detections", runId] })}
        />
      )}
    </div>
  );
}
