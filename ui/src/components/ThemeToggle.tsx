import { Moon, Sun, Monitor } from "lucide-react";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/utils";

const options = [
  { value: "light", icon: Sun, label: "Light theme" },
  { value: "dark", icon: Moon, label: "Dark theme" },
  { value: "system", icon: Monitor, label: "Follow system theme" },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className="flex items-center gap-0.5 rounded-[var(--radius-sm)] border border-[hsl(var(--border))] p-0.5">
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          role="radio"
          aria-checked={theme === value}
          aria-label={label}
          title={label}
          onClick={() => setTheme(value)}
          className={cn(
            "grid size-6 place-items-center rounded-[4px] transition-colors",
            theme === value
              ? "bg-[hsl(var(--bg-surface))] text-[hsl(var(--text))] shadow-[0_0_0_1px_hsl(var(--border))]"
              : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
          )}
        >
          <Icon size={12} />
        </button>
      ))}
    </div>
  );
}
