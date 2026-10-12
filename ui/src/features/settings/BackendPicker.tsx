import { useQuery } from "@tanstack/react-query";
import { getBackends } from "../../lib/api";
import type { PhaseName } from "../../lib/types";
import { Select } from "../../components/ui/input";

/**
 * Technique selector for a phase, built from the backend registry
 * (GET /config/backends/{phase}). A newly registered backend shows up here
 * with its enum options — no UI change needed.
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
  const props = Object.entries(current?.options.properties ?? {}).filter(([, p]) => p.enum);

  return (
    <div className="flex flex-col gap-3">
      <Select
        label={label}
        value={value.backend}
        hint={current?.description}
        onChange={(e) => onChange({ backend: e.target.value, options: {} })}
      >
        {backends.length === 0 && <option value={value.backend}>{value.backend}</option>}
        {backends.map((b) => (
          <option key={b.name} value={b.name}>{b.name}</option>
        ))}
      </Select>
      {props.map(([key, p]) => (
        <Select
          key={key}
          label={`${label} · ${(p.title ?? key).toLowerCase()}`}
          hint={p.description}
          value={String(value.options[key] ?? p.default ?? "")}
          onChange={(e) => onChange({ ...value, options: { ...value.options, [key]: e.target.value } })}
        >
          {p.enum!.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
        </Select>
      ))}
    </div>
  );
}
