import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { createRun, getTypesetCapabilities } from "../lib/api";
import {
  getConfig,
  getFormats,
  getLocalModels,
  getProviders,
} from "../lib/api";
import { SOURCE_LANGUAGES, TARGET_LANGUAGES } from "../lib/languages";
import { Button } from "../components/ui/button";
import { Input, Select } from "../components/ui/input";
import { Card } from "../components/ui/card";
import { ImageSorter } from "../components/ImageSorter";
import { Switch } from "../components/ui/Switch";
import { cn } from "../lib/utils";

const PROVIDER_HINTS: Record<string, string> = {
  anthropic: "e.g. claude-sonnet-4-5, claude-opus-4-5",
  openai: "e.g. gpt-4o, gpt-4o-mini",
  google: "e.g. gemini-2.0-flash, gemini-1.5-pro",
  custom: "model name — e.g. qwen2.5vl, llama3.2-vision",
};

export default function NewRun() {
  const nav = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [format, setFormat] = useState("auto");
  // language
  const [sourceLang, setSourceLang] = useState("auto");
  const [translate, setTranslate] = useState(false);
  const [targetLang, setTargetLang] = useState("Spanish");
  // context
  const [globalCtx, setGlobalCtx] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  // submit
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detectorBackend, setDetectorBackend] = useState("auto");
  const [detectorThreshold, setDetectorThreshold] = useState(0.4);
  const [runMode, setRunMode] = useState<"full" | "manual">("full");

  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: formats = [] } = useQuery({
    queryKey: ["formats"],
    queryFn: getFormats,
  });
  const { data: providers = [] } = useQuery({
    queryKey: ["providers"],
    queryFn: getProviders,
  });
  const { data: capabilities } = useQuery({
    queryKey: ["typeset-capabilities"],
    queryFn: getTypesetCapabilities,
    staleTime: Infinity,
  });

  const { data: localModels = [] } = useQuery({
    queryKey: ["local-models"],
    queryFn: getLocalModels,
    retry: 1,
    enabled: provider === "custom",
  });

  useEffect(() => {
    if (!cfg || provider) return;
    setFormat(cfg.defaults.format || "auto");
    setSourceLang(cfg.defaults.source_language || "auto");
    if (cfg.defaults.model) setModel(cfg.defaults.model);
    if (cfg.defaults.provider) setProvider(cfg.defaults.provider);
  }, [cfg]);

  const submit = async () => {
    if (!files.length) {
      setError("select at least one image");
      return;
    }
    if (!name.trim()) {
      setError("give the run a name");
      return;
    }
    if (!model.trim()) {
      setError("enter a model name");
      return;
    }
    if (!provider) {
      setError("select a provider");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("name", name);
      form.append("model", model);
      form.append("provider", provider);
      form.append("comic_format", format);
      form.append("source_language", sourceLang);
      form.append("translate", String(translate));
      form.append("target_language", translate ? targetLang : "");
      form.append("global_context", globalCtx);
      form.append("ui_language", cfg?.defaults.ui_language ?? "English");
      for (const f of files) form.append("files", f);
      const run = await createRun(form, {
        detector_backend: detectorBackend,
        detector_threshold: detectorThreshold,
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
    <div className="max-w-2xl">
      <h1 className="mb-6 text-xl font-semibold">new run</h1>
      <Card>
        <div className="flex flex-col gap-5">
          <Input
            label="run name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="solo leveling ch01"
          />

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
              pages
            </label>
            <ImageSorter onChange={setFiles} />
          </div>

          {/* provider */}
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
              provider
            </label>
            <div className="flex flex-wrap gap-2">
              {providers.map((p) => (
                <button
                  key={p.key}
                  onClick={() => {
                    setProvider(p.key);
                    setModel("");
                  }}
                  disabled={!p.ready}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
                    provider === p.key
                      ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                      : p.ready
                        ? "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]"
                        : "cursor-not-allowed border-[hsl(var(--border))] opacity-40",
                  )}
                >
                  {p.label}
                  {!p.ready && <AlertCircle size={12} />}
                </button>
              ))}
            </div>
          </div>

          {/* model */}
          {provider && (
            <div>
              <Input
                label="model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={PROVIDER_HINTS[provider] ?? "model name"}
              />
              {provider === "custom" && localModels.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {localModels.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => setModel(m.name)}
                      className="rounded border border-[hsl(var(--border))] px-2 py-0.5 text-xs text-[hsl(var(--text-muted))] transition-colors hover:border-[hsl(var(--accent2))] hover:text-[hsl(var(--text))]"
                    >
                      {m.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Select
              label="format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              {formats.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.name}
                </option>
              ))}
            </Select>
            <Select
              label="source language"
              value={sourceLang}
              onChange={(e) => setSourceLang(e.target.value)}
            >
              {SOURCE_LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </Select>
          </div>

          {/* translation toggle */}
          <div className="rounded-lg border border-[hsl(var(--border))] p-3 space-y-3">
            <Switch
              label="translation"
              hint="add translated text alongside original in each dialogue"
              checked={translate}
              onCheckedChange={setTranslate}
            />
            {translate && (
              <Select
                label="translate to"
                value={targetLang}
                onChange={(e) => setTargetLang(e.target.value)}
              >
                {TARGET_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </Select>
            )}
          </div>

          {/* advanced — global context + detector */}
          <div>
            <button
              onClick={() => setShowAdvanced((a) => !a)}
              className="flex items-center gap-1.5 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
            >
              {showAdvanced ? (
                <ChevronUp size={12} />
              ) : (
                <ChevronDown size={12} />
              )}
              advanced options
            </button>

            {showAdvanced && (
              <div className="mt-3 space-y-4">
                {/* run mode */}
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
                    run mode
                  </label>
                  <div className="flex gap-2">
                    {(
                      [
                        {
                          key: "full",
                          label: "auto (detect + analyze)",
                          desc: "runs detection then analysis automatically",
                        },
                        {
                          key: "manual",
                          label: "manual (phase by phase)",
                          desc: "you trigger each phase — lets you edit detections before analysis",
                        },
                      ] as const
                    ).map((m) => (
                      <button
                        key={m.key}
                        onClick={() => setRunMode(m.key)}
                        title={m.desc}
                        className={cn(
                          "rounded border px-3 py-1.5 text-xs transition-colors",
                          runMode === m.key
                            ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                            : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
                        )}
                      >
                        {m.label}
                      </button>
                    ))}
                  </div>
                  {runMode === "manual" && (
                    <p className="mt-1 text-[9px] text-[hsl(var(--text-muted))]">
                      Run stops after detection. Edit regions if needed, then
                      manually start analysis from the run view.
                    </p>
                  )}
                </div>

                {/* detector */}

                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
                    text detector
                  </label>
                  <div className="flex flex-wrap gap-2 mb-2">
                    {[
                      {
                        key: "auto",
                        label: "auto",
                        note: "uses CTD if available, else ogkalu",
                      },
                      ...(capabilities?.detectors ?? [
                        {
                          key: "ogkalu",
                          label: "ogkalu RT-DETR",
                          available: true,
                          note: "",
                        },
                      ]),
                    ].map((d) => {
                      const available =
                        (d as { available?: boolean }).available !== false;
                      return (
                        <button
                          key={d.key}
                          onClick={() => available && setDetectorBackend(d.key)}
                          disabled={!available}
                          title={(d as { note?: string }).note}
                          className={cn(
                            "rounded border px-3 py-1.5 text-xs transition-colors",
                            detectorBackend === d.key
                              ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                              : available
                                ? "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]"
                                : "cursor-not-allowed border-[hsl(var(--border))] opacity-40",
                          )}
                        >
                          {d.label}
                          {!available && (
                            <span className="ml-1.5 text-[10px] opacity-60">
                              model not found
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] text-[hsl(var(--text-muted))]">
                      <span>detection threshold</span>
                      <span className="font-mono">
                        {detectorThreshold.toFixed(2)}
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0.2}
                      max={0.9}
                      step={0.05}
                      value={detectorThreshold}
                      onChange={(e) =>
                        setDetectorThreshold(parseFloat(e.target.value))
                      }
                      className="w-full h-1 accent-[hsl(var(--accent2))] cursor-pointer"
                    />
                    <p className="text-[9px] text-[hsl(var(--text-muted))]">
                      lower = detect more regions (more false positives); higher
                      = fewer, more confident
                    </p>
                  </div>
                </div>

                {/* context */}
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
                    manga context (optional)
                  </label>
                  <textarea
                    value={globalCtx}
                    onChange={(e) => setGlobalCtx(e.target.value)}
                    rows={4}
                    placeholder={`Provide background info to help the model:\n- Narrative conventions (e.g. "caption boxes are narrator commentary, not inner thoughts")\n- Character names already known\n- Story setting or genre\n- Anything the model should know before analyzing`}
                    className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 py-2 text-xs leading-relaxed placeholder:text-[hsl(var(--text-muted))] resize-y focus:border-[hsl(var(--accent2))] focus:outline-none"
                  />
                </div>
              </div>
            )}
          </div>

          {error && (
            <p className="text-sm text-[hsl(var(--danger))]">{error}</p>
          )}

          <div className="flex gap-3 pt-1">
            <Button onClick={submit} disabled={loading || !provider}>
              {loading
                ? "starting…"
                : `start run${files.length ? ` (${files.length} pages)` : ""}`}
            </Button>
            <Button variant="outline" onClick={() => nav("/")}>
              cancel
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
