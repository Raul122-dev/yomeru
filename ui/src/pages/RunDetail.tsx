import { useParams } from "react-router-dom";
import { PhaseBar } from "../features/phases/PhaseBar";
import { RunHeader } from "../features/run/RunHeader";
import { RunPhaseContent } from "../features/run/RunPhaseContent";
import { useRunDetailData } from "../hooks/useRunDetailData";
import { useRunPhaseNavigation } from "../hooks/useRunPhaseNavigation";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const runId = id as string;

  const { run, pages, derived, isLoading } = useRunDetailData(runId);
  const { activePhase, setActivePhase, goToPhase } = useRunPhaseNavigation(
    run,
    derived,
  );

  if (isLoading || !run || !derived) {
    return (
      <div className="text-sm text-[hsl(var(--text-muted))]">loading…</div>
    );
  }

  return (
    <div className="space-y-4">
      <RunHeader run={run} />

      <PhaseBar run={run} activePhase={activePhase} onPhaseClick={goToPhase} />

      <RunPhaseContent
        runId={runId}
        run={run}
        pages={pages}
        activePhase={activePhase}
        onDetectionDone={() => undefined}
        onAnalysisDone={() => undefined}
        onTypesetStageChange={() => undefined}
      />
    </div>
  );
}
