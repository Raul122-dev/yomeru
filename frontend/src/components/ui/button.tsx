import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "bg-[hsl(var(--accent))] text-[hsl(var(--accent-fg))] hover:bg-[hsl(var(--accent)/.85)]",
        outline:
          "border border-[hsl(var(--border-strong))] text-[hsl(var(--text))] hover:bg-[hsl(var(--bg-subtle))]",
        ghost:
          "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] hover:text-[hsl(var(--text))]",
        danger:
          "border border-[hsl(var(--danger))] text-[hsl(var(--danger))] hover:bg-[hsl(var(--danger)/.1)]",
        link: "text-[hsl(var(--accent2))] underline-offset-4 hover:underline p-0 h-auto",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-7 px-3 text-xs",
        lg: "h-11 px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <button className={cn(button({ variant, size }), className)} {...props} />
  );
}

export const buttonVariants = button;
