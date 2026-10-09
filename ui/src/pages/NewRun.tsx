import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";
import { createRun, getConfig } from "../lib/api";
import type { PipelineSettings } from "../lib/types";
import { Button } from "../components/ui/button";
import { Input, Select } from "../components/ui/input";
import { Card } from "../components/ui/card";
import { ImageSorter } from "../components/ImageSorter";
import { PipelineSettingsForm } from "../features/settings/PipelineSettingsForm";
import { cn } from "../lib/utils";

export default function NewRun() {
  const nav = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [globalCtx, setGlobalCtx] = useState("");
  const [presetId, setPresetId] = useState("");
  const [settings, setSettings] = useState<PipelineSettings | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [runMode, setRunMode] = useState<"full" | "manual">("full");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });

  // Base = defaults or the chosen preset; the form edits a copy for this run only
  const base = useMemo(
    () => (presetId ? cfg?.presets.find((p) => p.id === presetId)?.settings : cfg?.settings) ?? null,
    [cfg, presetId],
  );
  useEffect(() => setSettings(base), [base]);

  const modelLabel = settings
    ? `${cfg?.connections.find((c) => c.id === settings.analysis_model.connection_id)?.name ?? "?"} · ${settings.analysis_model.model || "no model"}`
    : "";

  const submit = async () => {
    if (!files.length) return setError("Select at least one page");
    if (!name.trim()) return setError("Give the run a name");
    if (!settings?.analysis_model.connection_id || !settings.analysis_model.model)
      return setError("No analysis model selected — set one in Settings or below");
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("name", name);
      form.append("global_context", globalCtx);
      for (const f of files) form.append("files", f);
      const run = await createRun(form, {
        preset_id: presetId || undefined,
        settings,
        auto_start: runMode === "full",
      });
      nav(`/runs/${run.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto">
      <h1 className="mb-6 text-xl font-semibold">New Run</h1>

      {/* Pages section */}
      <Card className="mb-4">
        <div className="flex flex-col gap-4">
          <Input
            label="run name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="solo leveling ch01"
          />

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
              Pages
            </label>
            <ImageSorter onChange={setFiles} />
          </div>
        </div>
      </Card>

      {/* Chapter context — prominent, not hidden */}
      <Card className="mb-4">
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
          Chapter Context
        </label>
        <p className="mb-2 text-[10px] text-[hsl(var(--text-muted))]">
          Extra context about this chapter that helps the model produce better
          translations. Character names, story setting, genre, narrative style,
          etc.
        </p>
        <textarea
          value={globalCtx}
          onChange={(e) => setGlobalCtx(e.target.value)}
          rows={3}
          placeholder={`e.g. "Action manhwa. MC is Sung Jin-Woo, a hunter who gains the ability to level up like a game character. This chapter introduces the S-rank hunter Cha Hae-In."`}
          className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 py-2 text-xs leading-relaxed placeholder:text-[hsl(var(--text-muted))] resize-y focus:border-[hsl(var(--accent2))] focus:outline-none"
        />
      </Card>

      {/* Run options */}
      <Card className="mb-4">
        <div className="flex flex-col gap-4">
          <Select label="settings" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
            <option value="">Defaults</option>
            {cfg?.presets.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </Select>
          <p className="-mt-2 font-mono text-xs text-[hsl(var(--text-muted))]">
            {modelLabel} · {settings?.language.source} → {settings?.language.target} · {settings?.language.comic_format}
          </p>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
              execution mode
            </label>
            <div className="flex gap-2">
              {(
                [
                  { key: "full", label: "Auto (all phases)", desc: "Runs all 5 phases sequentially" },
                  { key: "manual", label: "Step by step", desc: "You trigger each phase and can edit between phases" },
                ] as const
              ).map((m) => (
                <button
                  key={m.key}
                  onClick={() => setRunMode(m.key)}
                  title={m.desc}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs transition-colors",
                    runMode === m.key
                      ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                      : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => setShowSettings((a) => !a)}
            className="flex items-center gap-1.5 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
          >
            {showSettings ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            adjust settings for this run only
          </button>
          {showSettings && settings && (
            <div className="rounded-md border border-[hsl(var(--border))] p-3">
              <PipelineSettingsForm value={settings} onChange={setSettings} />
            </div>
          )}
        </div>
      </Card>

      {/* Submit */}
      {error && (
        <p className="mb-3 text-sm text-[hsl(var(--danger))]">{error}</p>
      )}

      <div className="flex gap-3">
        <Button onClick={submit} disabled={loading}>
          {loading
            ? "Starting…"
            : `Start run${files.length ? ` (${files.length} pages)` : ""}`}
        </Button>
        <Button variant="outline" onClick={() => nav("/")}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
