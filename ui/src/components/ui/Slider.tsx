import { cn } from "../../lib/utils";

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  hint?: string;
  format?: (v: number) => string;
  onChange: (v: number) => void;
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  hint,
  format,
  onChange,
}: SliderProps) {
  const display = format
    ? format(value)
    : Number.isInteger(step)
      ? String(value)
      : value.toFixed(2);
  return (
    <div className="space-y-0.5">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] text-[hsl(var(--text-muted))]">
          {label}
        </span>
        <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
          {display}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1 accent-[hsl(var(--accent2))] cursor-pointer"
      />
      {hint && (
        <p className="text-[9px] text-[hsl(var(--text-muted))] leading-tight">
          {hint}
        </p>
      )}
    </div>
  );
}
