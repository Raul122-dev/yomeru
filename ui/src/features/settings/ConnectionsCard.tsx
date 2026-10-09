import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plug, Plus, Trash2, Wifi, WifiOff } from "lucide-react";
import {
  createConnection,
  deleteConnection,
  getConfig,
  testConnection,
  testConnectionDraft,
  updateConnection,
  type ConnectionInput,
} from "../../lib/api";
import type { AppConfig, Connection, Protocol } from "../../lib/types";
import { Button } from "../../components/ui/button";
import { Input, Select } from "../../components/ui/input";
import { Card } from "../../components/ui/card";

const PROTOCOLS: { key: Protocol; label: string; hint: string; placeholder: string }[] = [
  {
    key: "openai",
    label: "OpenAI-compatible",
    hint: "OpenAI, OpenRouter, Ollama, LM Studio, vLLM, DeepSeek, Groq…",
    placeholder: "https://openrouter.ai/api/v1 · http://localhost:11434/v1",
  },
  {
    key: "anthropic",
    label: "Anthropic-compatible",
    hint: "Anthropic Messages API, or any proxy that speaks it",
    placeholder: "https://api.anthropic.com",
  },
];

const EMPTY: ConnectionInput = { name: "", protocol: "openai", base_url: "", api_key: "" };

function ConnectionForm({
  initial,
  onDone,
  onCancel,
}: {
  initial?: Connection;
  onDone: (cfg: AppConfig) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ConnectionInput>(
    initial
      ? { name: initial.name, protocol: initial.protocol, base_url: initial.base_url, api_key: initial.api_key }
      : EMPTY,
  );
  const [test, setTest] = useState<{ ok: boolean; models?: number; error?: string } | null>(null);
  const proto = PROTOCOLS.find((p) => p.key === draft.protocol)!;

  const save = useMutation({
    mutationFn: () => (initial ? updateConnection(initial.id, draft) : createConnection(draft)),
    onSuccess: onDone,
  });
  const check = useMutation({
    // Saved connection with untouched (masked) key → test server-side copy
    mutationFn: () =>
      initial && draft.api_key === initial.api_key
        ? testConnection(initial.id)
        : testConnectionDraft(draft),
    onSuccess: setTest,
    onError: (e: Error) => setTest({ ok: false, error: e.message }),
  });

  return (
    <div className="flex flex-col gap-3 rounded-md border border-[hsl(var(--border))] p-3">
      <Input
        label="name"
        value={draft.name}
        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        placeholder="OpenRouter"
      />
      <Select
        label="protocol"
        value={draft.protocol}
        onChange={(e) => setDraft({ ...draft, protocol: e.target.value as Protocol })}
      >
        {PROTOCOLS.map((p) => (
          <option key={p.key} value={p.key}>
            {p.label}
          </option>
        ))}
      </Select>
      <p className="-mt-1.5 text-xs text-[hsl(var(--text-muted))]">{proto.hint}</p>
      <Input
        label="base url"
        value={draft.base_url}
        onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
        placeholder={proto.placeholder}
        hint="Empty = the official endpoint of the protocol"
      />
      <Input
        label="api key"
        type="password"
        value={draft.api_key ?? ""}
        onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
        placeholder="Not needed for local servers"
      />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => save.mutate()} disabled={!draft.name.trim() || save.isPending}>
          {save.isPending ? "saving…" : "save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => check.mutate()} disabled={check.isPending}>
          {check.isPending ? "testing…" : "test"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          cancel
        </Button>
      </div>
      {test && (
        <p className={`flex items-center gap-1.5 text-xs ${test.ok ? "text-[hsl(var(--success))]" : "text-[hsl(var(--danger))]"}`}>
          {test.ok ? <Wifi size={12} /> : <WifiOff size={12} />}
          {test.ok ? `Connected · ${test.models} models` : test.error}
        </p>
      )}
      {save.error && <p className="text-xs text-[hsl(var(--danger))]">{(save.error as Error).message}</p>}
    </div>
  );
}

export function ConnectionsCard() {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const [editing, setEditing] = useState<string | "new" | null>(null);

  const done = (next: AppConfig) => {
    qc.setQueryData(["config"], next);
    qc.invalidateQueries({ queryKey: ["models"] });
    setEditing(null);
  };
  const remove = useMutation({ mutationFn: deleteConnection, onSuccess: done });

  const conns = cfg?.connections ?? [];
  return (
    <Card className="mb-4">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-sm font-medium">Connections</h2>
        {editing === null && (
          <Button size="sm" variant="ghost" onClick={() => setEditing("new")}>
            <Plus size={12} /> add
          </Button>
        )}
      </div>
      <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
        Where models are served. Two protocols cover everything: OpenAI-compatible and
        Anthropic-compatible.
      </p>
      <div className="flex flex-col gap-2">
        {conns.length === 0 && editing === null && (
          <p className="text-xs text-[hsl(var(--text-muted))]">
            No connections yet. Add one to pick models.
          </p>
        )}
        {conns.map((c) =>
          editing === c.id ? (
            <ConnectionForm key={c.id} initial={c} onDone={done} onCancel={() => setEditing(null)} />
          ) : (
            <div
              key={c.id}
              className="flex items-center gap-3 rounded-md border border-[hsl(var(--border))] px-3 py-2"
            >
              <Plug size={14} className="shrink-0 text-[hsl(var(--text-muted))]" />
              <div className="min-w-0 flex-1">
                <p className="text-sm">{c.name}</p>
                <p className="truncate font-mono text-xs text-[hsl(var(--text-muted))]">
                  {c.protocol} · {c.base_url || "official endpoint"}
                  {c.has_key && " · key " + c.api_key}
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setEditing(c.id)}>
                edit
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`delete ${c.name}`}
                onClick={() => confirm(`Delete connection "${c.name}"?`) && remove.mutate(c.id)}
              >
                <Trash2 size={12} />
              </Button>
            </div>
          ),
        )}
        {editing === "new" && <ConnectionForm onDone={done} onCancel={() => setEditing(null)} />}
      </div>
      {remove.isSuccess && (
        <p className="mt-2 flex items-center gap-1 text-xs text-[hsl(var(--text-muted))]">
          <Check size={12} /> removed
        </p>
      )}
    </Card>
  );
}
