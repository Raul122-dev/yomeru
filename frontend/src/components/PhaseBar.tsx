/**
 * PhaseBar — two-group phase navigator.
 *
 * Group 1 "Image Analysis": Detection → Analysis
 * Group 2 "Typesetting":    S3 Match → S4 Inpaint → S5 Render
 *
 * Each sub-phase is independently clickable.
 * Active phase is highlighted. Status icons reflect backend state.
 */
import {
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
  ChevronRight,
} from "lucide-react";
import { cn } from "../lib/utils";
import type { Run } from "../lib/api";

export type Phase =
  | "detection"
  | "analysis"
  | "typeset_matching"
  | "typeset_inpainting"
  | "typeset_rendering";

type PhaseStatus = "pending" | "running" | "done" | "failed";

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

function statusIcon(s: PhaseStatus, size = 11) {
  switch (s) {
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
    default:
      return (
        <Circle
          size={size}
          className="text-[hsl(var(--text-muted)/.35)] shrink-0"
        />
      );
  }
}

function statusLabel(s: PhaseStatus) {
  return { pending: "", running: "…", done: "✓", failed: "!" }[s];
}

export function buildGroups(
  run: Run,
  typesetStageStatuses: {
    matching: PhaseStatus;
    inpainting: PhaseStatus;
    rendering: PhaseStatus;
  },
  typesetOutputExists: boolean,
): Group[] {
  const detDone = run.detection_status === "done";
  const anaDone = run.analysis_status === "done";
  // Legacy runs without sub-statuses
  const legacyDone = !run.detection_status && run.status === "done";

  return [
    {
      label: "Image Analysis",
      phases: [
        {
          key: "detection",
          label: "Detection",
          status: (run.detection_status ?? "pending") as PhaseStatus,
          clickable: true,
        },
        {
          key: "analysis",
          label: "Analysis",
          status: (run.analysis_status ?? "pending") as PhaseStatus,
          clickable: detDone || legacyDone,
        },
      ],
    },
    {
      label: "Typesetting",
      phases: [
        {
          key: "typeset_matching",
          label: "S3 Match",
          status: typesetStageStatuses.matching,
          clickable: anaDone || legacyDone,
        },
        {
          key: "typeset_inpainting",
          label: "S4 Inpaint",
          status: typesetStageStatuses.inpainting,
          clickable: anaDone || legacyDone,
        },
        {
          key: "typeset_rendering",
          label: "S5 Render",
          status: typesetStageStatuses.rendering,
          clickable: anaDone || legacyDone,
        },
      ],
    },
  ];
}

interface PhaseBarProps {
  run: Run;
  typesetStageStatuses: {
    matching: PhaseStatus;
    inpainting: PhaseStatus;
    rendering: PhaseStatus;
  };
  typesetOutputExists: boolean;
  activePhase: Phase;
  onPhaseClick: (phase: Phase) => void;
}

export function PhaseBar({
  run,
  typesetStageStatuses,
  typesetOutputExists,
  activePhase,
  onPhaseClick,
}: PhaseBarProps) {
  const groups = buildGroups(run, typesetStageStatuses, typesetOutputExists);

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] overflow-hidden">
      <div className="flex items-stretch divide-x divide-[hsl(var(--border))]">
        {groups.map((group, gi) => (
          <div key={group.label} className="flex-1 min-w-0">
            {/* group label */}
            <div className="px-3 py-1 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle)/.8)]">
              <p className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted)/.5)]">
                {group.label}
              </p>
            </div>
            {/* sub-phases */}
            <div className="flex items-stretch divide-x divide-[hsl(var(--border)/.4)]">
              {group.phases.map((phase, pi) => (
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
