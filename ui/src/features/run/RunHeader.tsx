import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import type { Run } from "../../lib/types";

interface RunHeaderProps {
  run: Run;
}

export function RunHeader({ run }: RunHeaderProps) {
  return (
    <div className="flex items-center gap-3">
      <Link
        to="/"
        className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
      >
        <ArrowLeft size={16} />
      </Link>

      <div>
        <h1 className="text-xl font-semibold leading-tight">{run.name}</h1>
        <p className="text-[11px] text-[hsl(var(--text-muted))]">
          {run.model} · {run.comic_format} · {run.total_pages} pages
        </p>
      </div>
    </div>
  );
}
