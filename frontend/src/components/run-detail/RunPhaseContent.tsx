import { useQueryClient } from "@tanstack/react-query";
import type { Run } from "../../lib/api";
import { DetectionPhase } from "../DetectionPhase";
import { AnalysisSection } from "../AnalysisSection";
import { StageView } from "../StageView";
import { TypesetSection } from "../TypesetSection";
import type { Phase } from "../PhaseBar";

interface RunPhaseContentProps {
  runId: string;
  run: Run;
  pages: { page: number; filename: string }[];
  activePhase: Phase;
  onDetectionDone?: () => void;
  onAnalysisDone?: () => void;
  onTypesetStageChange?: () => void;
}

export function RunPhaseContent({
  runId,
  run,
  pages,
  activePhase,
  onDetectionDone,
  onAnalysisDone,
  onTypesetStageChange,
}: RunPhaseContentProps) {
  const qc = useQueryClient();

  const invalidateRunData = () => {
    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["typeset-status", runId] });
  };

  if (activePhase === "detection") {
    return (
      <DetectionPhase
        runId={runId}
        pages={pages}
        onDetectionDone={onDetectionDone}
      />
    );
  }

  if (activePhase === "analysis") {
    return (
      <AnalysisSection
        runId={runId}
        pages={pages}
        showRunButton={
          run.detection_status === "done" && run.analysis_status !== "running"
        }
        onAnalysisDone={onAnalysisDone}
      />
    );
  }

  if (
    activePhase === "typeset_matching" ||
    activePhase === "typeset_inpainting"
  ) {
    return (
      <StageView
        runId={runId}
        pages={pages}
        stage={activePhase}
        onStageStatusChange={() => {
          invalidateRunData();
          onTypesetStageChange?.();
        }}
      />
    );
  }

  if (activePhase === "typeset_rendering") {
    return (
      <TypesetSection
        runId={runId}
        pages={pages}
        runStatus={run.status}
        activeStage="typeset_rendering"
        onStageStatusChange={() => {
          invalidateRunData();
          onTypesetStageChange?.();
        }}
      />
    );
  }

  return null;
}
