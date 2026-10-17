import { useQuery } from "@tanstack/react-query";
import { listFonts } from "../../lib/api";
import { Select } from "../../components/ui/input";

const STYLE_LABEL: Record<string, string> = {
  regular: "Speech",
  bold: "Shouting & free text",
  thought: "Thought",
  narration: "Narration",
  sfx: "Sound effects",
};

/** Which font letters each style. Empty = the default for the target language. */
export function FontStylesField({ value, onChange }: {
  value: Record<string, string> | undefined;
  onChange: (fonts: Record<string, string>) => void;
}) {
  const { data } = useQuery({ queryKey: ["fonts"], queryFn: listFonts });
  if (!data) return null;
  const fonts = value ?? {};
  const latin = data.defaults.latin ?? {};
  const set = (style: string, name: string) => {
    const next = { ...fonts };
    if (name) next[style] = name;
    else delete next[style];
    onChange(next);
  };
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">Fonts</p>
      <p className="-mt-1 text-xs text-[hsl(var(--text-muted))]">
        Add your own fonts in Settings → Fonts. "Default" follows the target language.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.styles.map((style) => (
          <Select key={style} id={`font-${style}`} label={STYLE_LABEL[style] ?? style}
            value={fonts[style] ?? ""} onChange={(e) => set(style, e.target.value)}>
            <option value="">Default{latin[style] ? ` (${latin[style].replace(/\.(ttf|otf|ttc)$/i, "")})` : ""}</option>
            {fonts[style] && !data.fonts.some((f) => f.name === fonts[style]) && (
              <option value={fonts[style]}>{fonts[style]} (missing)</option>
            )}
            {data.fonts.map((f) => (
              <option key={f.name} value={f.name}>
                {f.name.replace(/\.(ttf|otf|ttc)$/i, "")}{f.source === "user" ? " (yours)" : ""}
              </option>
            ))}
          </Select>
        ))}
      </div>
    </div>
  );
}
