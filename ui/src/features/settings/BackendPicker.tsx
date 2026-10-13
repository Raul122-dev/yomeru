import { useQuery } from "@tanstack/react-query";
import { getBackends } from "../../lib/api";
import type { BackendInfo, BackendOptionSchema, PhaseName } from "../../lib/types";
import { Input, Select } from "../../components/ui/input";
import { Slider } from "../../components/ui/Slider";
import { Switch } from "../../components/ui/Switch";

/**
 * Technique selector for a phase + its options form, both generated from the
 * backend registry (GET /config/backends/{phase}): a newly registered backend
 * shows up here with its options — enum → select, bounded number → slider,
 * boolean → switch, other text/number → input. No UI change per plugin.
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
            {b.name}{b.compatible ? "" : " (incompatible)"}
          </option>
        ))}
      </Select>
      {props.map(([key, p]) => (
        <OptionField
          key={key}
          name={(p.title ?? key).toLowerCase()}
          schema={p}
          value={value.options[key] ?? p.default}
          onChange={(v) => setOpt(key, v)}
        />
      ))}
    </div>
  );
}

function OptionField({
  name,
  schema: p,
  value,
  onChange,
}: {
  name: string;
  schema: BackendOptionSchema;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (p.enum) {
    return (
      <Select label={name} hint={p.description} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
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
      label={name}
      hint={p.description}
      type={numeric ? "number" : "text"}
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(numeric ? Number(e.target.value) : e.target.value)}
    />
  );
}
