import { useState, useRef, useEffect } from "react";
import { cn } from "../../lib/utils";
import { ChevronDown, Eye, EyeOff } from "lucide-react";

interface ComboboxItem {
  id: string;
  name: string;
  vision?: boolean | null;
}

interface ComboboxProps {
  label?: string;
  hint?: string;
  value: string;
  items: ComboboxItem[];
  loading?: boolean;
  placeholder?: string;
  showVisionBadge?: boolean;
  onChange: (value: string) => void;
}

export function Combobox({
  label,
  hint,
  value,
  items,
  loading,
  placeholder,
  showVisionBadge = false,
  onChange,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = search
    ? items.filter((i) => i.name.toLowerCase().includes(search.toLowerCase()))
    : items;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        listRef.current &&
        !listRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative w-full">
      {label && (
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
          {label}
        </label>
      )}
      <div className="relative">
        <input
          ref={inputRef}
          className={cn(
            "h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 pr-8 text-sm text-[hsl(var(--text))] placeholder:text-[hsl(var(--text-muted))] transition-colors",
            "focus:border-[hsl(var(--accent2))] focus:outline-none",
          )}
          value={open ? search : value}
          placeholder={placeholder}
          onChange={(e) => {
            setSearch(e.target.value);
            if (!open) setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setSearch("");
          }}
        />
        <button
          type="button"
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
          onClick={() => {
            setOpen(!open);
            if (!open) inputRef.current?.focus();
          }}
          tabIndex={-1}
        >
          <ChevronDown size={14} />
        </button>
      </div>
      {hint && (
        <p className="mt-1.5 text-xs text-[hsl(var(--text-muted))]">{hint}</p>
      )}

      {open && (
        <div
          ref={listRef}
          className="absolute z-50 mt-1 max-h-56 w-full overflow-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] shadow-lg"
        >
          {loading ? (
            <p className="p-3 text-xs text-[hsl(var(--text-muted))]">
              loading models…
            </p>
          ) : filtered.length === 0 ? (
            <p className="p-3 text-xs text-[hsl(var(--text-muted))]">
              {search ? "no matches" : "no models available"}
            </p>
          ) : (
            filtered.map((item) => (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors",
                  "hover:bg-[hsl(var(--bg-subtle))]",
                  item.id === value && "bg-[hsl(var(--bg-subtle))] font-medium",
                )}
                onClick={() => {
                  onChange(item.id);
                  setOpen(false);
                  setSearch("");
                }}
              >
                <span className="flex-1 truncate">{item.name}</span>
                {showVisionBadge && item.vision === true && (
                  <Eye size={12} className="shrink-0 text-green-500" />
                )}
                {showVisionBadge && item.vision === false && (
                  <EyeOff size={12} className="shrink-0 text-red-400" />
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
