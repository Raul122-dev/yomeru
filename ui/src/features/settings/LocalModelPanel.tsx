import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Download, RefreshCw } from "lucide-react";
import { getLocalModels, pullLocalModel } from "../../lib/api";
import type { LocalModelsInfo } from "../../lib/types";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";

/**
 * Status of the local model server (Ollama) for the `local` read & translate
 * technique: is it running, which vision models are installed, how much GPU
 * memory there is, which model 'auto' will use — and a one-click download of
 * the suggested (or chosen) model with progress.
 */
export function LocalModelPanel({ server, model }: { server?: string; model?: string }) {
  const qc = useQueryClient();
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["local-models", server],
    queryFn: () => getLocalModels(server),
    refetchInterval: (q) => (Object.keys((q.state.data as LocalModelsInfo | undefined)?.pulls ?? {}).length ? 1500 : false),
  });
  const pull = useMutation({
    mutationFn: (tag: string) => pullLocalModel(tag, server),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["local-models", server] }),
  });

  if (!data) return null;
  const vision = data.models.filter((m) => m.vision);
  const want = model && model !== "auto" ? model : data.suggested.tag;
  const installed = data.models.some((m) => m.name === want);
  const progress = data.pulls[want];

  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-[hsl(var(--border))] p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-medium text-[hsl(var(--text))]">
          <Cpu size={13} /> Local model server
        </span>
        <div className="flex items-center gap-2">
          {data.running
            ? <Badge variant="done">Ollama {data.version}</Badge>
            : <Badge variant="failed">Not running</Badge>}
          <Button size="icon" variant="ghost" className="size-6" onClick={() => refetch()} title="Refresh">
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
          </Button>
        </div>
      </div>

      {!data.running && (
        <p className="text-[hsl(var(--text-muted))]">
          No server at <code>{data.server}</code>. Install{" "}
          <a className="underline" href="https://ollama.com/download" target="_blank" rel="noreferrer">Ollama</a>
          {" "}and start it — yomeru uses it to run vision models on this machine, no API cost.
        </p>
      )}

      <p className="text-[hsl(var(--text-muted))]">
        {data.gpu
          ? <>GPU: {data.gpu.name} · {data.gpu.free_gb} GB free of {data.gpu.total_gb} GB</>
          : <>No CUDA GPU found — models run on the CPU (slow).</>}
        {" · "}Suggested: <span className="font-mono text-[hsl(var(--text))]">{data.suggested.tag}</span>
        {" "}({data.suggested.note})
      </p>

      {data.running && (
        <>
          <p className="text-[hsl(var(--text-muted))]">
            Installed vision models:{" "}
            {vision.length
              ? vision.map((m) => (
                  <span key={m.name} className="mr-2 font-mono text-[hsl(var(--text))]">{m.name} <span className="text-[hsl(var(--text-muted))]">{m.size_gb} GB</span></span>
                ))
              : "None"}
          </p>
          {progress ? (
            <PullProgress tag={want} p={progress} />
          ) : !installed ? (
            <Button size="sm" variant="outline" className="self-start" disabled={pull.isPending}
              onClick={() => pull.mutate(want)}>
              <Download size={12} /> Download {want}
            </Button>
          ) : (
            <p className="text-[hsl(var(--text-muted))]">
              Will use <span className="font-mono text-[hsl(var(--text))]">{want}</span> — ready.
            </p>
          )}
          {pull.error && <p className="text-[hsl(var(--danger))]">{(pull.error as Error).message}</p>}
        </>
      )}
    </div>
  );
}

function PullProgress({ tag, p }: { tag: string; p: LocalModelsInfo["pulls"][string] }) {
  if (p.error) return <p className="text-[hsl(var(--danger))]">Download of {tag} failed: {p.error}</p>;
  const pct = p.total ? Math.round((p.completed / p.total) * 100) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-[hsl(var(--text-muted))]">
        <span>Downloading <span className="font-mono">{tag}</span> · {p.status}</span>
        <span className="font-mono">{p.total ? `${(p.completed / 1e9).toFixed(1)} / ${(p.total / 1e9).toFixed(1)} GB` : ""}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-[hsl(var(--bg-subtle))]">
        <div className="h-full bg-[hsl(var(--accent2))] transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
