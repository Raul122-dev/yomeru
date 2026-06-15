/**
 * PhaseBar — two-group phase navigator.
 *
 * Group 1 "Image Analysis": Detection → Analysis
 * Group 2 "Typesetting":    Matching → Inpainting → Rendering
 */
import { AlertCircle, CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { PhaseStatus, Run } from "../../lib/types";
import { cn } from "../../lib/utils";
import { getUiPhaseStatus, isPhaseComplete } from "../../lib/phase";

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

const PHASE_ORDER: Phase[] = [
  "detection",
  "analysis",
  "matching",
  "inpainting",
  "rendering",
];

function hasStarted(status: PhaseStatus) {
  return status !== "pending";
}

function statusIcon(status: PhaseStatus, size = 11) {
  switch (status) {
    case "done":
      return (
        <CheckCircle2
          size={size}
          className="text-[hsl(var(--success))] shrink-0"
        />
      );
    case "running":
      return (
        <Loader2
          size={size}
          className="text-[hsl(var(--accent2))] animate-spin shrink-0"
        />
      );
    case "failed":
      return (
        <XCircle size={size} className="text-[hsl(var(--danger))] shrink-0" />
      );
    case "partial":
      return (
        <AlertCircle
          size={size}
          className="text-[hsl(var(--warning))] shrink-0"
        />
      );
    default:
      return (
        <Circle
          size={size}
          className="text-[hsl(var(--text-muted)/.35)] shrink-0"
        />
      );
  }
}

function statusLabel(status: PhaseStatus) {
  return {
    pending: "",
    running: "…",
    done: "✓",
    failed: "!",
    partial: "~",
  }[status];
}

function getPhaseStatuses(run: Run): Record<Phase, PhaseStatus> {
  return {
    detection: getUiPhaseStatus(run, "detection"),
    analysis: getUiPhaseStatus(run, "analysis"),
    matching: getUiPhaseStatus(run, "matching"),
    inpainting: getUiPhaseStatus(run, "inpainting"),
    rendering: getUiPhaseStatus(run, "rendering"),
  };
}

function isPhaseClickable(
  phase: Phase,
  statuses: Record<Phase, PhaseStatus>,
): boolean {
  if (phase === "detection") return true;
  if (hasStarted(statuses[phase])) return true;

  const phaseIndex = PHASE_ORDER.indexOf(phase);
  return PHASE_ORDER.slice(0, phaseIndex).every((prevPhase) =>
    isPhaseComplete(statuses[prevPhase]),
  );
}

export function buildGroups(run: Run): Group[] {
  const statuses = getPhaseStatuses(run);

  return [
    {
      label: "Image Analysis",
      phases: [
        {
          key: "detection",
          label: "Detection",
          status: statuses.detection,
          clickable: isPhaseClickable("detection", statuses),
        },
        {
          key: "analysis",
          label: "Analysis",
          status: statuses.analysis,
          clickable: isPhaseClickable("analysis", statuses),
        },
      ],
    },
    {
      label: "Typesetting",
      phases: [
        {
          key: "matching",
          label: "Matching",
          status: statuses.matching,
          clickable: isPhaseClickable("matching", statuses),
        },
        {
          key: "inpainting",
          label: "Inpainting",
          status: statuses.inpainting,
          clickable: isPhaseClickable("inpainting", statuses),
        },
        {
          key: "rendering",
          label: "Rendering",
          status: statuses.rendering,
          clickable: isPhaseClickable("rendering", statuses),
        },
      ],
    },
  ];
}

interface PhaseBarProps {
  run: Run;
  activePhase: Phase;
  onPhaseClick: (phase: Phase) => void;
}

export function PhaseBar({ run, activePhase, onPhaseClick }: PhaseBarProps) {
  const groups = buildGroups(run);

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] overflow-hidden">
      <div className="flex items-stretch divide-x divide-[hsl(var(--border))]">
        {groups.map((group) => (
          <div key={group.label} className="flex-1 min-w-0">
            <div className="px-3 py-1 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle)/.8)]">
              <p className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted)/.5)]">
                {group.label}
              </p>
            </div>
            <div className="flex items-stretch divide-x divide-[hsl(var(--border)/.4)]">
              {group.phases.map((phase) => (
                <button
                  key={phase.key}
                  onClick={() => phase.clickable && onPhaseClick(phase.key)}
                  disabled={!phase.clickable}
                  className={cn(
                    "flex-1 flex items-center gap-1.5 px-3 py-2 text-[11px] transition-colors min-w-0",
                    "disabled:cursor-not-allowed",
                    phase.key === activePhase
                      ? "bg-[hsl(var(--bg))] text-[hsl(var(--text))] font-medium"
                      : phase.clickable
                        ? "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg)/.6)] hover:text-[hsl(var(--text))]"
                        : "text-[hsl(var(--text-muted)/.35)]",
                  )}
                >
                  {statusIcon(phase.status)}
                  <span className="truncate">{phase.label}</span>
                  {phase.status !== "pending" && (
                    <span
                      className={cn(
                        "ml-auto text-[9px] shrink-0",
                        phase.status === "done" && "text-[hsl(var(--success))]",
                        phase.status === "running" &&
                          "text-[hsl(var(--accent2))]",
                        phase.status === "failed" &&
                          "text-[hsl(var(--danger))]",
                        phase.status === "partial" &&
                          "text-[hsl(var(--warning))]",
                      )}
                    >
                      {statusLabel(phase.status)}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
