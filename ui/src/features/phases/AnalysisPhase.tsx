import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { FlowDiagram } from "../run/FlowDiagram";
import { PageDetail } from "../run/PageDetail";
import { Button } from "../../components/ui/button";
import { getAnalyses, getContext, reanalyzeWithCorrections } from "../../lib/api";
import { parsePartialJson, type PartialPageData } from "../../lib/partialJson";
import { usePhaseView } from "../../hooks/usePhaseView";
import { EmptyState, Panel, PhaseHeader } from "./PhaseShell";

export interface AnalysisPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
  showRunButton?: boolean;
  onAnalysisDone?: () => void;
}

/** Parse each page's streamed JSON at most every 250 ms. */
function usePartialData(tokens: Record<number, string>) {
  const [parsed, setParsed] = useState<Record<number, PartialPageData>>({});
  const latest = useRef(tokens);
  latest.current = tokens;
  useEffect(() => {
    const id = window.setTimeout(() => {
      const out: Record<number, PartialPageData> = {};
      for (const [p, buf] of Object.entries(latest.current)) {
        const d = parsePartialJson(buf);
        if (d && Object.keys(d).length) out[Number(p)] = d;
      }
      setParsed(out);
    }, 250);
    return () => window.clearTimeout(id);
  }, [tokens]);
  return parsed;
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
    <Panel>
      <div className="mb-4 flex items-baseline justify-between">
        <p className="eyebrow">Story context</p>
        <span className="font-mono text-xs text-[hsl(var(--text-muted))]">{totalPages} pages read</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* Characters */}
        <div className="space-y-2">
          <h4 className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
            Characters ({characters ? Object.keys(characters).length : 0})
          </h4>
          <div className="space-y-1.5">
            {characters &&
              Object.entries(characters)
                .slice(0, 8)
                .map(([id, character]) => (
                  <div key={id} className="rounded bg-[hsl(var(--bg-subtle))] px-2.5 py-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-[hsl(var(--text))]">{id}</span>
                      <span className="text-xs text-[hsl(var(--accent2))]">
                        {character.emotional_state}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-[hsl(var(--text-muted))]">
                      {character.description}
                    </p>
                  </div>
                ))}
            {(!characters || Object.keys(characters).length === 0) && (
              <p className="text-xs text-[hsl(var(--text-muted))]">No characters tracked yet</p>
            )}
          </div>
        </div>

        {/* Scene */}
        <div className="space-y-2">
          <h4 className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
            Current Scene
          </h4>
          {scene ? (
            <div className="rounded bg-[hsl(var(--bg-subtle))] p-3 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium">{scene.location}</span>
                <span className="text-[hsl(var(--accent2))]">{scene.mood}</span>
              </div>
              {scene.narrative_beat && (
                <p className="text-xs italic leading-relaxed text-[hsl(var(--text-muted))]">
                  {scene.narrative_beat}
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-[hsl(var(--text-muted))]">—</p>
          )}
        </div>

        {/* Recent page summaries */}
        <div className="space-y-2">
          <h4 className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
            Story Progress
          </h4>
          <div className="space-y-1.5">
            {summaries?.map((summary) => (
              <div key={summary.page} className="flex gap-2 text-xs">
                <span className="shrink-0 font-mono text-xs text-[hsl(var(--accent2))]">
                  p{String(summary.page).padStart(2, "0")}
                </span>
                <p className="line-clamp-2 text-xs leading-relaxed text-[hsl(var(--text-muted))]">
                  {summary.summary}
                </p>
              </div>
            ))}
            {(!summaries || summaries.length === 0) && (
              <p className="text-xs text-[hsl(var(--text-muted))]">No summaries yet</p>
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}

export function AnalysisPhase({ runId, pages }: AnalysisPhaseProps) {
  const qc = useQueryClient();
  const v = usePhaseView(runId, "analysis", pages, { invalidate: ["analyses", "context"] });
  const [selected, setSelected] = useState<{ page: number; filename: string } | null>(null);

  const events = useMemo(
    () => (v.progress?.phase === "analysis" ? v.progress.events : []),
    [v.progress],
  );
  const tokens = v.progress?.phase === "analysis" ? v.progress.tokens : {};
  const partial = usePartialData(tokens);

  const { data: analyses = [] } = useQuery({
    queryKey: ["analyses", runId],
    queryFn: () => getAnalyses(runId) as Promise<Record<string, unknown>[]>,
    enabled: v.status !== "pending",
    staleTime: 0,
  });
  const { data: context } = useQuery({
    queryKey: ["context", runId],
    queryFn: () => getContext(runId) as Promise<Record<string, unknown>>,
    enabled: v.hasOutput,
  });

  useEffect(() => {
    if (v.status !== "running") {
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
      qc.invalidateQueries({ queryKey: ["context", runId] });
    }
  }, [v.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const merged = useMemo(() => {
    const out = [...analyses];
    for (const [p, data] of Object.entries(partial)) {
      if (!out.find((a) => (a as { page_number?: number }).page_number === Number(p)))
        out.push({ page_number: Number(p), ...data });
    }
    return out;
  }, [analyses, partial]);

  const analysed = new Set(analyses.map((a) => Number((a as { page_number: number }).page_number)));
  const failedLive = events.filter((e) => e.type === "page_error").map((e) => Number(e.page));
  const failedPages = failedLive.length
    ? [...new Set(failedLive)]
    : v.hasOutput ? pages.map((p) => p.page).filter((n) => !analysed.has(n)) : [];

  const selectedAnalysis = selected
    ? (analyses.find((a) => (a as { page_number: number }).page_number === selected.page) as Record<string, unknown> | undefined)
    : undefined;

  const modelLabel = (v.run as { connection_name?: string } | undefined)?.connection_name;

  return (
    <div className="flex flex-col gap-4">
      <PhaseHeader
        runId={runId}
        title="Read & translate"
        description={`Reads every page with the vision model and translates it${modelLabel ? ` — ${modelLabel} · ${v.run?.model}` : v.run?.model ? ` — ${v.run.model}` : ""}.`}
        status={v.status}
        canRun={v.canRun}
        blockedReason={v.blockedReason}
        onRun={() => void v.start()}
        processed={v.processed || (v.isRunning ? 0 : analyses.length)}
        total={v.total}
      >
        {failedPages.length > 0 && !v.isRunning && (
          <div className="flex items-center gap-3 border-t border-[hsl(var(--border))] px-5 py-2.5 text-sm text-[hsl(var(--danger))]">
            {failedPages.length} {failedPages.length === 1 ? "page" : "pages"} without analysis
            <Button size="sm" variant="danger" className="ml-auto"
                    onClick={() => void v.start({ page_scope: failedPages })}>
              <RefreshCw size={12} /> Retry {failedPages.length === 1 ? "it" : "them"}
            </Button>
          </div>
        )}
      </PhaseHeader>

      {merged.length === 0 && !v.isRunning ? (
        <EmptyState>Run analysis once detection is done. The model reads each page in order and keeps track of characters and story.</EmptyState>
      ) : (
        <>
          <FlowDiagram
            runId={runId}
            pages={pages}
            analyses={merged}
            events={events}
            tokens={tokens}
            onPageSelect={(page, filename) => setSelected({ page, filename })}
          />
          {selectedAnalysis && selected && (
            <div className="overflow-hidden rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))]"
                 style={{ height: "calc(100vh - 260px)", minHeight: 550 }}>
              <PageDetail
                key={selected.page}
                runId={runId}
                analysis={selectedAnalysis as unknown as Parameters<typeof PageDetail>[0]["analysis"]}
                filename={selected.filename}
                onClose={() => setSelected(null)}
                isPhaseRunning={v.isRunning}
                onRequestReanalysis={async (corrections) => {
                  const str = Object.fromEntries(Object.entries(corrections).map(([k, c]) => [String(k), c]));
                  try {
                    await reanalyzeWithCorrections(runId, selected.page, str);
                    qc.invalidateQueries({ queryKey: ["run", runId] });
                    toast(`Re-analysing page ${selected.page}…`);
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : String(e));
                  }
                }}
              />
            </div>
          )}
        </>
      )}

      {context && <ContextSummary context={context} />}
    </div>
  );
}
