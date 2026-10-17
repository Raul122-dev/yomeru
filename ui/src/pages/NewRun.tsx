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
  const [series, setSeries] = useState("");
  const [chapter, setChapter] = useState("");
  const [error, setError] = useState("");

  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });

  // Base = defaults or the chosen preset; the form edits a copy for this run only
  const base = useMemo(
    () => (presetId ? cfg?.presets.find((p) => p.id === presetId)?.settings : cfg?.settings) ?? null,
    [cfg, presetId],
  );
  useEffect(() => setSettings(base), [base]);

  const isLocal = settings?.analysis?.backend === "local";
  const hasApiModel = !!(settings?.analysis_model.connection_id && settings.analysis_model.model);
  const needsSetup = !!settings && !isLocal && !hasApiModel;
  const modelLabel = !settings
    ? ""
    : isLocal
      ? `Local (experimental) · ${String(settings.analysis.options?.model ?? "auto")}`
      : `${cfg?.connections.find((c) => c.id === settings.analysis_model.connection_id)?.name ?? "?"} · ${settings.analysis_model.model || "No model"}`;

  const useLocal = () =>
    settings && setSettings({ ...settings, analysis: { ...settings.analysis, backend: "local", options: {} } });

  const submit = async () => {
    if (!files.length) return setError("Select at least one page");
    if (!name.trim()) return setError("Give the run a name");
    if (!settings) return;
    if (needsSetup)
      return setError("No model provider configured — set one up in Settings, or use the experimental local mode");
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("name", name);
      form.append("global_context", globalCtx);
      form.append("series", series);
      form.append("chapter", chapter);
      for (const f of files) form.append("files", f);
      const run = await createRun(form, {
        preset_id: presetId || undefined,
        settings,
        auto_start: runMode === "full",
      });
      nav(`/runs/${run.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto">
      <h1 className="mb-6 text-xl font-semibold">New run</h1>

      {/* Pages section */}
      <Card className="mb-4">
        <div className="flex flex-col gap-4">
          <Input
            label="Run name *"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My series, chapter 1"
          />
          <div className="flex flex-wrap gap-3">
            <Input
              label="Series (optional)"
              value={series}
              onChange={(e) => setSeries(e.target.value)}
              placeholder="My series"
              hint="Groups chapters in comic library apps (saved in the .cbz)"
            />
            <Input
              label="Chapter no. (optional)"
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
              placeholder="1"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
              Pages
            </label>
            <ImageSorter
              onChange={setFiles}
              onError={setError}
              onArchive={(info) => {
                // ComicInfo.xml pre-fills what the user has not typed yet
                if (info.series) setSeries((v) => v || info.series!);
                if (info.number) setChapter((v) => v || info.number!);
                const title = info.title || (info.series && info.number ? `${info.series} ${info.number}` : "");
                if (title) setName((v) => v || title);
              }}
            />
          </div>
        </div>
      </Card>

      {/* Chapter context — prominent, not hidden */}
      <Card className="mb-4">
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
          Chapter context
        </label>
        <p className="mb-2 text-xs text-[hsl(var(--text-muted))]">
          Extra context about this chapter that helps the model produce better
          translations. Character names, story setting, genre, narrative style,
          etc.
        </p>
        <textarea
          value={globalCtx}
          onChange={(e) => setGlobalCtx(e.target.value)}
          rows={3}
          placeholder={`e.g. "Action manhwa. The main character is a young hunter who can level up like in a game; he speaks casually. This chapter introduces his rival, a cold, formal swordswoman."`}
          className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 py-2 text-xs leading-relaxed placeholder:text-[hsl(var(--text-muted))] resize-y focus:border-[hsl(var(--accent2))] focus:outline-none"
        />
      </Card>

      {needsSetup && (
        <Card className="mb-4 border-[hsl(var(--warning)/.6)]">
          <p className="text-sm font-medium">A model is needed to read and translate the pages</p>
          <p className="mt-1 text-xs text-[hsl(var(--text-muted))]">
            yomeru uses a vision model through an API (OpenRouter, OpenAI, Anthropic or any compatible
            provider) — best quality. Or, for a 100% free run, a model on this machine (experimental:
            noticeably weaker translations).
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => nav("/settings")}>Set up a provider</Button>
            <Button size="sm" variant="outline" onClick={useLocal}>Use local mode (experimental)</Button>
          </div>
        </Card>
      )}

      {/* Run options */}
      <Card className="mb-4">
        <div className="flex flex-col gap-4">
          <Select label="Settings" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
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
              Execution mode
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
            Adjust settings for this run only
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
        <Button onClick={submit} disabled={loading || !files.length || !name.trim() || needsSetup}
                title={!files.length ? "Add pages first" : !name.trim() ? "Name the run first" : needsSetup ? "Set up a model first" : undefined}>
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
