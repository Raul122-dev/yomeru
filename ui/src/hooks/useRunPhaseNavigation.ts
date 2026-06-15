import { useCallback, useEffect, useRef, useState } from "react";
import type { Run } from "../lib/types";
import type { Phase } from "../features/phases/PhaseBar";
import {
  canNavigateToPhase,
  getDefaultPhase,
  type DerivedRunPhaseState,
} from "../lib/phase";

export function useRunPhaseNavigation(
  run?: Run,
  derived?: DerivedRunPhaseState | null,
) {
  const [activePhase, setActivePhase] = useState<Phase>("detection");
  const initializedRunId = useRef<string | null>(null);
  const userManual = useRef(false);

  useEffect(() => {
    if (!run || !derived) return;

    if (initializedRunId.current !== run.id) {
      initializedRunId.current = run.id;
      userManual.current = false;
      setActivePhase(getDefaultPhase(run));
      return;
    }

    // Auto-navigate to running phase unless user manually picked a tab
    if (!userManual.current) {
      const best = getDefaultPhase(run);
      setActivePhase(best);
    } else {
      // If user tab is no longer valid, reset
      setActivePhase((current) =>
        canNavigateToPhase(current, derived) ? current : getDefaultPhase(run),
      );
    }
  }, [derived, run]);

  const goToPhase = useCallback(
    (phase: Phase) => {
      if (!derived) return;
      if (!canNavigateToPhase(phase, derived)) return;
      userManual.current = true;
      setActivePhase(phase);
      // Reset manual flag after a bit so auto-nav resumes on next phase change
      setTimeout(() => {
        userManual.current = false;
      }, 3000);
    },
    [derived],
  );

  return {
    activePhase,
    setActivePhase,
    goToPhase,
  };
}
