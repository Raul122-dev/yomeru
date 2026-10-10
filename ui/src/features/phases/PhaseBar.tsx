/**
 * PhaseBar — the run's pipeline rail.
 *
 * Five steps in order, grouped as Image analysis (detection, analysis) and
 * Typesetting (matching, inpainting, rendering). A step can be opened once it
 * has started or every earlier step is complete.
 */
import type { PhaseStatus, Run } from "../../lib/types";
import { cn } from "../../lib/utils";
import { getUiPhaseStatus, isPhaseComplete } from "../../lib/phase";
import { STATUS_HINT, STATUS_LABEL, StatusIcon } from "../../lib/status";

export type Phase =
  | "detection"
  | "analysis"
  | "matching"
  | "inpainting"
  | "rendering";

interface SubPhase {
  key: Phase;
  label: string;
  status: PhaseStatus;
  clickable: boolean;
}

interface Group {
  label: string;
  phases: SubPhase[];
}

const PHASE_ORDER: Phase[] = ["detection", "analysis", "matching", "inpainting", "rendering"];
const LABELS: Record<Phase, string> = {
  detection: "Detection",
  analysis: "Analysis",
  matching: "Matching",
  inpainting: "Inpainting",
  rendering: "Rendering",
};

function getPhaseStatuses(run: Run): Record<Phase, PhaseStatus> {
  return Object.fromEntries(PHASE_ORDER.map((p) => [p, getUiPhaseStatus(run, p)])) as Record<
    Phase,
    PhaseStatus
  >;
}

function isPhaseClickable(phase: Phase, statuses: Record<Phase, PhaseStatus>): boolean {
  if (phase === "detection" || statuses[phase] !== "pending") return true;
  return PHASE_ORDER.slice(0, PHASE_ORDER.indexOf(phase)).every((p) => isPhaseComplete(statuses[p]));
}

export function buildGroups(run: Run): Group[] {
  const statuses = getPhaseStatuses(run);
  const sub = (key: Phase): SubPhase => ({
    key,
    label: LABELS[key],
    status: statuses[key],
    clickable: isPhaseClickable(key, statuses),
  });
  return [
    { label: "Image analysis", phases: [sub("detection"), sub("analysis")] },
    { label: "Typesetting", phases: [sub("matching"), sub("inpainting"), sub("rendering")] },
  ];
}

interface PhaseBarProps {
  run: Run;
  activePhase: Phase;
  onPhaseClick: (phase: Phase) => void;
}

export function PhaseBar({ run, activePhase, onPhaseClick }: PhaseBarProps) {
  const groups = buildGroups(run);
  let n = 0;
  return (
    <nav aria-label="Pipeline" className="flex flex-wrap items-end gap-x-6 gap-y-3">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-1.5">
          <span className="eyebrow">{group.label}</span>
          <div className="flex items-center rounded-[var(--radius-sm)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] p-0.5">
            {group.phases.map((phase) => {
              n += 1;
              const active = phase.key === activePhase;
              return (
                <button
                  key={phase.key}
                  onClick={() => phase.clickable && onPhaseClick(phase.key)}
                  disabled={!phase.clickable}
                  aria-current={active ? "step" : undefined}
                  title={`${phase.label}: ${STATUS_LABEL[phase.status]}${STATUS_HINT[phase.status] ? ` — ${STATUS_HINT[phase.status]}` : ""}`}
                  className={cn(
                    "flex h-8 items-center gap-2 rounded-[4px] px-3 text-sm transition-colors",
                    "disabled:cursor-not-allowed disabled:text-[hsl(var(--text-faint))]",
                    active
                      ? "bg-[hsl(var(--text))] text-[hsl(var(--bg))]"
                      : "text-[hsl(var(--text-body))] hover:bg-[hsl(var(--bg-subtle))] hover:text-[hsl(var(--text))]",
                  )}
                >
                  <span className={cn("font-mono text-[11px]", active ? "opacity-60" : "text-[hsl(var(--text-faint))]")}>
                    {n}
                  </span>
                  {phase.label}
                  <StatusIcon
                    status={phase.status}
                    className={cn(active && "!text-[hsl(var(--bg))]")}
                  />
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}
