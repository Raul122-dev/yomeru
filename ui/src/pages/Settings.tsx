import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ArrowRight,
  Wifi,
  WifiOff,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import {
  getConfig,
  getLocalModels,
  getFormats,
  updateProvider,
  updateDefaults,
  updateTranslation,
  updatePhases,
  testConnection,
} from "../lib/api";
import { TARGET_LANGUAGES, SOURCE_LANGUAGES } from "../lib/languages";
import { Button } from "../components/ui/button";
import { Input, Select } from "../components/ui/input";
import { Card } from "../components/ui/card";
import { Switch } from "../components/ui/Switch";
import { Slider } from "../components/ui/Slider";
import { Combobox } from "../components/ui/Combobox";
import { FontsCard } from "../components/FontsCard";
import type { AppConfig, ModelInfo } from "../lib/types";

// ── helpers ───────────────────────────────────────────────────────────────────

function SaveButton({
  saving,
  saved,
  onClick,
}: {
  saving: boolean;
  saved: boolean;
  onClick: () => void;
}) {
  return (
    <Button onClick={onClick} disabled={saving} size="sm" className="mt-4">
      {saved ? (
        <>
          <Check size={13} /> saved
        </>
      ) : saving ? (
        "saving..."
      ) : (
        "save"
      )}
    </Button>
  );
}

function SectionToggle({
  label,
  open,
  onToggle,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex items-center gap-1.5 text-xs font-medium text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
    >
      {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      {label}
    </button>
  );
}

// ── Model & Language Card ─────────────────────────────────────────────────────

function ModelLanguageCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: formats = [] } = useQuery({
    queryKey: ["formats"],
    queryFn: getFormats,
  });
  const {
    data: models = [],
    isLoading: modelsLoading,
  } = useQuery({
    queryKey: ["local-models"],
    queryFn: getLocalModels,
    retry: 1,
  });

  const [model, setModel] = useState("");
  const [format, setFormat] = useState("auto");
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("Spanish");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (cfg) {
      setModel(cfg.defaults.model ?? "");
      setFormat(cfg.defaults.format ?? "auto");
      setSourceLang(cfg.defaults.source_language ?? "auto");
      setTargetLang(cfg.defaults.target_language ?? "Spanish");
    }
  }, [cfg]);

  const save = useMutation({
    mutationFn: () =>
      updateDefaults({
        model,
        format,
        source_language: sourceLang,
        target_language: targetLang,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const selectedModel = models.find((m) => m.id === model);
  const visionWarning =
    selectedModel && selectedModel.vision === false
      ? "⚠ This model may not support vision — analysis requires image input."
      : null;

  return (
    <Card className="mb-4">
      <h2 className="mb-1 text-sm font-medium">Vision Model</h2>
      <p className="mb-4 text-[10px] text-[hsl(var(--text-muted))]">
        Primary model for manga page analysis. Must support image/vision input.
      </p>

      <div className="flex flex-col gap-4">
        <Combobox
          label="analysis model"
          hint="Used for text detection context, character identification, and scene understanding"
          value={model}
          items={models}
          loading={modelsLoading}
          placeholder="e.g. google/gemini-3.1-flash-image-preview"
          showVisionBadge
          onChange={setModel}
        />
        {visionWarning && (
          <p className="text-[10px] text-amber-400">{visionWarning}</p>
        )}

        <div className="rounded-md border border-[hsl(var(--border))] p-3 space-y-3">
          <p className="text-[10px] font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
            Language Pair
          </p>
          <div className="flex items-center gap-2">
            <Select
              label="source"
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
              label="target"
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
        </div>

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

        <SaveButton
          saving={save.isPending}
          saved={saved}
          onClick={() => save.mutate()}
        />
      </div>
    </Card>
  );
}

// ── Translation Model Card ────────────────────────────────────────────────────

function TranslationModelCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: models = [], isLoading: modelsLoading } = useQuery({
    queryKey: ["local-models"],
    queryFn: getLocalModels,
    retry: 1,
  });

  const [enabled, setEnabled] = useState(false);
  const [model, setModel] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (cfg?.translation) {
      setEnabled(cfg.translation.enabled ?? false);
      setModel(cfg.translation.model ?? "");
    }
  }, [cfg]);

  const save = useMutation({
    mutationFn: () => updateTranslation({ enabled, model }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <Card className="mb-4">
      <h2 className="mb-1 text-sm font-medium">Translation Model</h2>
      <p className="mb-4 text-[10px] text-[hsl(var(--text-muted))]">
        Optional separate model for translation. When disabled, the primary
        vision model handles both analysis and translation in a single call.
      </p>

      <div className="flex flex-col gap-4">
        <Switch
          label="Use separate translation model"
          hint="Splits analysis into two LLM calls: vision analysis + translation"
          checked={enabled}
          onCheckedChange={setEnabled}
        />

        {enabled && (
          <Combobox
            label="translation model"
            hint="Does not require vision support — text-only models work here"
            value={model}
            items={models}
            loading={modelsLoading}
            placeholder="e.g. google/gemini-2.5-flash"
            onChange={setModel}
          />
        )}

        <SaveButton
          saving={save.isPending}
          saved={saved}
          onClick={() => save.mutate()}
        />
      </div>
    </Card>
  );
}

// ── Connection Card ───────────────────────────────────────────────────────────

function ConnectionCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });

  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [connStatus, setConnStatus] = useState<{
    ok: boolean;
    error?: string;
  } | null>(null);

  useEffect(() => {
    if (cfg?.providers?.custom) {
      setUrl(cfg.providers.custom.base_url ?? "");
      setApiKey(cfg.providers.custom.api_key ?? "");
    }
  }, [cfg]);

  const save = useMutation({
    mutationFn: () =>
      updateProvider("custom", { base_url: url, api_key: apiKey }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      qc.invalidateQueries({ queryKey: ["local-models"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const checkConn = useMutation({
    mutationFn: testConnection,
    onSuccess: (data) => setConnStatus(data),
  });

  return (
    <Card className="mb-4">
      <h2 className="mb-1 text-sm font-medium">Endpoint</h2>
      <p className="mb-4 text-[10px] text-[hsl(var(--text-muted))]">
        OpenAI-compatible API — Ollama, LM Studio, OpenRouter, vLLM, etc.
      </p>

      <div className="flex flex-col gap-4">
        <Input
          label="base url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://localhost:11434"
          hint="No need to add /v1 — handled automatically"
        />
        <Input
          label="api key (optional)"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Required for cloud services (OpenRouter, DeepSeek, etc.)"
        />

        <div className="flex items-center gap-2">
          <SaveButton
            saving={save.isPending}
            saved={saved}
            onClick={() => save.mutate()}
          />
          <Button
            size="sm"
            variant="ghost"
            className="mt-4"
            onClick={() => checkConn.mutate()}
            disabled={checkConn.isPending}
          >
            {checkConn.isPending ? "testing…" : "test connection"}
          </Button>
        </div>

        {connStatus && (
          <div
            className={`flex items-center gap-1.5 text-xs ${connStatus.ok ? "text-green-400" : "text-red-400"}`}
          >
            {connStatus.ok ? <Wifi size={12} /> : <WifiOff size={12} />}
            {connStatus.ok ? "Connected" : connStatus.error}
          </div>
        )}
      </div>
    </Card>
  );
}

// ── Provider Keys Card (collapsible) ──────────────────────────────────────────

function ProviderKeysCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [open, setOpen] = useState(false);

  const providers = [
    { key: "anthropic", label: "Anthropic (Claude)", placeholder: "sk-ant-..." },
    { key: "openai", label: "OpenAI (GPT)", placeholder: "sk-..." },
    { key: "google", label: "Google (Gemini)", placeholder: "AIza..." },
  ];

  const [keys, setKeys] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (cfg?.providers) {
      const k: Record<string, string> = {};
      for (const p of providers) {
        k[p.key] = cfg.providers[p.key]?.api_key ?? "";
      }
      setKeys(k);
    }
  }, [cfg]);

  const saveKey = (provider: string) => {
    updateProvider(provider, { api_key: keys[provider] }).then(() => {
      qc.invalidateQueries({ queryKey: ["config"] });
      setSaved((s) => ({ ...s, [provider]: true }));
      setTimeout(() => setSaved((s) => ({ ...s, [provider]: false })), 2000);
    });
  };

  return (
    <Card className="mb-4">
      <SectionToggle
        label="Direct Provider API Keys (Advanced)"
        open={open}
        onToggle={() => setOpen(!open)}
      />
      {!open && (
        <p className="mt-1 text-[10px] text-[hsl(var(--text-muted))]">
          Only needed when connecting directly to providers instead of a unified
          endpoint.
        </p>
      )}

      {open && (
        <div className="mt-4 flex flex-col gap-4">
          {providers.map((p) => (
            <div key={p.key} className="flex items-end gap-2">
              <Input
                label={p.label}
                type="password"
                value={keys[p.key] ?? ""}
                onChange={(e) =>
                  setKeys((k) => ({ ...k, [p.key]: e.target.value }))
                }
                placeholder={p.placeholder}
              />
              <Button
                size="sm"
                onClick={() => saveKey(p.key)}
                className="shrink-0"
              >
                {saved[p.key] ? <Check size={12} /> : "save"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Phase Settings Card ───────────────────────────────────────────────────────

function PhaseSettingsCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [saved, setSaved] = useState(false);

  const [detection, setDetection] = useState({
    backend: "auto",
    threshold: 0.4,
  });
  const [matching, setMatching] = useState({
    backend: "hungarian",
    ocr_weight: 0.4,
    spatial_weight: 0.4,
    position_weight: 0.2,
    min_score: 0.05,
  });
  const [inpainting, setInpainting] = useState({ backend: "auto" });
  const [rendering, setRendering] = useState({
    backend: "pil",
    use_translation: true,
    skip_sfx: true,
    skip_narration: false,
    padding: 12,
    min_font_size: 9,
    max_font_size: 30,
  });

  useEffect(() => {
    if (cfg?.phases) {
      if (cfg.phases.detection) setDetection(cfg.phases.detection);
      if (cfg.phases.matching) setMatching(cfg.phases.matching);
      if (cfg.phases.inpainting) setInpainting(cfg.phases.inpainting);
      if (cfg.phases.rendering) setRendering(cfg.phases.rendering);
    }
  }, [cfg]);

  const save = useMutation({
    mutationFn: () =>
      updatePhases({ detection, matching, inpainting, rendering }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const [openSection, setOpenSection] = useState<string | null>(null);
  const toggle = (s: string) =>
    setOpenSection(openSection === s ? null : s);

  return (
    <Card className="mb-4">
      <h2 className="mb-1 text-sm font-medium">Phase Settings</h2>
      <p className="mb-4 text-[10px] text-[hsl(var(--text-muted))]">
        Fine-tune each pipeline phase. Changes apply to new runs.
      </p>

      <div className="flex flex-col gap-3">
        {/* Detection */}
        <div className="rounded border border-[hsl(var(--border))] p-2">
          <SectionToggle
            label="Detection"
            open={openSection === "detection"}
            onToggle={() => toggle("detection")}
          />
          {openSection === "detection" && (
            <div className="mt-3 space-y-3">
              <Select
                label="backend"
                value={detection.backend}
                onChange={(e) =>
                  setDetection({ ...detection, backend: e.target.value })
                }
              >
                <option value="auto">Auto (best available)</option>
                <option value="ogkalu">Ogkalu RT-DETR</option>
                <option value="ctd">CTD (Comic Text Detector)</option>
              </Select>
              <Slider
                label="confidence threshold"
                value={detection.threshold}
                min={0.1}
                max={0.9}
                step={0.05}
                hint="Lower = more detections (may include noise)"
                onChange={(v) =>
                  setDetection({ ...detection, threshold: v })
                }
              />
            </div>
          )}
        </div>

        {/* Matching */}
        <div className="rounded border border-[hsl(var(--border))] p-2">
          <SectionToggle
            label="Matching"
            open={openSection === "matching"}
            onToggle={() => toggle("matching")}
          />
          {openSection === "matching" && (
            <div className="mt-3 space-y-3">
              <Slider
                label="OCR weight"
                value={matching.ocr_weight}
                min={0}
                max={1}
                step={0.05}
                hint="Influence of OCR text similarity"
                onChange={(v) =>
                  setMatching({ ...matching, ocr_weight: v })
                }
              />
              <Slider
                label="spatial weight"
                value={matching.spatial_weight}
                min={0}
                max={1}
                step={0.05}
                hint="Influence of spatial positioning"
                onChange={(v) =>
                  setMatching({ ...matching, spatial_weight: v })
                }
              />
              <Slider
                label="position weight"
                value={matching.position_weight}
                min={0}
                max={1}
                step={0.05}
                hint="Influence of reading order"
                onChange={(v) =>
                  setMatching({ ...matching, position_weight: v })
                }
              />
              <Slider
                label="min score"
                value={matching.min_score}
                min={0}
                max={0.5}
                step={0.01}
                hint="Minimum match score to accept"
                onChange={(v) =>
                  setMatching({ ...matching, min_score: v })
                }
              />
            </div>
          )}
        </div>

        {/* Inpainting */}
        <div className="rounded border border-[hsl(var(--border))] p-2">
          <SectionToggle
            label="Inpainting"
            open={openSection === "inpainting"}
            onToggle={() => toggle("inpainting")}
          />
          {openSection === "inpainting" && (
            <div className="mt-3 space-y-3">
              <Select
                label="backend"
                value={inpainting.backend}
                onChange={(e) =>
                  setInpainting({ ...inpainting, backend: e.target.value })
                }
              >
                <option value="auto">Auto (LaMa if available)</option>
                <option value="lama">LaMa</option>
                <option value="opencv">OpenCV (fast, lower quality)</option>
              </Select>
            </div>
          )}
        </div>

        {/* Rendering */}
        <div className="rounded border border-[hsl(var(--border))] p-2">
          <SectionToggle
            label="Rendering"
            open={openSection === "rendering"}
            onToggle={() => toggle("rendering")}
          />
          {openSection === "rendering" && (
            <div className="mt-3 space-y-3">
              <Switch
                label="Use translated text"
                hint="Render translated text (disable to render original)"
                checked={rendering.use_translation}
                onCheckedChange={(v) =>
                  setRendering({ ...rendering, use_translation: v })
                }
              />
              <Switch
                label="Skip SFX"
                hint="Don't render sound effects"
                checked={rendering.skip_sfx}
                onCheckedChange={(v) =>
                  setRendering({ ...rendering, skip_sfx: v })
                }
              />
              <Switch
                label="Skip narration"
                hint="Don't render narration boxes"
                checked={rendering.skip_narration}
                onCheckedChange={(v) =>
                  setRendering({ ...rendering, skip_narration: v })
                }
              />
              <Slider
                label="padding"
                value={rendering.padding}
                min={0}
                max={30}
                step={1}
                hint="Pixels of padding inside text regions"
                onChange={(v) =>
                  setRendering({ ...rendering, padding: v })
                }
              />
              <Slider
                label="min font size"
                value={rendering.min_font_size}
                min={6}
                max={20}
                step={1}
                onChange={(v) =>
                  setRendering({ ...rendering, min_font_size: v })
                }
              />
              <Slider
                label="max font size"
                value={rendering.max_font_size}
                min={16}
                max={60}
                step={1}
                onChange={(v) =>
                  setRendering({ ...rendering, max_font_size: v })
                }
              />
            </div>
          )}
        </div>

        <SaveButton
          saving={save.isPending}
          saved={saved}
          onClick={() => save.mutate()}
        />
      </div>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  return (
    <div className="">
      <h1 className="mb-6 text-xl font-semibold">Settings</h1>
      <div className="grid grid-cols-1 gap-x-6 lg:grid-cols-2">
        <div className="flex flex-col">
          <ModelLanguageCard />
          <TranslationModelCard />
          <ConnectionCard />
          <ProviderKeysCard />
        </div>
        <div className="flex flex-col">
          <PhaseSettingsCard />
          <FontsCard />
        </div>
      </div>
    </div>
  );
}
