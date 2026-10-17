import type { Run } from "../../lib/types";
import { AnalysisPhase } from "../phases/AnalysisPhase";
import { DetectionPhase } from "../phases/DetectionPhase";
import { InpaintingPhase } from "../phases/InpaintingPhase";
import { MatchingPhase } from "../phases/MatchingPhase";
import type { Phase } from "../phases/PhaseBar";
import { RenderingPhase } from "../phases/RenderingPhase";

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
  pages,
  activePhase,
  onDetectionDone,
  onAnalysisDone,
}: RunPhaseContentProps) {
  switch (activePhase) {
    case "detection":
      return (
        <DetectionPhase
          runId={runId}
          pages={pages}
          onDetectionDone={onDetectionDone}
        />
      );
    case "analysis":
      return (
        <AnalysisPhase
          runId={runId}
          pages={pages}
          showRunButton
          onAnalysisDone={onAnalysisDone}
        />
      );
    case "matching":
      return <MatchingPhase runId={runId} pages={pages} />;
    case "inpainting":
      return <InpaintingPhase runId={runId} pages={pages} />;
    case "rendering":
      return <RenderingPhase runId={runId} pages={pages} />;
    default:
      return null;
  }
}
