import type { Phase } from "../features/phases/PhaseBar";
import type { PhaseName, PhaseStatus, Run, TypesetStatus } from "./types";

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
  phaseStatuses: Record<Phase, PhaseStatus>;
}

const PHASE_ORDER: Phase[] = [
  "detection",
  "analysis",
  "matching",
  "inpainting",
  "rendering",
];

const UI_TO_API_PHASE: Record<Phase, PhaseName> = {
  detection: "detection",
  analysis: "analysis",
  matching: "matching",
  inpainting: "inpainting",
  rendering: "rendering",
};

export function isPhaseComplete(status: PhaseStatus) {
  return status === "done" || status === "partial";
}

export function getRunPhaseStatus(
  run: Run,
  phase: PhaseName,
  typesetOutputExists = false,
): PhaseStatus {
  const unifiedStatus = run.phase_status?.[phase];
  if (unifiedStatus) return unifiedStatus;

  switch (phase) {
    case "detection":
      return run.detection_status ?? "pending";
    case "analysis":
      return run.analysis_status ?? "pending";
    case "matching":
      return run.typeset_matching_status ??
        (typesetOutputExists ? "done" : "pending");
    case "inpainting":
      return run.typeset_inpainting_status ??
        (typesetOutputExists ? "done" : "pending");
    case "rendering":
      return run.typeset_rendering_status ??
        (typesetOutputExists ? "done" : "pending");
  }
}

export function getUiPhaseStatus(
  run: Run,
  phase: Phase,
  typesetOutputExists = false,
): PhaseStatus {
  return getRunPhaseStatus(run, UI_TO_API_PHASE[phase], typesetOutputExists);
}

function hasStarted(status: PhaseStatus) {
  return status !== "pending";
}

export function getDefaultPhase(run: Run): Phase {
  const statuses = Object.fromEntries(
    PHASE_ORDER.map((phase) => [phase, getUiPhaseStatus(run, phase)]),
  ) as Record<Phase, PhaseStatus>;

  for (const phase of PHASE_ORDER) {
    if (statuses[phase] === "running") return phase;
  }

  for (const phase of PHASE_ORDER) {
    if (statuses[phase] === "failed") return phase;
  }

  if (isPhaseComplete(statuses.inpainting)) return "rendering";
  if (isPhaseComplete(statuses.matching)) return "inpainting";
  if (isPhaseComplete(statuses.analysis)) return "matching";
  if (isPhaseComplete(statuses.detection)) return "analysis";

  return "detection";
}

export function getDerivedRunPhaseState(
  run: Run,
  typesetStatus?: TypesetStatus,
): DerivedRunPhaseState {
  const typesetOutputExists =
    typesetStatus?.status === "done" && (typesetStatus.pages?.length ?? 0) > 0;

  const phaseStatuses = Object.fromEntries(
    PHASE_ORDER.map((phase) => [
      phase,
      getUiPhaseStatus(run, phase, typesetOutputExists),
    ]),
  ) as Record<Phase, PhaseStatus>;

  const legacyDone = !run.phase_status && !run.detection_status && run.status === "done";
  const analysisReady = isPhaseComplete(phaseStatuses.detection);
  const typesetReady = isPhaseComplete(phaseStatuses.analysis);

  const tsStatuses: TypesetStageStatuses = {
    matching: phaseStatuses.matching,
    inpainting: phaseStatuses.inpainting,
    rendering: phaseStatuses.rendering,
  };

  return {
    legacyDone,
    analysisReady,
    typesetReady,
    typesetOutputExists,
    tsStatuses,
    phaseStatuses,
  };
}

export function canNavigateToPhase(
  phase: Phase,
  state: Pick<DerivedRunPhaseState, "phaseStatuses">,
): boolean {
  if (phase === "detection") return true;
  if (hasStarted(state.phaseStatuses[phase])) return true;

  const phaseIndex = PHASE_ORDER.indexOf(phase);
  return PHASE_ORDER.slice(0, phaseIndex).every((prevPhase) =>
    isPhaseComplete(state.phaseStatuses[prevPhase]),
  );
}
