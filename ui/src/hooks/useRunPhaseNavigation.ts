import { useCallback, useEffect, useRef, useState } from "react";
import type { Run } from "../lib/types";
import type { Phase } from "../features/phases/PhaseBar";
import { canNavigateToPhase, getDefaultPhase, type DerivedRunPhaseState } from "../lib/phase";

/**
 * Which phase tab is open. Follows the running phase automatically until the
 * user picks a tab; from then on the user's choice sticks for this run.
 */
export function useRunPhaseNavigation(run?: Run, derived?: DerivedRunPhaseState | null) {
  const [activePhase, setActivePhase] = useState<Phase>("detection");
  const initializedRunId = useRef<string | null>(null);
  const userPicked = useRef(false);

  useEffect(() => {
    if (!run || !derived) return;
    if (initializedRunId.current !== run.id) {
      initializedRunId.current = run.id;
      userPicked.current = false;
      setActivePhase(getDefaultPhase(run));
      return;
    }
    if (!userPicked.current) {
      setActivePhase(getDefaultPhase(run));
    } else {
      setActivePhase((cur) => (canNavigateToPhase(cur, derived) ? cur : getDefaultPhase(run)));
    }
  }, [derived, run]);

  const goToPhase = useCallback(
    (phase: Phase) => {
      if (!derived || !canNavigateToPhase(phase, derived)) return;
      userPicked.current = true;
      setActivePhase(phase);
    },
    [derived],
  );

  return { activePhase, setActivePhase, goToPhase };
}
