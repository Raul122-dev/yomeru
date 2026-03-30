import { Moon, Sun, Monitor } from "lucide-react";
import { useTheme } from "../lib/theme";
import { cn } from "../lib/utils";

const options = [
  { value: "light", icon: Sun, label: "Light" },
  { value: "dark", icon: Moon, label: "Dark" },
  { value: "system", icon: Monitor, label: "System" },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="flex items-center gap-0.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] p-0.5">
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          onClick={() => setTheme(value)}
          title={label}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded transition-colors",
            theme === value
              ? "bg-[hsl(var(--bg-surface))] text-[hsl(var(--text))] shadow-sm"
              : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
          )}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
}
