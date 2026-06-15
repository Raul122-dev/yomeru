import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badge = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]",
        pending:
          "border-[hsl(var(--border-strong))] text-[hsl(var(--text-muted))]",
        running:
          "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)]",
        done: "border-[hsl(var(--success))] text-[hsl(var(--success))] bg-[hsl(var(--success)/.08)]",
        failed:
          "border-[hsl(var(--danger))] text-[hsl(var(--danger))] bg-[hsl(var(--danger)/.08)]",
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
