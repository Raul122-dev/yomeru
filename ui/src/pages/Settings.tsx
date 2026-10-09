import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Trash2 } from "lucide-react";
import {
  createPreset,
  deletePreset,
  getConfig,
  updatePreset,
  updateSettings,
} from "../lib/api";
import type { AppConfig, PipelineSettings, Preset } from "../lib/types";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { FontsCard } from "../components/FontsCard";
import { ConnectionsCard } from "../features/settings/ConnectionsCard";
import { PipelineSettingsForm } from "../features/settings/PipelineSettingsForm";
import { cn } from "../lib/utils";

/** Global defaults or one preset — same form, different save target. */
function SettingsEditor({ cfg }: { cfg: AppConfig }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState<"global" | string>("global");
  const preset = cfg.presets.find((p) => p.id === target);
  const source: PipelineSettings = preset ? preset.settings : cfg.settings;

  const [draft, setDraft] = useState<PipelineSettings>(source);
  const [name, setName] = useState(preset?.name ?? "");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    setDraft(source);
    setName(preset?.name ?? "");
  }, [target, cfg]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = JSON.stringify(draft) !== JSON.stringify(source) || (preset && name !== preset.name);
  const onSaved = (next: AppConfig) => {
    qc.setQueryData(["config"], next);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const save = useMutation({
    mutationFn: () =>
      preset ? updatePreset({ ...preset, name, settings: draft } as Preset) : updateSettings(draft),
    onSuccess: onSaved,
  });
  const saveAsPreset = useMutation({
    mutationFn: (n: string) => createPreset(n, draft),
    onSuccess: (next) => {
      onSaved(next);
      setTarget(next.presets[next.presets.length - 1].id);
    },
  });
  const remove = useMutation({
    mutationFn: () => deletePreset(target),
    onSuccess: (next) => {
      qc.setQueryData(["config"], next);
      setTarget("global");
    },
  });

  return (
    <Card className="mb-4">
      <h2 className="mb-1 text-sm font-medium">Pipeline</h2>
      <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
        Defaults for new runs. Presets are saved variations you can pick when creating a run.
        Every run keeps a copy of the settings it was created with, so editing these never
        changes existing runs.
      </p>

      <div className="mb-5 flex flex-wrap gap-1.5" role="tablist">
        {[{ id: "global", name: "Defaults" }, ...cfg.presets].map((p) => (
          <button
            key={p.id}
            role="tab"
            aria-selected={target === p.id}
            onClick={() => setTarget(p.id)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs transition-colors",
              target === p.id
                ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
            )}
          >
            {p.name}
          </button>
        ))}
        <button
          onClick={() => {
            const n = prompt("Preset name", "");
            if (n?.trim()) saveAsPreset.mutate(n.trim());
          }}
          className="flex items-center gap-1 rounded-md border border-dashed border-[hsl(var(--border))] px-2.5 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
        >
          <Plus size={11} /> save as preset
        </button>
      </div>

      {preset && (
        <div className="mb-5">
          <Input label="preset name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      )}

      <PipelineSettingsForm value={draft} onChange={setDraft} />

      <div className="mt-6 flex items-center gap-2">
        <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          {saved ? <><Check size={12} /> saved</> : save.isPending ? "saving…" : "save"}
        </Button>
        {dirty && (
          <Button size="sm" variant="ghost" onClick={() => setDraft(source)}>
            discard changes
          </Button>
        )}
        {preset && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => confirm(`Delete preset "${preset.name}"?`) && remove.mutate()}
          >
            <Trash2 size={12} /> delete preset
          </Button>
        )}
      </div>
      {(save.error || saveAsPreset.error) && (
        <p className="mt-2 text-xs text-[hsl(var(--danger))]">
          {((save.error || saveAsPreset.error) as Error).message}
        </p>
      )}
    </Card>
  );
}

export default function Settings() {
  const { data: cfg, isLoading, error } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  return (
    <div>
      <h1 className="mb-6 text-xl font-semibold">Settings</h1>
      {error && <p className="text-sm text-[hsl(var(--danger))]">{(error as Error).message}</p>}
      {isLoading && <p className="text-sm text-[hsl(var(--text-muted))]">loading…</p>}
      {cfg && (
        <div className="grid grid-cols-1 gap-x-6 lg:grid-cols-2">
          <div className="flex flex-col">
            <SettingsEditor cfg={cfg} />
          </div>
          <div className="flex flex-col">
            <ConnectionsCard />
            <FontsCard />
          </div>
        </div>
      )}
    </div>
  );
}
