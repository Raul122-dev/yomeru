import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

/* DESIGN.md: app/nav controls are 6px squares (button-primary-sm / button-ghost-sm). */
const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] text-sm font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-45 cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "bg-[hsl(var(--accent))] text-[hsl(var(--accent-fg))] hover:bg-[hsl(var(--accent)/.82)]",
        outline:
          "border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] text-[hsl(var(--text))] hover:border-[hsl(var(--border-strong))] hover:bg-[hsl(var(--bg-subtle))]",
        ghost:
          "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] hover:text-[hsl(var(--text))]",
        danger:
          "border border-[hsl(var(--danger)/.4)] text-[hsl(var(--danger))] hover:bg-[hsl(var(--danger)/.08)]",
        link: "text-[hsl(var(--accent2))] underline-offset-4 hover:underline p-0 h-auto",
      },
      size: {
        default: "h-8 px-3",
        sm: "h-7 px-2.5 text-xs",
        lg: "h-10 px-4",
        icon: "size-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return (
    <button type={type} className={cn(button({ variant, size }), className)} {...props} />
  );
}

export const buttonVariants = button;
