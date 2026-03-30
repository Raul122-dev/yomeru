import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, ChevronDown, ChevronUp, Terminal } from "lucide-react";
import {
  getRun,
  getContext,
  getAnalyses,
  connectWS,
  retryRun,
  startAnalysis,
  type Run,
} from "../lib/api";
import { parsePartialJson, type PartialPageData } from "../lib/partialJson";
import { Badge } from "./ui/badge";
import { Card } from "./ui/card";
import { FlowDiagram } from "./FlowDiagram";
import { PageDetail } from "./PageDetail";
import { DialogueEditor } from "./DialogueEditor";

// ── types shared with parent ──────────────────────────────────────────────────
export interface AnalysisSectionProps {
  runId: string;
  pages: { page: number; filename: string }[];
  /** If true, show "Run Analysis" button (detection already done) */
  showRunButton?: boolean;
  onAnalysisDone?: () => void;
}

// ── live log ──────────────────────────────────────────────────────────────────
function LiveLog({
  events,
  tokenBuffers,
  activePageLog,
  isRunning,
}: {
  events: Record<string, unknown>[];
  tokenBuffers: Record<number, string>;
  activePageLog: number | null;
  isRunning: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [showTokens, setShowTokens] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isRunning) setOpen(true);
  }, [isRunning]);
  useEffect(() => {
    if (open && logRef.current)
      logRef.current.scrollTo(0, logRef.current.scrollHeight);
  }, [events, tokenBuffers, open]);

  const structural = events.filter((e) =>
    [
      "page_start",
      "page_done",
      "page_error",
      "done",
      "error",
      "retry_start",
      "retry_done",
    ].includes(e.type as string),
  );

  return (
    <div className="rounded-lg border border-[hsl(var(--border))]">
      <div className="flex items-center justify-between px-4 py-2.5">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
        >
          {isRunning && (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[hsl(var(--accent2))]" />
          )}
          <Terminal size={12} />
          pipeline log
          {structural.length > 0 && <span>({structural.length})</span>}
          {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
        {open && (
          <button
            onClick={() => setShowTokens((t) => !t)}
            className={`text-[10px] transition-colors ${showTokens ? "text-[hsl(var(--accent2))]" : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"}`}
          >
            {showTokens ? "hide tokens" : "show token stream"}
          </button>
        )}
      </div>
      {open && (
        <div
          ref={logRef}
          className="h-52 overflow-y-auto border-t border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-4 py-2.5 font-mono text-xs leading-relaxed space-y-0.5"
        >
          {structural.length === 0 && !activePageLog && (
            <span className="text-[hsl(var(--text-muted))]">
              waiting for pipeline events…
            </span>
          )}
          {structural.map((ev, i) => {
            const t = ev.type as string;
            if (t === "page_start")
              return (
                <div key={i} className="text-[hsl(var(--text-muted))]">
                  → p{ev.page as number} {ev.filename as string}
                </div>
              );
            if (t === "page_detect_done")
              return (
                <div key={i} className="text-[hsl(var(--accent2))]">
                  {" "}
                  ⬡ p{ev.page as number} {ev.regions as number} regions detected
                </div>
              );
            if (t === "page_done")
              return (
                <div key={i} className="text-[hsl(var(--success))]">
                  ✓ p{ev.page as number} · {ev.dialogues as number}d{" "}
                  {ev.characters as number}c{" "}
                  <span className="text-[hsl(var(--text-muted))]">
                    {ev.mood as string}
                  </span>
                </div>
              );
            if (t === "page_error")
              return (
                <div key={i} className="text-[hsl(var(--danger))]">
                  ✗ p{ev.page as number} · {ev.error as string}
                </div>
              );
            if (t === "done")
              return (
                <div key={i} className="font-medium text-[hsl(var(--accent))]">
                  ✓ done {ev.processed as number}/{ev.total as number}
                </div>
              );
            if (t === "error")
              return (
                <div key={i} className="text-[hsl(var(--danger))]">
                  error: {ev.message as string}
                </div>
              );
            if (t === "retry_start")
              return (
                <div key={i} className="text-[hsl(var(--accent2))]">
                  ↻ retrying {ev.total as number} pages
                </div>
              );
            if (t === "retry_done")
              return (
                <div key={i} className="text-[hsl(var(--accent))]">
                  ↻ done · {(ev.newly_processed as number[]).length} recovered
                </div>
              );
            return null;
          })}
          {showTokens && activePageLog && tokenBuffers[activePageLog] && (
            <div className="mt-1 border-t border-[hsl(var(--border))] pt-1">
              <span className="text-[hsl(var(--accent2))]">
                p{activePageLog} stream:{" "}
              </span>
              <span className="text-[hsl(var(--text-muted))] whitespace-pre-wrap break-all">
                {tokenBuffers[activePageLog]}
              </span>
              <span className="animate-pulse text-[hsl(var(--accent2))]">
                ▊
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── context summary ───────────────────────────────────────────────────────────
function ContextSummary({ context }: { context: Record<string, unknown> }) {
  const chars = context.characters as
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
  )?.slice(-3);
  if (!chars && !scene) return null;

  return (
    <div className="grid grid-cols-3 gap-4">
      <Card>
        <h3 className="mb-3 text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
          characters
        </h3>
        <div className="space-y-2">
          {chars &&
            Object.entries(chars)
              .slice(0, 6)
              .map(([id, c]) => (
                <div key={id} className="text-xs">
                  <span className="font-medium text-[hsl(var(--accent))]">
                    {id}
                  </span>
                  <span className="ml-1.5 text-[hsl(var(--accent2))]">
                    {c.emotional_state}
                  </span>
                  <p className="text-[hsl(var(--text-muted))] line-clamp-1 text-[10px]">
                    {c.description}
                  </p>
                </div>
              ))}
          {(!chars || Object.keys(chars).length === 0) && (
            <p className="text-xs text-[hsl(var(--text-muted))]">—</p>
          )}
        </div>
      </Card>
      <Card>
        <h3 className="mb-3 text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
          current scene
        </h3>
        {scene ? (
          <div className="space-y-1.5 text-xs">
            <p className="font-medium">{scene.location}</p>
            <p className="text-[hsl(var(--accent2))]">{scene.mood}</p>
            <p className="text-[hsl(var(--text-muted))] text-[10px] leading-relaxed">
              {scene.narrative_beat}
            </p>
          </div>
        ) : (
          <p className="text-xs text-[hsl(var(--text-muted))]">—</p>
        )}
      </Card>
      <Card>
        <h3 className="mb-3 text-[10px] font-medium uppercase tracking-wider text-[hsl(var(--text-muted))]">
          recent pages
        </h3>
        <div className="space-y-2">
          {summaries?.map((ps) => (
            <div key={ps.page} className="flex gap-2 text-xs">
              <span className="shrink-0 font-mono text-[hsl(var(--accent))]">
                p{ps.page}
              </span>
              <p className="text-[hsl(var(--text-muted))] line-clamp-2 text-[10px] leading-relaxed">
                {ps.summary}
              </p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────
export function AnalysisSection({
  runId,
  pages,
  showRunButton,
  onAnalysisDone,
}: AnalysisSectionProps) {
  const qc = useQueryClient();
  const [showDialogueEditor, setShowDialogueEditor] = useState(false);

  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [tokenBuffers, setTokenBuffers] = useState<Record<number, string>>({});
  const [partialData, setPartialData] = useState<
    Record<number, PartialPageData>
  >({});
  const [activePageLog, setActivePageLog] = useState<number | null>(null);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [selectedFilename, setSelectedFilename] = useState("");

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (q: { state: { data?: Run } }) => {
      const s = q.state.data?.status;
      return s === "running" || s === "pending" ? 2000 : false;
    },
  });

  const { data: analyses = [], refetch: refetchAnalyses } = useQuery({
    queryKey: ["analyses", runId],
    queryFn: () => getAnalyses(runId) as Promise<Record<string, unknown>[]>,
    enabled: !!run && run.status !== "pending",
    refetchInterval: (q: { state: { data?: unknown[] } }) =>
      run?.status === "running" ? 8000 : false,
  });

  const { data: context, refetch: refetchCtx } = useQuery({
    queryKey: ["context", runId],
    queryFn: () => getContext(runId) as Promise<Record<string, unknown>>,
    enabled: run?.status === "done",
  });

  const retry = useMutation({
    mutationFn: () => retryRun(runId),
    onSuccess: () => {
      setEvents([]);
      setTokenBuffers({});
      setPartialData({});
      setActivePageLog(null);
      qc.invalidateQueries({ queryKey: ["run", runId] });
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
    },
  });

  const analysisMutation = useMutation({
    mutationFn: () => startAnalysis(runId),
    onSuccess: () => {
      setEvents([]);
      setTokenBuffers({});
      setPartialData({});
      setActivePageLog(null);
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
    onSettled: () => onAnalysisDone?.(),
  });

  const handleEvent = useCallback(
    (ev: Record<string, unknown>) => {
      const type = ev.type as string;
      const page = ev.page as number | undefined;
      setEvents((prev) => [...prev, ev]);
      if (type === "page_start" && page) {
        setActivePageLog(page);
        setTokenBuffers((prev) => ({ ...prev, [page]: "" }));
      }
      if (type === "token" && page) {
        const token = ev.token as string;
        setTokenBuffers((prev) => {
          const accumulated = (prev[page] ?? "") + token;
          const parsed = parsePartialJson(accumulated);
          if (parsed && Object.keys(parsed).length > 0)
            setPartialData((pd) => ({ ...pd, [page]: parsed }));
          return { ...prev, [page]: accumulated };
        });
      }
      if (type === "page_done" && page) {
        setActivePageLog(null);
        setTokenBuffers((prev) => {
          const n = { ...prev };
          delete n[page];
          return n;
        });
      }
      if (type === "done") {
        setActivePageLog(null);
        qc.invalidateQueries({ queryKey: ["run", runId] });
        refetchCtx();
        refetchAnalyses();
      }
    },
    [runId, qc, refetchCtx, refetchAnalyses],
  );

  useEffect(() => {
    if (run?.status !== "running") return;
    return connectWS(runId, handleEvent);
  }, [run?.status, runId, handleEvent]);

  if (!run) return null;

  const isRunning =
    run.status === "running" || run.analysis_status === "running";
  const hasFailures =
    run.status !== "running" && run.processed_pages < run.total_pages;
  const pct =
    run.total_pages > 0
      ? Math.round((run.processed_pages / run.total_pages) * 100)
      : 0;

  // merge partial data for live diagram
  const mergedAnalyses = [...analyses];
  Object.entries(partialData).forEach(([pageStr, partial]) => {
    const pageNum = parseInt(pageStr);
    if (
      !mergedAnalyses.find(
        (a: Record<string, unknown>) =>
          (a as { page_number: number }).page_number === pageNum,
      )
    )
      mergedAnalyses.push({ page_number: pageNum, ...partial } as Record<
        string,
        unknown
      >);
  });

  const selectedAnalysis =
    selectedPage !== null
      ? ((analyses as { page_number: number }[]).find(
          (a) => a.page_number === selectedPage,
        ) as Record<string, unknown> | undefined)
      : undefined;

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-medium text-[hsl(var(--text-muted))]">
          analysis
        </h2>
        <Badge variant={run.status}>{run.status}</Badge>
        <div className="ml-auto flex items-center gap-3">
          {showRunButton && run.analysis_status !== "running" && (
            <button
              onClick={() => analysisMutation.mutate()}
              disabled={analysisMutation.isPending || isRunning}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] transition-colors disabled:opacity-50"
            >
              {analysisMutation.isPending ? (
                <RefreshCw size={11} className="animate-spin" />
              ) : null}
              {run.analysis_status === "done" ? "re-analyze" : "run analysis"}
            </button>
          )}
          {hasFailures && (
            <button
              onClick={() => retry.mutate()}
              disabled={retry.isPending}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--danger)/.5)] px-2.5 py-1 text-xs text-[hsl(var(--danger))] hover:bg-[hsl(var(--danger)/.08)] transition-colors disabled:opacity-50"
            >
              <RefreshCw
                size={11}
                className={retry.isPending ? "animate-spin" : ""}
              />
              retry {run.total_pages - run.processed_pages} failed
            </button>
          )}
          <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
            {run.model} · {run.comic_format}
          </span>
        </div>
      </div>

      {/* progress */}
      {isRunning && (
        <div>
          <div className="mb-1.5 flex justify-between text-xs text-[hsl(var(--text-muted))]">
            <span>
              {run.processed_pages} / {run.total_pages} pages
            </span>
            <span className="text-[hsl(var(--accent2))]">{pct}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--bg-subtle))]">
            <div
              className="h-full rounded-full bg-[hsl(var(--accent2))] transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      {run.status === "failed" && run.processed_pages === 0 && (
        <div className="rounded-lg border border-[hsl(var(--danger))] p-3">
          <p className="text-sm text-[hsl(var(--danger))]">
            {run.error || "run failed"}
          </p>
        </div>
      )}

      {/* flow diagram + detail panel */}
      {pages.length > 0 && (
        <div
          className={
            selectedAnalysis
              ? "grid grid-cols-[1fr_360px] gap-4 items-start"
              : ""
          }
        >
          <FlowDiagram
            runId={runId}
            pages={pages}
            analyses={mergedAnalyses}
            events={events}
            onPageSelect={(p, f) => {
              setSelectedPage(p);
              setSelectedFilename(f);
            }}
          />
          {selectedAnalysis && (
            <div className="sticky top-20 h-[500px] overflow-hidden rounded-lg border border-[hsl(var(--border))] flex flex-col">
              <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] shrink-0">
                <span className="text-[10px] text-[hsl(var(--text-muted))]">
                  p{(selectedAnalysis as { page_number: number }).page_number}
                </span>
                <button
                  onClick={() => setShowDialogueEditor((v) => !v)}
                  className="ml-auto text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] transition-colors"
                >
                  {showDialogueEditor ? "view analysis" : "edit dialogues"}
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                {showDialogueEditor ? (
                  <div className="h-full overflow-y-auto">
                    <DialogueEditor
                      runId={runId}
                      pageNum={
                        (selectedAnalysis as { page_number: number })
                          .page_number
                      }
                      pageData={selectedAnalysis as any}
                      onSaved={() =>
                        qc.invalidateQueries({ queryKey: ["analyses", runId] })
                      }
                    />
                  </div>
                ) : (
                  <PageDetail
                    runId={runId}
                    analysis={
                      selectedAnalysis as unknown as Parameters<
                        typeof PageDetail
                      >[0]["analysis"]
                    }
                    filename={selectedFilename}
                    onClose={() => setSelectedPage(null)}
                  />
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* log */}
      {(isRunning || events.length > 0) && (
        <LiveLog
          events={events}
          tokenBuffers={tokenBuffers}
          activePageLog={activePageLog}
          isRunning={isRunning}
        />
      )}

      {/* context summary */}
      {context && <ContextSummary context={context} />}
    </div>
  );
}
