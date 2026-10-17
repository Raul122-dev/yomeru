import { cn } from "../../lib/utils";

/* DESIGN.md feature-card: elevated surface + 1px hairline, 12px radius, no shadow. */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] p-5",
        className,
      )}
      {...props}
    />
  );
}
