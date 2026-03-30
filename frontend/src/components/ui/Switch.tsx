import * as RadixSwitch from "@radix-ui/react-switch";
import { cn } from "../../lib/utils";

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
}: SwitchProps) {
  return (
    <label
      className={cn(
        "flex items-center justify-between gap-3 py-1.5 cursor-pointer select-none",
        disabled && "opacity-50 cursor-not-allowed",
      )}
    >
      <div className="min-w-0">
        <span className="text-[11px] text-[hsl(var(--text))]">{label}</span>
        {hint && (
          <p className="text-[10px] text-[hsl(var(--text-muted))] leading-snug">
            {hint}
          </p>
        )}
      </div>
      <RadixSwitch.Root
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={cn(
          "relative inline-flex h-4 w-7 shrink-0 cursor-pointer rounded-full border-2 border-transparent",
          "transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--accent2))] focus-visible:ring-offset-2",
          checked
            ? "bg-[hsl(var(--accent2))]"
            : "bg-[hsl(var(--border-strong))]",
        )}
      >
        <RadixSwitch.Thumb
          className={cn(
            "pointer-events-none block h-3 w-3 rounded-full bg-white shadow-sm",
            "transition-transform duration-150",
            checked ? "translate-x-3" : "translate-x-0",
          )}
        />
      </RadixSwitch.Root>
    </label>
  );
}
