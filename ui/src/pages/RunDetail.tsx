import { useParams, Link } from "react-router-dom";
import { Download } from "lucide-react";
import { PhaseBar } from "../features/phases/PhaseBar";
import { RunHeader } from "../features/run/RunHeader";
import { RunPhaseContent } from "../features/run/RunPhaseContent";
import { RunStatus, runState } from "../features/run/RunStatus";
import { LABELS } from "../features/phases/PhaseBar";
import { useRunDetailData } from "../hooks/useRunDetailData";
import { useRunPhaseNavigation } from "../hooks/useRunPhaseNavigation";
import { buttonVariants } from "../components/ui/button";
import { cn } from "../lib/utils";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const runId = id as string;

  const { run, pages, derived, typesetStatus, isLoading, isError, error } = useRunDetailData(runId);
  const { activePhase, goToPhase } = useRunPhaseNavigation(run, derived);

  if (isError) {
    return (
      <div className="rounded-[var(--radius-md)] border border-[hsl(var(--border))] p-8">
        <p className="eyebrow">Run not found</p>
        <p className="mt-2 text-sm text-[hsl(var(--text-muted))]">{(error as Error)?.message}</p>
        <Link to="/" className="mt-4 inline-block text-sm text-[hsl(var(--accent2))] underline underline-offset-4">Back to runs</Link>
      </div>
    );
  }
  if (isLoading || !run || !derived) {
    return <div className="text-sm text-[hsl(var(--text-muted))]">Loading…</div>;
  }

  const hasRendered = (typesetStatus?.pages?.length ?? 0) > 0;
  const state = runState(run);
  const confirmExport = (e: React.MouseEvent) => {
    if (state.kind === "done") return;
    const why = state.kind === "pending" ? state.reason : state.kind === "failed" ? `${LABELS[state.phase]} failed` : "a step is running";
    if (!window.confirm(`The result may be out of date (${why}).\n\nDownload anyway?`)) e.preventDefault();
  };

  return (
    <div className="flex flex-col gap-5">
      <RunHeader run={run} />
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <PhaseBar run={run} activePhase={activePhase} onPhaseClick={goToPhase} />
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
          <RunStatus run={run} />
          {hasRendered && (
          <div className="flex h-9 items-center gap-2">
            <a href={`/api/runs/${runId}/export?format=cbz`} onClick={confirmExport}
               className={cn(buttonVariants({ variant: state.kind === "done" ? "default" : "outline", size: "sm" }))}
               title="Comic book archive — opens in comic readers (pages in reading order)">
              <Download size={12} /> Download .cbz
            </a>
            <a href={`/api/runs/${runId}/export?format=zip`} onClick={confirmExport}
               className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
               title="Plain folder of images">
              .zip
            </a>
          </div>
          )}
        </div>
      </div>
      <RunPhaseContent runId={runId} run={run} pages={pages} activePhase={activePhase} />
    </div>
  );
}
