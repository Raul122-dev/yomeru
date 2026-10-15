import { useQuery } from "@tanstack/react-query";
import { getConfig, getConnectionModels } from "../../lib/api";
import type { ModelRef } from "../../lib/types";
import { Select } from "../../components/ui/input";
import { Combobox } from "../../components/ui/Combobox";

/** Connection + model selector. Models are fetched from the chosen connection. */
export function ModelPicker({
  label,
  hint,
  value,
  onChange,
  requireVision = false,
  allowNone = false,
}: {
  label: string;
  hint?: string;
  value: ModelRef;
  onChange: (v: ModelRef) => void;
  requireVision?: boolean;
  allowNone?: boolean;
}) {
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const conns = cfg?.connections ?? [];
  const { data: models = [], isLoading, error } = useQuery({
    queryKey: ["models", value.connection_id],
    queryFn: () => getConnectionModels(value.connection_id),
    enabled: !!value.connection_id,
    staleTime: 5 * 60_000,
    retry: 0,
  });
  const selected = models.find((m) => m.id === value.model);

  return (
    <div className="flex flex-col gap-2">
      <Select
        label={label}
        value={value.connection_id}
        onChange={(e) => onChange({ connection_id: e.target.value, model: "" })}
      >
        {(allowNone || !value.connection_id) && (
          <option value="">{allowNone ? "— Same as the reading model —" : "— Choose a connection —"}</option>
        )}
        {conns.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </Select>
      {value.connection_id && (
        <Combobox
          value={value.model}
          items={models}
          loading={isLoading}
          placeholder="Type or pick a model ID"
          showVisionBadge={requireVision}
          onChange={(m) => onChange({ ...value, model: m })}
        />
      )}
      {error && (
        <p className="text-xs text-[hsl(var(--danger))]">{(error as Error).message}</p>
      )}
      {requireVision && selected?.vision === false && (
        <p className="text-xs text-[hsl(var(--danger))]">
          This model does not accept images — Read & translate needs a vision model.
        </p>
      )}
      {hint && <p className="text-xs text-[hsl(var(--text-muted))]">{hint}</p>}
    </div>
  );
}
