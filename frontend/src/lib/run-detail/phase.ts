import type { Run, TypesetStatus } from "../api";
import type { Phase } from "../../components/PhaseBar";

export type PhaseStatus = "pending" | "running" | "done" | "failed";

export interface TypesetStageStatuses {
  matching: PhaseStatus;
  inpainting: PhaseStatus;
  rendering: PhaseStatus;
}

export interface DerivedRunPhaseState {
  legacyDone: boolean;
  analysisReady: boolean;
  typesetReady: boolean;
  typesetOutputExists: boolean;
  tsStatuses: TypesetStageStatuses;
}

export function getDefaultPhase(run: Run): Phase {
  if (!run.detection_status && run.status === "done") return "analysis";
  if (run.analysis_status === "done" || run.analysis_status === "running") {
    return "analysis";
  }
  if (run.detection_status === "done") return "analysis";
  if (run.detection_status === "running") return "detection";
  return "detection";
}

export function getDerivedRunPhaseState(
  run: Run,
  typesetStatus?: TypesetStatus,
): DerivedRunPhaseState {
  const typesetOutputExists =
    typesetStatus?.status === "done" && (typesetStatus.pages?.length ?? 0) > 0;

  const legacyDone = !run.detection_status && run.status === "done";
  const analysisReady = run.detection_status === "done" || legacyDone;
  const typesetReady = run.analysis_status === "done" || legacyDone;

  const runWithTypeset = run as Run & {
    typeset_matching_status?: PhaseStatus;
    typeset_inpainting_status?: PhaseStatus;
    typeset_rendering_status?: PhaseStatus;
  };

  const tsStatuses: TypesetStageStatuses = {
    matching:
      runWithTypeset.typeset_matching_status ??
      (typesetOutputExists ? "done" : "pending"),
    inpainting:
      runWithTypeset.typeset_inpainting_status ??
      (typesetOutputExists ? "done" : "pending"),
    rendering:
      runWithTypeset.typeset_rendering_status ??
      (typesetOutputExists ? "done" : "pending"),
  };

  return {
    legacyDone,
    analysisReady,
    typesetReady,
    typesetOutputExists,
    tsStatuses,
  };
}

export function canNavigateToPhase(
  phase: Phase,
  state: Pick<DerivedRunPhaseState, "analysisReady" | "typesetReady">,
): boolean {
  if (phase === "detection") return true;
  if (phase === "analysis") return state.analysisReady;

  return phase === "typeset_matching" ||
    phase === "typeset_inpainting" ||
    phase === "typeset_rendering"
    ? state.typesetReady
    : false;
}
