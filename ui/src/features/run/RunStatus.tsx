/**
 * RunStatus — the run as a whole, next to the phase rail: all done / work
 * pending / failed / running, with the one action that moves it forward
 * ("Run pending phases" from the first phase that isn't complete).
 * Per-phase status stays on the rail itself.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, Play, XCircle } from "lucide-react";
import { startAllPhases } from "../../lib/api";
import type { PhaseStatus, Run } from "../../lib/types";
import { getUiPhaseStatus } from "../../lib/phase";
import { Button } from "../../components/ui/button";
import { LABELS, PHASE_ORDER, type Phase } from "../phases/PhaseBar";

export type RunState =
  | { kind: "running"; phase: Phase }
  | { kind: "failed"; phase: Phase; error?: string | null }
  | { kind: "pending"; from: Phase; count: number; reason: string }
  | { kind: "done" };

export function runState(run: Run): RunState {
  const st = Object.fromEntries(PHASE_ORDER.map((p) => [p, getUiPhaseStatus(run, p)])) as Record<Phase, PhaseStatus>;
  const running = PHASE_ORDER.find((p) => st[p] === "running");
  if (running) return { kind: "running", phase: running };
  const failed = PHASE_ORDER.find((p) => st[p] === "failed");
  if (failed) return { kind: "failed", phase: failed, error: run.error };
  const todo = PHASE_ORDER.filter((p) => st[p] !== "done");
  if (!todo.length) return { kind: "done" };
  const from = todo[0];
  const s = st[from];
  // what made it pending: the last complete phase before it changed after it ran
  const before = PHASE_ORDER.slice(0, PHASE_ORDER.indexOf(from)).reverse().find((p) => st[p] === "done");
  const reason =
    s === "stale" ? `${before ? LABELS[before] : "An earlier step"} changed after ${LABELS[from]} ran`
    : s === "partial" ? `${LABELS[from]} finished only some pages`
    : s === "cancelled" ? `${LABELS[from]} was stopped`
    : `${LABELS[from]} hasn't run yet`;
  return { kind: "pending", from, count: todo.length, reason };
}

export function RunStatus({ run }: { run: Run }) {
  const qc = useQueryClient();
  const state = runState(run);
  const go = useMutation({
    mutationFn: (from: Phase) => startAllPhases(run.id, undefined, from),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["run", run.id] }),
  });

  if (state.kind === "done") {
    return (
      <span className="flex items-center gap-1.5 text-xs text-[hsl(var(--text-muted))]">
        <CheckCircle2 size={14} className="text-[hsl(var(--success,var(--text)))]" /> All steps done
      </span>
    );
  }
  if (state.kind === "running") {
    return (
      <span className="flex items-center gap-1.5 text-xs text-[hsl(var(--text-muted))]">
        <Loader2 size={14} className="animate-spin text-[hsl(var(--accent2))]" /> Running {LABELS[state.phase]}…
      </span>
    );
  }
  const failed = state.kind === "failed";
  const from = failed ? state.phase : state.from;
  return (
    <div className="flex items-center gap-2">
      <span className="flex min-w-0 items-start gap-1.5 text-xs" title={failed ? state.error ?? undefined : state.reason}>
        {failed ? (
          <XCircle size={14} className="mt-px shrink-0 text-[hsl(var(--danger))]" />
        ) : (
          <AlertTriangle size={14} className="mt-px shrink-0 text-[hsl(var(--warning-deep))]" />
        )}
        <span className="min-w-0">
          <span className="font-medium">
            {failed ? `${LABELS[state.phase]} failed` : `${state.count} step${state.count > 1 ? "s" : ""} pending`}
          </span>
          <span className="block max-w-[15rem] truncate text-[hsl(var(--text-muted))]">
            {failed ? state.error || "See the step for details" : state.reason}
          </span>
        </span>
      </span>
      <Button size="sm" variant={failed ? "outline" : "default"} disabled={go.isPending}
              onClick={() => go.mutate(from)} title={`Runs ${LABELS[from]} and every step after it`}>
        <Play size={12} /> {failed ? `Retry from ${LABELS[from]}` : "Run pending steps"}
      </Button>
    </div>
  );
}
