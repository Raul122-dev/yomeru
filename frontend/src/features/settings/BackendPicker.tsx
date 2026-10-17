import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { getBackends, getConfig } from "../../lib/api";
import type { BackendInfo, BackendOptionSchema, PhaseName } from "../../lib/types";
import { Button } from "../../components/ui/button";
import { Input, Select } from "../../components/ui/input";
import { Slider } from "../../components/ui/Slider";
import { Switch } from "../../components/ui/Switch";

/**
 * Technique selector for a phase + its options form, both generated from the
 * backend registry (GET /config/backends/{phase}): a newly registered backend
 * shows up here with its options — enum → select, bounded number → slider,
 * boolean → switch, list of objects → editable ordered list, other
 * text/number → input. Schema hints: `x-widget: "connection"` picks a saved
 * connection, `x-confirm: {value: message}` asks before choosing a value.
 * No UI change per plugin.
 */
export function BackendPicker({
  phase,
  label,
  value,
  onChange,
}: {
  phase: PhaseName;
  label: string;
  value: { backend: string; options: Record<string, unknown> };
  onChange: (v: { backend: string; options: Record<string, unknown> }) => void;
}) {
  const { data: backends = [] } = useQuery({
    queryKey: ["backends", phase],
    queryFn: () => getBackends(phase),
    staleTime: Infinity,
  });
  const current = backends.find((b) => b.name === value.backend);
  const props = Object.entries(current?.options.properties ?? {});
  const setOpt = (k: string, v: unknown) => onChange({ ...value, options: { ...value.options, [k]: v } });
  const missing = backends.length > 0 && !current;

  return (
    <div className="flex flex-col gap-3">
      <Select
        label={label}
        value={value.backend}
        hint={missing ? `"${value.backend}" is not installed` : current?.description}
        onChange={(e) => {
          const next = backends.find((b) => b.name === e.target.value);
          onChange({ backend: e.target.value, options: { ...(next?.defaults ?? {}) } });
        }}
      >
        {(backends.length === 0 || missing) && <option value={value.backend}>{value.backend}</option>}
        {backends.map((b: BackendInfo) => (
          <option key={b.name} value={b.name} disabled={!b.compatible}>
            {b.title ?? b.name}{b.compatible ? "" : " (incompatible)"}
          </option>
        ))}
      </Select>
      {props.map(([key, p]) => (
        <OptionField
          key={key}
          name={sentence(p.title ?? key)}
          schema={p}
          defs={current?.options.$defs}
          id={`${phase}-${key}`}
          value={value.options[key] ?? p.default}
          onChange={(v) => setOpt(key, v)}
        />
      ))}
    </div>
  );
}

type Defs = Record<string, BackendOptionSchema> | undefined;

function resolve(p: BackendOptionSchema | undefined, defs: Defs): BackendOptionSchema {
  if (!p) return {};
  return p.$ref ? (defs?.[p.$ref.split("/").pop() ?? ""] ?? {}) : p;
}

function OptionField({
  name,
  schema: p,
  defs,
  id,
  value,
  onChange,
}: {
  name: string;
  schema: BackendOptionSchema;
  defs: Defs;
  id: string;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (p.type === "array" && resolve(p.items, defs).properties) {
    return <ListField name={name} schema={p} defs={defs} id={id} value={value} onChange={onChange} />;
  }
  if (p["x-widget"] === "connection") {
    return <ConnectionField name={name} hint={p.description} id={id} value={value} onChange={onChange} />;
  }
  if (p.enum) {
    const confirmFor = p["x-confirm"] ?? {};
    return (
      <Select id={id} label={name} hint={p.description} value={String(value ?? "")}
        onChange={(e) => {
          const v = e.target.value;
          if (confirmFor[v] && !window.confirm(confirmFor[v])) return;
          onChange(v);
        }}>
        {p.enum.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
      </Select>
    );
  }
  if (p.type === "boolean") {
    return <Switch label={name} hint={p.description} checked={Boolean(value)} onCheckedChange={onChange} />;
  }
  const numeric = p.type === "number" || p.type === "integer";
  if (numeric && p.minimum !== undefined && p.maximum !== undefined) {
    const span = p.maximum - p.minimum;
    const step = p.type === "integer" ? 1 : span <= 0.5 ? 0.01 : span <= 1 ? 0.05 : 0.1;
    return (
      <Slider label={name} hint={p.description} value={Number(value ?? p.minimum)}
        min={p.minimum} max={p.maximum} step={step} onChange={onChange} />
    );
  }
  return (
    <Input
      id={id}
      label={name}
      hint={p.description}
      type={numeric ? "number" : "text"}
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(numeric ? Number(e.target.value) : e.target.value)}
    />
  );
}

function ConnectionField({ name, hint, id, value, onChange }: {
  name: string; hint?: string; id: string; value: unknown; onChange: (v: unknown) => void;
}) {
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const conns = cfg?.connections ?? [];
  const known = conns.some((c) => c.id === value);
  return (
    <Select id={id} label={name} hint={hint ?? (conns.length ? undefined : "Add a connection in Connections, above")}
      value={String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a connection</option>
      {!known && value ? <option value={String(value)}>{String(value)} (deleted)</option> : null}
      {conns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </Select>
  );
}

/** Ordered list of objects (e.g. a chain of models tried in order). */
function ListField({ name, schema: p, defs, id, value, onChange }: {
  name: string; schema: BackendOptionSchema; defs: Defs; id: string; value: unknown; onChange: (v: unknown) => void;
}) {
  const item = resolve(p.items, defs);
  const fields = Object.entries(item.properties ?? {});
  const list = (Array.isArray(value) ? value : []) as Record<string, unknown>[];
  const set = (i: number, k: string, v: unknown) => onChange(list.map((it, j) => (j === i ? { ...it, [k]: v } : it)));
  const move = (i: number, d: number) => {
    const next = [...list];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
  };
  const blank = Object.fromEntries(fields.map(([k, f]) => [k, f.default ?? (f.enum ? f.enum[0] : "")]));

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">{name}</p>
      {p.description && <p className="-mt-1 text-xs text-[hsl(var(--text-muted))]">{p.description}</p>}
      {list.map((it, i) => (
        <div key={i} className="rounded-md border border-[hsl(var(--border))] p-3">
          <div className="mb-2 flex items-center gap-1">
            <span className="font-mono text-xs text-[hsl(var(--text-muted))]">{i + 1}</span>
            <div className="ml-auto flex gap-0.5">
              <Button variant="ghost" size="icon" className="size-6" disabled={i === 0} onClick={() => move(i, -1)}
                aria-label="Move up" title="Try earlier"><ArrowUp size={12} /></Button>
              <Button variant="ghost" size="icon" className="size-6" disabled={i === list.length - 1}
                onClick={() => move(i, 1)} aria-label="Move down" title="Try later"><ArrowDown size={12} /></Button>
              <Button variant="ghost" size="icon" className="size-6" onClick={() => onChange(list.filter((_, j) => j !== i))}
                aria-label="Remove" title="Remove"><X size={12} /></Button>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {fields.map(([k, f]) => (
              <OptionField key={k} name={sentence(f.title ?? k)} defs={defs} id={`${id}-${i}-${k}`}
                schema={i === 0 ? f : { ...f, description: undefined }}   // hints once, not per item
                value={it[k] ?? f.default} onChange={(v) => set(i, k, v)} />
            ))}
          </div>
        </div>
      ))}
      <Button variant="outline" size="sm" className="self-start" onClick={() => onChange([...list, blank])}>
        <Plus size={12} /> Add
      </Button>
    </div>
  );
}

const ACRONYMS = /\b(ocr|api|gpu|vram|url|id|ids|cjk|lama|usd)\b/g;

function sentence(s: string) {
  const t = s.replace(/_/g, " ").toLowerCase().replace(ACRONYMS, (m) => (m === "lama" ? "LaMa" : m.toUpperCase()));
  return t.charAt(0).toUpperCase() + t.slice(1);
}
