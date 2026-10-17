import { AlertTriangle, Ban, Check, Circle, Loader2, RotateCcw, X } from "lucide-react";
import type { PhaseStatus } from "./types";
import { Badge } from "../components/ui/badge";
import { cn } from "./utils";

/** One vocabulary for phase status across the app. */
export const STATUS_LABEL: Record<PhaseStatus, string> = {
  pending: "Pending",
  running: "Running",
  done: "Done",
  partial: "Partial",
  failed: "Failed",
  stale: "Outdated",
  cancelled: "Cancelled",
};

export const STATUS_HINT: Partial<Record<PhaseStatus, string>> = {
  partial: "Some pages failed or only some pages were run",
  stale: "An earlier phase changed after this one ran — run it again",
  cancelled: "Stopped before finishing",
};

export function StatusIcon({ status, className }: { status: PhaseStatus; className?: string }) {
  const c = cn("size-3.5 shrink-0", className);
  switch (status) {
    case "done":
      return <Check className={cn(c, "text-[hsl(var(--text))]")} strokeWidth={2.5} />;
    case "running":
      return <Loader2 className={cn(c, "animate-spin text-[hsl(var(--accent2))]")} />;
    case "failed":
      return <X className={cn(c, "text-[hsl(var(--danger))]")} strokeWidth={2.5} />;
    case "partial":
      return <AlertTriangle className={cn(c, "text-[hsl(var(--warning-deep))]")} />;
    case "stale":
      return <RotateCcw className={cn(c, "text-[hsl(var(--warning-deep))]")} />;
    case "cancelled":
      return <Ban className={cn(c, "text-[hsl(var(--text-muted))]")} />;
    default:
      return <Circle className={cn(c, "text-[hsl(var(--text-faint))]")} />;
  }
}

export function StatusBadge({ status }: { status: PhaseStatus }) {
  return (
    <Badge variant={status} title={STATUS_HINT[status]}>
      <StatusIcon status={status} className="size-3" />
      {STATUS_LABEL[status]}
    </Badge>
  );
}
