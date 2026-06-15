import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import { createRun, getTypesetCapabilities } from "../lib/api";
import { getConfig, getFormats } from "../lib/api";
import { SOURCE_LANGUAGES, TARGET_LANGUAGES } from "../lib/languages";
import { Button } from "../components/ui/button";
import { Input, Select } from "../components/ui/input";
import { Card } from "../components/ui/card";
import { ImageSorter } from "../components/ImageSorter";
import { cn } from "../lib/utils";

export default function NewRun() {
  const nav = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("");
  const [format, setFormat] = useState("auto");
  // language
  const [sourceLang, setSourceLang] = useState("auto");
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
  const { data: capabilities } = useQuery({
    queryKey: ["typeset-capabilities"],
    queryFn: getTypesetCapabilities,
    staleTime: Infinity,
  });

  // Inherit settings from config
  useEffect(() => {
    if (!cfg) return;
    setFormat(cfg.defaults.format || "auto");
    setSourceLang(cfg.defaults.source_language || "auto");
    setTargetLang(cfg.defaults.target_language || "Spanish");
    if (cfg.defaults.model) setModel(cfg.defaults.model);
    if (cfg.defaults.provider) setProvider(cfg.defaults.provider);
  }, [cfg]);

  const submit = async () => {
    if (!files.length) {
      setError("Select at least one page");
      return;
    }
    if (!name.trim()) {
      setError("Give the run a name");
      return;
    }
    if (!model.trim()) {
      setError("No model configured — set one in Settings");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("name", name);
      form.append("model", model);
      form.append("provider", provider || "custom");
      form.append("comic_format", format);
      form.append("source_language", sourceLang);
      form.append("target_language", targetLang);
      form.append("global_context", globalCtx);
      form.append("ui_language", cfg?.defaults.target_language ?? "Spanish");
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
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
          Options
        </h2>

        <div className="flex flex-col gap-4">
          {/* Language pair */}
          <div className="flex items-center gap-2">
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
            <ArrowRight
              size={16}
              className="mt-5 shrink-0 text-[hsl(var(--text-muted))]"
            />
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
          </div>

          {/* Format */}
          <Select
            label="manga format"
            value={format}
            onChange={(e) => setFormat(e.target.value)}
          >
            {formats.map((f) => (
              <option key={f.key} value={f.key}>
                {f.name}
              </option>
            ))}
          </Select>

          {/* Run mode */}
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
              execution mode
            </label>
            <div className="flex gap-2">
              {(
                [
                  {
                    key: "full",
                    label: "Auto (all phases)",
                    desc: "Runs all 5 phases sequentially",
                  },
                  {
                    key: "manual",
                    label: "Step by step",
                    desc: "You trigger each phase manually — edit between phases",
                  },
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
            {runMode === "manual" && (
              <p className="mt-1.5 text-[10px] text-[hsl(var(--text-muted))]">
                Starts in pending state. Trigger phases one by one from the run
                view — lets you review and edit results between phases.
              </p>
            )}
          </div>

          {/* Advanced */}
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
              detection settings
            </button>

            {showAdvanced && (
              <div className="mt-3 rounded-md border border-[hsl(var(--border))] p-3 space-y-3">
                {/* Detector backend */}
                <div>
                  <label className="mb-1.5 block text-[10px] font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
                    text detector
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      {
                        key: "auto",
                        label: "Auto",
                        note: "CTD if available, else ogkalu",
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
                          onClick={() =>
                            available && setDetectorBackend(d.key)
                          }
                          disabled={!available}
                          title={(d as { note?: string }).note}
                          className={cn(
                            "rounded border px-2.5 py-1 text-[11px] transition-colors",
                            detectorBackend === d.key
                              ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                              : available
                                ? "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]"
                                : "cursor-not-allowed border-[hsl(var(--border))] opacity-40",
                          )}
                        >
                          {d.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Threshold */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px] text-[hsl(var(--text-muted))]">
                    <span>confidence threshold</span>
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
                    Lower = more regions detected (possible false positives)
                  </p>
                </div>
              </div>
            )}
          </div>
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
