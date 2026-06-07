import { useCallback, useEffect, useState } from "react";
import type { Run } from "../../lib/api";
import type { Phase } from "../../components/PhaseBar";
import {
  canNavigateToPhase,
  getDefaultPhase,
  type DerivedRunPhaseState,
} from "../../lib/run-detail/phase";

export function useRunPhaseNavigation(
  run?: Run,
  derived?: DerivedRunPhaseState | null,
) {
  const [activePhase, setActivePhase] = useState<Phase>("detection");

  useEffect(() => {
    if (!run) return;
    setActivePhase(getDefaultPhase(run));
  }, [run?.status, run?.detection_status, run?.analysis_status]);

  const goToPhase = useCallback(
    (phase: Phase) => {
      if (!derived) return;
      if (!canNavigateToPhase(phase, derived)) return;
      setActivePhase(phase);
    },
    [derived],
  );

  return {
    activePhase,
    setActivePhase,
    goToPhase,
  };
}
