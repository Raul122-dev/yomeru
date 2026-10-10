/**
 * Shared chrome for every phase view: header with status, run / run-again /
 * cancel, progress, and contextual notices (outdated, cancelled, blocked).
 */
import { useMutation } from "@tanstack/react-query";
import { Loader2, Play, RotateCcw, Square } from "lucide-react";
import { toast } from "sonner";
import { cancelRun } from "../../lib/api";
import type { PhaseStatus } from "../../lib/types";
import { StatusBadge } from "../../lib/status";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

export interface PhaseHeaderProps {
  runId: string;
  title: string;
  description: string;
  status: PhaseStatus;
  canRun: boolean;
  blockedReason?: string;
  onRun: () => void;
  processed?: number;
  total?: number;
  children?: React.ReactNode;
}

export function PhaseHeader({
  runId, title, description, status, canRun, blockedReason, onRun, processed = 0, total = 0, children,
}: PhaseHeaderProps) {
  const running = status === "running";
  const ran = status !== "pending";
  const cancel = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => toast("Stopping after the current page…"),
  });
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;

  return (
    <section className="rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h2 className="text-base">{title}</h2>
            <StatusBadge status={status} />
          </div>
          <p className="mt-0.5 text-sm text-[hsl(var(--text-muted))]">{description}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {running ? (
            <Button variant="outline" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              <Square size={11} fill="currentColor" /> Stop
            </Button>
          ) : (
            <Button
              size="sm"
              variant={status === "stale" || !ran ? "default" : "outline"}
              onClick={onRun}
              disabled={!canRun}
              title={!canRun ? blockedReason : undefined}
            >
              {ran ? <RotateCcw size={12} /> : <Play size={12} />}
              {ran ? `Run ${title.toLowerCase()} again` : `Run ${title.toLowerCase()}`}
            </Button>
          )}
        </div>
      </div>

      {running && (
        <div className="border-t border-[hsl(var(--border))] px-5 py-3">
          <div className="mb-1.5 flex items-center justify-between font-mono text-xs text-[hsl(var(--text-muted))]">
            <span className="flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin text-[hsl(var(--accent2))]" />
              {total > 0 ? `${processed} / ${total} pages` : "starting…"}
            </span>
            <span>{pct}%</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-[hsl(var(--bg-subtle))]" role="progressbar"
               aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-[hsl(var(--accent2))] transition-all duration-500" style={{ width: `${Math.max(pct, 2)}%` }} />
          </div>
        </div>
      )}

      {status === "stale" && <Notice tone="warn">An earlier phase changed after this one ran. Run it again to bring the pages up to date.</Notice>}
      {status === "cancelled" && <Notice>Stopped before finishing. Run it again to complete every page.</Notice>}
      {status === "partial" && <Notice tone="warn">Some pages failed or were not processed.</Notice>}
      {!canRun && !running && blockedReason && <Notice>{blockedReason}</Notice>}
      {children}
    </section>
  );
}

function Notice({ children, tone }: { children: React.ReactNode; tone?: "warn" }) {
  return (
    <p className={cn(
      "border-t border-[hsl(var(--border))] px-5 py-2.5 text-sm",
      tone === "warn" ? "text-[hsl(var(--warning-deep))]" : "text-[hsl(var(--text-muted))]",
    )}>
      {children}
    </p>
  );
}

export interface StripItem {
  page: number;
  filename: string;
  src: string;
  meta?: React.ReactNode;
  flag?: "warn" | "error";
}

/** Portrait filmstrip of pages; the selected page has the blue edit mark. */
export function PageStrip({ items, selected, onSelect }: {
  items: StripItem[];
  selected: number | null;
  onSelect: (page: number) => void;
}) {
  return (
    <div
      className="scroll-strip -mx-1 flex gap-2.5 overflow-x-auto px-1 pb-2 pt-1"
      role="listbox"
      aria-label="Pages"
      aria-orientation="horizontal"
    >
      {items.map((it) => {
        const active = it.page === selected;
        return (
          <button
            key={it.page}
            role="option"
            aria-selected={active}
            onClick={() => onSelect(it.page)}
            className={cn(
              "group w-[132px] shrink-0 rounded-[var(--radius-sm)] p-1 text-left transition-colors",
              active ? "bg-[hsl(var(--accent2-soft))] ring-2 ring-[hsl(var(--accent2))]" : "hover:bg-[hsl(var(--bg-subtle))]",
            )}
          >
            <div className="relative aspect-[5/7] overflow-hidden rounded-[4px] border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
              <img src={it.src} alt={`page ${it.page}`} loading="lazy" decoding="async"
                   className="size-full object-cover object-top" />
              {it.flag && (
                <span className={cn("absolute right-1 top-1 size-2 rounded-full",
                  it.flag === "error" ? "bg-[hsl(var(--danger))]" : "bg-[hsl(var(--warning))]")} />
              )}
            </div>
            <div className="mt-1.5 flex items-baseline justify-between gap-1 px-0.5">
              <span className="font-mono text-xs font-medium">p{String(it.page).padStart(2, "0")}</span>
              <span className="truncate font-mono text-[11px] text-[hsl(var(--text-muted))]">{it.meta}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function Panel({ title, aside, children, className }: {
  title?: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] p-5", className)}>
      {(title || aside) && (
        <div className="mb-4 flex items-baseline justify-between gap-3">
          {title && <h3 className="text-sm">{title}</h3>}
          {aside && <div className="font-mono text-xs text-[hsl(var(--text-muted))]">{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="screentone-fade rounded-[var(--radius-md)] border border-dashed border-[hsl(var(--border-strong))] px-6 py-10 text-sm text-[hsl(var(--text-muted))]">
      {children}
    </div>
  );
}

export function Label({ children }: { children: React.ReactNode }) {
  return <p className="eyebrow mb-2">{children}</p>;
}
