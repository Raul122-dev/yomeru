import { describe, expect, it } from "vitest";
import { canNavigateToPhase, getDefaultPhase, getDerivedRunPhaseState } from "./phase";
import type { Run } from "./types";

const run = (phase_status: Record<string, string>) => ({ id: "r", phase_status } as unknown as Run);

describe("run phase state", () => {
  it("opens the phase that is running, then the failed one, then the next to do", () => {
    expect(getDefaultPhase(run({ detection: "done", analysis: "running" }))).toBe("analysis");
    expect(getDefaultPhase(run({ detection: "done", analysis: "done", matching: "failed" }))).toBe("matching");
    expect(getDefaultPhase(run({ detection: "done", analysis: "partial" }))).toBe("matching");
    expect(getDefaultPhase(run({}))).toBe("detection");
  });

  it("a phase can be opened once every earlier one is complete", () => {
    const state = getDerivedRunPhaseState(run({ detection: "done", analysis: "pending" }));
    expect(canNavigateToPhase("analysis", state)).toBe(true);
    expect(canNavigateToPhase("matching", state)).toBe(false);
    expect(state.analysisReady).toBe(true);
    expect(state.typesetReady).toBe(false);
  });
});
