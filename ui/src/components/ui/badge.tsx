import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

/* Status is carried by an icon/label, not by colour alone. Done = plain ink:
   finished work is simply inked; blue = in progress; amber = needs attention. */
const badge = cva(
  "inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-1.5 py-px font-mono text-[11px] leading-4 font-medium uppercase tracking-wide",
  {
    variants: {
      variant: {
        default: "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
        pending: "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
        running: "border-[hsl(var(--accent2)/.45)] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2-soft))]",
        done: "border-[hsl(var(--text)/.25)] text-[hsl(var(--text))]",
        partial: "border-[hsl(var(--warning)/.6)] text-[hsl(var(--warning-deep))]",
        stale: "border-[hsl(var(--warning)/.6)] text-[hsl(var(--warning-deep))] border-dashed",
        cancelled: "border-[hsl(var(--border-strong))] text-[hsl(var(--text-muted))] border-dashed",
        failed: "border-[hsl(var(--danger)/.45)] text-[hsl(var(--danger))]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badge> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badge({ variant }), className)} {...props} />;
}
