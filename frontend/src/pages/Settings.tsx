import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import {
  getConfig,
  getLocalModels,
  getFormats,
  updateProvider,
  updateDefaults,
} from "../lib/api";
import { UI_LANGUAGES, SOURCE_LANGUAGES } from "../lib/languages";
import { Button } from "../components/ui/button";
import { Input, Select } from "../components/ui/input";
import { Card } from "../components/ui/card";
import { FontsCard } from "../components/FontsCard";

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

function useSync<T>(
  remote: T | undefined,
  init: T,
): [
  T,
  React.Dispatch<React.SetStateAction<T>>,
  boolean,
  React.Dispatch<React.SetStateAction<boolean>>,
] {
  const [val, setVal] = useState<T>(init);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (remote !== undefined && !dirty) setVal(remote);
  }, [remote]);
  return [val, setVal, dirty, setDirty];
}

// ── defaults ──────────────────────────────────────────────────────────────────
function DefaultsCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: formats = [] } = useQuery({
    queryKey: ["formats"],
    queryFn: getFormats,
  });
  const { data: localModels = [] } = useQuery({
    queryKey: ["local-models"],
    queryFn: getLocalModels,
    retry: 1,
  });

  const [model, setModel, , setModelDirty] = useSync(cfg?.defaults.model, "");
  const [format, setFormat, , setFormatDirty] = useSync(
    cfg?.defaults.format,
    "auto",
  );
  const [uiLang, setUiLang, , setUiLangDirty] = useSync(
    cfg?.defaults.ui_language,
    "English",
  );
  const [sourceLang, setSourceLang, , setSourceLangDirty] = useSync(
    cfg?.defaults.source_language,
    "auto",
  );
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      updateDefaults({
        model,
        format,
        ui_language: uiLang,
        source_language: sourceLang,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setModelDirty(false);
      setFormatDirty(false);
      setUiLangDirty(false);
      setSourceLangDirty(false);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <Card className="mb-4 break-inside-avoid">
      <h2 className="mb-4 text-sm font-medium">defaults</h2>
      <div className="flex flex-col gap-4">
        <div>
          <Input
            label="default model"
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
              setModelDirty(true);
            }}
            placeholder="model name — e.g. qwen2.5vl, claude-sonnet-4-5, gpt-4o"
          />
          {localModels.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {localModels.map((m) => (
                <button
                  key={m.id}
                  onClick={() => {
                    setModel(m.name);
                    setModelDirty(true);
                  }}
                  className="rounded border border-[hsl(var(--border))] px-2 py-0.5 text-xs text-[hsl(var(--text-muted))] transition-colors hover:border-[hsl(var(--accent2))] hover:text-[hsl(var(--text))]"
                >
                  {m.name}
                </button>
              ))}
            </div>
          )}
        </div>
        <Select
          label="default format"
          value={format}
          onChange={(e) => {
            setFormat(e.target.value);
            setFormatDirty(true);
          }}
        >
          {formats.map((f) => (
            <option key={f.key} value={f.key}>
              {f.name}
            </option>
          ))}
        </Select>
        <Select
          label="default source language"
          value={sourceLang}
          onChange={(e) => {
            setSourceLang(e.target.value);
            setSourceLangDirty(true);
          }}
        >
          {SOURCE_LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </Select>
        <div>
          <Select
            label="ui language"
            value={uiLang}
            onChange={(e) => {
              setUiLang(e.target.value);
              setUiLangDirty(true);
            }}
          >
            {UI_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </Select>
          <p className="mt-1 text-[10px] text-[hsl(var(--text-muted))]">
            language for model-generated descriptions (scene, mood, character
            actions, summaries)
          </p>
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

// ── cloud providers ───────────────────────────────────────────────────────────
function ApiKeyCard({
  providerKey,
  label,
  placeholder,
}: {
  providerKey: string;
  label: string;
  placeholder: string;
}) {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [apiKey, setApiKey, , setDirty] = useSync(
    cfg?.providers[providerKey]?.api_key,
    "",
  );
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () => updateProvider(providerKey, { api_key: apiKey }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config", "providers"] });
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <Card className="mb-4 break-inside-avoid">
      <h2 className="mb-4 text-sm font-medium">{label}</h2>
      <Input
        label="api key"
        type="password"
        value={apiKey}
        onChange={(e) => {
          setApiKey(e.target.value);
          setDirty(true);
        }}
        placeholder={placeholder}
      />
      <SaveButton
        saving={save.isPending}
        saved={saved}
        onClick={() => save.mutate()}
      />
    </Card>
  );
}

// ── custom endpoint ───────────────────────────────────────────────────────────
function CustomEndpointCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const {
    data: localModels = [],
    error: modelsErr,
    refetch: refetchModels,
  } = useQuery({
    queryKey: ["local-models"],
    queryFn: getLocalModels,
    retry: 1,
  });

  const [url, setUrl, , setUrlDirty] = useSync(
    cfg?.providers.custom?.base_url,
    "",
  );
  const [apiKey, setApiKey, , setApiKeyDirty] = useSync(
    cfg?.providers.custom?.api_key,
    "",
  );
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      updateProvider("custom", { base_url: url, api_key: apiKey }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["config", "providers"] });
      refetchModels();
      setSaved(true);
      setUrlDirty(false);
      setApiKeyDirty(false);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <Card className="mb-4 break-inside-avoid">
      <h2 className="mb-4 text-sm font-medium">Custom endpoint</h2>
      <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
        Any OpenAI-compatible server — Ollama (local or cloud), LM Studio, vLLM,
        DeepSeek, Together, Groq, self-hosted…
      </p>
      <div className="flex flex-col gap-4">
        <Input
          label="base url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setUrlDirty(true);
          }}
          placeholder="http://localhost:11434"
          hint="no need to add /v1 — yomeru handles that automatically"
        />
        <Input
          label="api key (optional)"
          type="password"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value);
            setApiKeyDirty(true);
          }}
          placeholder="required for cloud services like DeepSeek, Together, Groq…"
        />
      </div>

      {modelsErr && (
        <p className="mt-3 text-xs text-[hsl(var(--danger))]">
          {(modelsErr as Error).message}
        </p>
      )}
      {!modelsErr && localModels.length > 0 && (
        <p className="mt-3 text-xs text-[hsl(var(--text-muted))]">
          {localModels.length} model{localModels.length !== 1 ? "s" : ""} found:{" "}
          {localModels.map((m) => m.name).join(", ")}
        </p>
      )}
      <SaveButton
        saving={save.isPending}
        saved={saved}
        onClick={() => save.mutate()}
      />
    </Card>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────
export default function Settings() {
  return (
    <div className="">
      <h1 className="mb-6 text-xl font-semibold col-span-2">settings</h1>
      <div className="columns-1 sm:columns-2">
        <DefaultsCard />
        <CustomEndpointCard />
        <ApiKeyCard
          providerKey="anthropic"
          label="Anthropic — Claude"
          placeholder="sk-ant-..."
        />
        <ApiKeyCard
          providerKey="openai"
          label="OpenAI — GPT"
          placeholder="sk-..."
        />
        <ApiKeyCard
          providerKey="google"
          label="Google — Gemini"
          placeholder="AIza..."
        />
        <FontsCard />
      </div>
    </div>
  );
}
