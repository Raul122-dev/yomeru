import { cn } from "../../lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export function Input({
  className,
  label,
  hint,
  error,
  id,
  ...props
}: InputProps) {
  const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={cn(
          "h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 text-sm text-[hsl(var(--text))] placeholder:text-[hsl(var(--text-muted))] transition-colors",
          "focus:border-[hsl(var(--accent2))] focus:outline-none",
          error && "border-[hsl(var(--danger))]",
          className,
        )}
        {...props}
      />
      {hint && !error && (
        <p className="mt-1.5 text-xs text-[hsl(var(--text-muted))]">{hint}</p>
      )}
      {error && (
        <p className="mt-1.5 text-xs text-[hsl(var(--danger))]">{error}</p>
      )}
    </div>
  );
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
}

export function Select({
  className,
  label,
  id,
  children,
  ...props
}: SelectProps) {
  const selectId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={selectId}
          className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]"
        >
          {label}
        </label>
      )}
      <select
        id={selectId}
        className={cn(
          "h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 text-sm text-[hsl(var(--text))] transition-colors",
          "focus:border-[hsl(var(--accent2))] focus:outline-none",
          className,
        )}
        {...props}
      >
        {children}
      </select>
    </div>
  );
}
