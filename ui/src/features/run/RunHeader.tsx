import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import type { Run } from "../../lib/types";

interface RunHeaderProps {
  run: Run;
}

export function RunHeader({ run }: RunHeaderProps) {
  const settings = (run as Run & { settings?: { language?: { source: string; target: string } } }).settings;
  const lang = settings?.language;
  return (
    <header className="relative overflow-hidden rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] px-5 py-4">
      <div aria-hidden className="screentone-fade pointer-events-none absolute inset-y-0 right-0 w-1/2 [transform:scaleX(-1)]" />
      <div className="relative flex items-center gap-3">
        <Link
          to="/"
          aria-label="Back to runs"
          className="rounded-[var(--radius-sm)] p-1 text-[hsl(var(--text-muted))] transition-colors hover:bg-[hsl(var(--bg-subtle))] hover:text-[hsl(var(--text))]"
        >
          <ArrowLeft size={16} />
        </Link>
        <div className="min-w-0">
          <h1 className="truncate text-xl leading-7">{run.name}</h1>
          <p className="font-mono text-xs text-[hsl(var(--text-muted))]">
            {run.total_pages} {run.total_pages === 1 ? "page" : "pages"} · {run.comic_format}
            {lang && ` · ${lang.source} → ${lang.target}`} · {run.model}
          </p>
        </div>
      </div>
    </header>
  );
}
