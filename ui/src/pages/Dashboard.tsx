import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { deleteRun, listRuns } from "../lib/api";
import type { PhaseName, PhaseStatus, Run } from "../lib/types";
import { buttonVariants } from "../components/ui/button";
import { StatusIcon } from "../lib/status";
import { cn } from "../lib/utils";

type SortKey = "newest" | "oldest" | "name";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "name", label: "Name" },
];
const PHASES: PhaseName[] = ["detection", "analysis", "matching", "inpainting", "rendering"];

function sortRuns(runs: Run[], sort: SortKey): Run[] {
  const t = (r: Run) => new Date(r.created_at).getTime();
  return [...runs].sort((a, b) =>
    sort === "name" ? a.name.localeCompare(b.name) : sort === "oldest" ? t(a) - t(b) : t(b) - t(a),
  );
}

/** The 5 phases as ink ticks: what's done, what's running, what's left. */
function PipelineTicks({ run }: { run: Run }) {
  return (
    <div className="flex items-center gap-1" aria-label="Pipeline progress">
      {PHASES.map((p) => {
        const s = (run.phase_status?.[p] ?? "pending") as PhaseStatus;
        return (
          <span key={p} title={`${p}: ${s}`}
            className={cn(
              "h-1 flex-1 rounded-full",
              s === "done" ? "bg-[hsl(var(--text)/.45)]"
                : s === "running" ? "animate-pulse bg-[hsl(var(--accent2))]"
                : s === "failed" ? "bg-[hsl(var(--danger))]"
                : s === "partial" || s === "stale" ? "bg-[hsl(var(--warning))]"
                : "bg-[hsl(var(--border))]",
            )} />
        );
      })}
    </div>
  );
}

function overall(run: Run): PhaseStatus {
  const ps = PHASES.map((p) => (run.phase_status?.[p] ?? "pending") as PhaseStatus);
  if (ps.includes("running")) return "running";
  if (ps.includes("failed")) return "failed";
  if (ps.every((s) => s === "done")) return "done";
  if (ps.includes("stale") || ps.includes("partial")) return "partial";
  if (ps.includes("cancelled")) return "cancelled";
  return "pending";
}

function RunCard({ run }: { run: Run }) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: async () => {
      const r = await deleteRun(run.id);
      if (!r.ok) throw new Error(`delete failed (${r.status})`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast(`Deleted "${run.name}"`);
    },
  });
  const cover = null;
  const date = new Date(run.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const st = overall(run);

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] transition-colors hover:border-[hsl(var(--border-strong))]">
      <Link to={`/runs/${run.id}`} className="flex flex-1 flex-col">
        <div className={cn("relative aspect-[4/3] overflow-hidden border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]", st === "failed" && "opacity-60 grayscale")}>
          {cover ? (
            <img src={cover} alt="" loading="lazy" decoding="async"
                 className="size-full object-cover object-top transition-transform duration-300 group-hover:scale-[1.02]" />
          ) : (
            <RunCoverFallback run={run} />
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2.5 p-3.5">
          <div className="flex items-start gap-2">
            <h2 className="line-clamp-2 flex-1 text-sm font-semibold leading-5">{run.name}</h2>
            <StatusIcon status={st} className="mt-0.5" />
          </div>
          <PipelineTicks run={run} />
          <p className="truncate font-mono text-[11px] text-[hsl(var(--text-muted))]" title={run.model}>
            {run.total_pages}p · {run.target_language ?? run.settings?.language.target ?? ""} · {date}
          </p>
          <p className="truncate font-mono text-[11px] text-[hsl(var(--text-faint))]" title={run.model}>{run.model}</p>
          {run.error && st === "failed" && (
            <p className="line-clamp-2 text-xs text-[hsl(var(--danger))]">{run.error}</p>
          )}
        </div>
      </Link>
      <button
        aria-label={`Delete ${run.name}`}
        onClick={() => {
          if (confirm(`Delete "${run.name}" and all its files? This can't be undone.`)) del.mutate();
        }}
        className="absolute right-2 top-2 grid size-7 place-items-center rounded-[var(--radius-sm)] bg-[hsl(var(--bg-surface)/.9)] text-[hsl(var(--text-muted))] opacity-0 shadow-[0_0_0_1px_hsl(var(--border))] transition-opacity hover:text-[hsl(var(--danger))] focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Trash2 size={13} />
      </button>
    </article>
  );
}

function RunCoverFallback({ run }: { run: Run }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="screentone relative size-full">
      {!failed && (
        <img src={`/api/runs/${run.id}/pages-cover`} alt="" loading="lazy" onError={() => setFailed(true)}
             className="size-full object-cover object-top opacity-90" />
      )}
    </div>
  );
}

export default function Dashboard() {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const { data: runs = [], isLoading } = useQuery<Run[]>({
    queryKey: ["runs"],
    queryFn: listRuns,
    // Poll only while a run is working
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => Object.values(r.phase_status ?? {}).includes("running")) ? 3000 : false,
  });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? runs.filter((r) => [r.name, r.model, r.comic_format, r.target_language].some((f) => f?.toLowerCase().includes(q)))
      : runs;
    return sortRuns(list, sort);
  }, [runs, query, sort]);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Library</p>
          <h1 className="mt-1 text-3xl leading-9">Runs</h1>
        </div>
        <Link to="/new" className={buttonVariants({ variant: "default" })}>
          <Plus size={14} /> New run
        </Link>
      </header>

      {runs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))]" />
            <input
              type="search"
              aria-label="Search runs"
              placeholder="Search by name, model, language…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-8 pr-8"
            />
            {query && (
              <button aria-label="Clear search" onClick={() => setQuery("")}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]">
                <X size={14} />
              </button>
            )}
          </div>
          <div role="radiogroup" aria-label="Sort" className="flex rounded-[var(--radius-sm)] border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] p-0.5">
            {SORTS.map((s) => (
              <button key={s.key} role="radio" aria-checked={sort === s.key} onClick={() => setSort(s.key)}
                className={cn("h-7 rounded-[4px] px-2.5 text-xs",
                  sort === s.key ? "bg-[hsl(var(--text))] text-[hsl(var(--bg))]" : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]")}>
                {s.label}
              </button>
            ))}
          </div>
          <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
            {filtered.length === runs.length ? `${runs.length} runs` : `${filtered.length} of ${runs.length}`}
          </span>
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-[hsl(var(--text-muted))]">loading…</p>
      ) : runs.length === 0 ? (
        <div className="screentone-fade rounded-[var(--radius-md)] border border-dashed border-[hsl(var(--border-strong))] px-8 py-16">
          <p className="eyebrow">No runs yet</p>
          <h2 className="mt-2 text-xl">Translate your first chapter</h2>
          <p className="mt-1 max-w-md text-sm text-[hsl(var(--text-muted))]">
            Upload the pages, pick the languages, and yomeru detects, reads, translates and typesets them — with an editor at every step.
          </p>
          <Link to="/new" className={cn(buttonVariants({ variant: "default" }), "mt-5")}>
            <Plus size={14} /> New run
          </Link>
        </div>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-[hsl(var(--text-muted))]">
          No runs match "{query}". <button className="text-[hsl(var(--accent2))] underline" onClick={() => setQuery("")}>Clear search</button>
        </p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-4">
          {filtered.map((r) => <RunCard key={r.id} run={r} />)}
        </div>
      )}
    </div>
  );
}
