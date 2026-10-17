/**
 * TranslationReview — the chapter-level review of Read & translate:
 *   - chapter context (editable; changing it outdates Read & translate),
 *   - glossary (editing it re-translates only the lines that use the changed
 *     terms, with the whole glossary as context),
 *   - "Re-translate all" for changes of tone/register,
 *   - lines the translator flagged for a human look.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  getRun, getTranslation, patchRun, retranslate, type GlossaryEntry,
} from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Panel } from "./PhaseShell";

export function TranslationReview({ runId, disabled, onOpenPage }: {
  runId: string;
  disabled?: boolean;
  onOpenPage?: (page: number) => void;
}) {
  const qc = useQueryClient();
  const { data: run } = useQuery({ queryKey: ["run", runId], queryFn: () => getRun(runId) });
  const { data: tr } = useQuery({ queryKey: ["translation", runId], queryFn: () => getTranslation(runId), retry: false });

  const [context, setContext] = useState("");
  const [rows, setRows] = useState<GlossaryEntry[]>([]);
  useEffect(() => setContext(run?.global_context ?? ""), [run?.global_context]);
  useEffect(() => setRows(tr?.glossary ?? []), [tr]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: ["translation", runId] });
  };
  const saveContext = useMutation({
    mutationFn: () => patchRun(runId, { global_context: context }),
    onSuccess: (m) => {
      refresh();
      toast(m.stale.length ? "Context saved — Read & translate is now outdated" : "Context saved");
    },
  });
  const saveGlossary = useMutation({
    mutationFn: () => retranslate(runId, { scope: "affected", glossary: rows }),
    onSuccess: (r) => {
      refresh();
      toast(r.affected ? `Glossary saved — re-translating ${r.affected} line${r.affected > 1 ? "s" : ""}` : "Glossary saved, no line uses the changes");
    },
  });
  const all = useMutation({
    mutationFn: () => retranslate(runId, { scope: "all" }),
    onSuccess: () => { refresh(); toast("Re-translating the whole chapter"); },
  });

  const glossaryDirty = JSON.stringify(rows) !== JSON.stringify(tr?.glossary ?? []);
  const contextDirty = context !== (run?.global_context ?? "");
  const review = Object.entries(tr?.review ?? {});
  const set = (i: number, k: keyof GlossaryEntry, v: string) =>
    setRows((r) => r.map((g, j) => (j === i ? { ...g, [k]: v } : g)));

  return (
    <Panel>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="flex flex-col gap-2">
          <h4 className="eyebrow">Chapter context</h4>
          <p className="text-xs text-[hsl(var(--text-muted))]">
            Notes the model reads with every page (who is who, setting, tone). Changing them outdates Read &amp; translate.
          </p>
          <textarea
            className="min-h-28 w-full rounded-[var(--radius-sm)] border border-[hsl(var(--border))] bg-transparent p-2 text-sm"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="e.g. Kai is the narrator; he speaks casually. Set in a mining town."
          />
          <div>
            <Button size="sm" variant="outline" disabled={!contextDirty || saveContext.isPending || disabled}
                    onClick={() => saveContext.mutate()}>Save context</Button>
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h4 className="eyebrow">Glossary</h4>
            <Button size="sm" variant="ghost" disabled={all.isPending || disabled} onClick={() => all.mutate()}
                    title="New style guide and every line again — for changes of tone or forms of address">
              <RefreshCw size={12} /> Re-translate all
            </Button>
          </div>
          <p className="text-xs text-[hsl(var(--text-muted))]">
            Names, terms and forms of address kept the same across the chapter. Saving re-translates only the lines that use what you changed.
          </p>
          <div className="flex max-h-64 flex-col gap-1 overflow-auto">
            {rows.map((g, i) => (
              <div key={i} className="flex items-center gap-1.5">
                <input className="w-1/2 rounded border border-[hsl(var(--border))] bg-transparent px-2 py-1 text-xs"
                       value={g.source} onChange={(e) => set(i, "source", e.target.value)} placeholder="Original" />
                <span className="text-xs text-[hsl(var(--text-muted))]">→</span>
                <input className="w-1/2 rounded border border-[hsl(var(--border))] bg-transparent px-2 py-1 text-xs"
                       value={g.target} onChange={(e) => set(i, "target", e.target.value)} placeholder="Translation" />
                <button aria-label="Remove" className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--danger))]"
                        onClick={() => setRows((r) => r.filter((_, j) => j !== i))}><Trash2 size={13} /></button>
              </div>
            ))}
            {!rows.length && <p className="text-xs text-[hsl(var(--text-muted))]">No terms yet.</p>}
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => setRows((r) => [...r, { source: "", target: "" }])}>
              <Plus size={12} /> Add term
            </Button>
            <Button size="sm" variant="outline" disabled={!glossaryDirty || saveGlossary.isPending || disabled}
                    onClick={() => saveGlossary.mutate()}>Save glossary</Button>
          </div>
        </section>
      </div>

      {review.length > 0 && (
        <section className="mt-6 flex flex-col gap-1.5">
          <h4 className="eyebrow">To review ({review.length})</h4>
          {review.map(([key, reason]) => {
            const page = Number(key.match(/^p(\d+)/)?.[1] ?? 0);
            return (
              <button key={key} onClick={() => onOpenPage?.(page)}
                      className="flex gap-2 rounded px-2 py-1 text-left text-xs hover:bg-[hsl(var(--bg-subtle))]">
                <span className="shrink-0 font-mono text-[hsl(var(--warning-deep))]">{key}</span>
                <span className="text-[hsl(var(--text-muted))]">{reason}</span>
              </button>
            );
          })}
        </section>
      )}
    </Panel>
  );
}
