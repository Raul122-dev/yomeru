import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Trash2,
  Clock,
  ChevronRight,
  Search,
  ArrowUpDown,
  X,
} from "lucide-react";
import { listRuns, deleteRun, type Run } from "../lib/api";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { cn } from "../lib/utils";

// ── sort options ───────────────────────────────────────────────────────────────

type SortKey = "newest" | "oldest" | "name" | "status";

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "newest first" },
  { key: "oldest", label: "oldest first" },
  { key: "name", label: "name A→Z" },
  { key: "status", label: "status" },
];

function sortRuns(runs: Run[], sort: SortKey): Run[] {
  return [...runs].sort((a, b) => {
    switch (sort) {
      case "newest":
        return (
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
      case "oldest":
        return (
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
      case "name":
        return a.name.localeCompare(b.name);
      case "status": {
        const order = { running: 0, pending: 1, done: 2, failed: 3 };
        return (order[a.status] ?? 9) - (order[b.status] ?? 9);
      }
    }
  });
}

// ── RunCard ────────────────────────────────────────────────────────────────────

function RunCard({ run, query }: { run: Run; query: string }) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => deleteRun(run.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const pct =
    run.total_pages > 0
      ? Math.round((run.processed_pages / run.total_pages) * 100)
      : 0;
  const date = new Date(run.created_at).toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });

  // highlight matching query in name
  const highlightedName = useMemo(() => {
    if (!query) return <span>{run.name}</span>;
    const idx = run.name.toLowerCase().indexOf(query.toLowerCase());
    if (idx === -1) return <span>{run.name}</span>;
    return (
      <>
        {run.name.slice(0, idx)}
        <mark className="bg-[hsl(var(--accent)/.3)] text-[hsl(var(--text))] rounded-sm px-0.5">
          {run.name.slice(idx, idx + query.length)}
        </mark>
        {run.name.slice(idx + query.length)}
      </>
    );
  }, [run.name, query]);

  return (
    <Card className="transition-shadow hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              to={`/runs/${run.id}`}
              className="truncate text-sm font-medium hover:text-[hsl(var(--accent))] transition-colors"
            >
              {highlightedName}
            </Link>
            <Badge variant={run.status}>{run.status}</Badge>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--text-muted))]">
            <span className="font-mono">{run.model}</span>
            <span>·</span>
            <span>{run.comic_format}</span>
            <span>·</span>
            <span className="flex items-center gap-1">
              <Clock size={11} />
              {date}
            </span>
            {run.total_pages > 0 && (
              <>
                <span>·</span>
                <span>{run.total_pages}p</span>
              </>
            )}
          </div>
          {run.status === "running" && (
            <div className="mt-2">
              <div className="h-1 w-full overflow-hidden rounded-full bg-[hsl(var(--bg-subtle))]">
                <div
                  className="h-full rounded-full bg-[hsl(var(--accent2))] transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-[hsl(var(--text-muted))]">
                {run.processed_pages}/{run.total_pages} pages
              </p>
            </div>
          )}
          {run.error && (
            <p className="mt-1.5 text-xs text-[hsl(var(--danger))]">
              {run.error}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => del.mutate()}
            className="hover:text-[hsl(var(--danger))]"
          >
            <Trash2 size={14} />
          </Button>
          <Link
            to={`/runs/${run.id}`}
            className="flex h-9 w-9 items-center justify-center rounded-md text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] transition-colors"
          >
            <ChevronRight size={14} />
          </Link>
        </div>
      </div>
    </Card>
  );
}

// ── Dashboard ──────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const [showSort, setShowSort] = useState(false);

  const { data: runs = [] as Run[], isLoading } = useQuery<Run[]>({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 3000,
  });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matching = q
      ? runs.filter(
          (r) =>
            r.name.toLowerCase().includes(q) ||
            r.model.toLowerCase().includes(q) ||
            r.comic_format.toLowerCase().includes(q) ||
            r.status.toLowerCase().includes(q),
        )
      : runs;
    return sortRuns(matching, sort);
  }, [runs, query, sort]);

  if (isLoading)
    return (
      <div className="text-sm text-[hsl(var(--text-muted))]">loading…</div>
    );

  const currentSort = SORT_OPTIONS.find((o) => o.key === sort)!;

  return (
    <div>
      {/* header */}
      <div className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">runs</h1>
        <Link
          to="/new"
          className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--accent))] px-4 py-2 text-sm font-medium text-[hsl(var(--accent-fg))] transition-colors hover:opacity-90"
        >
          + new run
        </Link>
      </div>

      {/* search + sort toolbar */}
      {runs.length > 0 && (
        <div className="mb-4 flex items-center gap-2">
          {/* search */}
          <div className="relative flex-1">
            <Search
              size={13}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))]"
            />
            <input
              type="text"
              placeholder="search by name, model, format, status…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] py-2 pl-8 pr-8 text-sm placeholder:text-[hsl(var(--text-muted)/.6)] focus:border-[hsl(var(--accent2))] focus:outline-none transition-colors"
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
              >
                <X size={13} />
              </button>
            )}
          </div>

          {/* sort */}
          <div className="relative">
            <button
              onClick={() => setShowSort((s) => !s)}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm transition-colors whitespace-nowrap",
                showSort
                  ? "border-[hsl(var(--accent2)/.5)] text-[hsl(var(--accent2))]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))] hover:text-[hsl(var(--text))]",
              )}
            >
              <ArrowUpDown size={12} />
              {currentSort.label}
            </button>

            {showSort && (
              <div className="absolute right-0 top-full z-10 mt-1 w-44 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] shadow-lg overflow-hidden">
                {SORT_OPTIONS.map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => {
                      setSort(opt.key);
                      setShowSort(false);
                    }}
                    className={cn(
                      "w-full px-3 py-2 text-left text-sm transition-colors",
                      sort === opt.key
                        ? "bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                        : "text-[hsl(var(--text))] hover:bg-[hsl(var(--bg-subtle))]",
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* results */}
      {runs.length === 0 ? (
        <Card className="py-16 text-center">
          <p className="text-sm text-[hsl(var(--text-muted))]">no runs yet</p>
          <Link
            to="/new"
            className="mt-2 block text-sm text-[hsl(var(--accent2))] hover:underline"
          >
            create your first run
          </Link>
        </Card>
      ) : filtered.length === 0 ? (
        <Card className="py-12 text-center">
          <p className="text-sm text-[hsl(var(--text-muted))]">
            no runs match "{query}"
          </p>
          <button
            onClick={() => setQuery("")}
            className="mt-2 block w-full text-sm text-[hsl(var(--accent2))] hover:underline"
          >
            clear search
          </button>
        </Card>
      ) : (
        <>
          {query && (
            <p className="mb-3 text-xs text-[hsl(var(--text-muted))]">
              {filtered.length} of {runs.length} runs
            </p>
          )}
          <div className="flex flex-col gap-3">
            {filtered.map((run) => (
              <RunCard key={run.id} run={run} query={query} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
