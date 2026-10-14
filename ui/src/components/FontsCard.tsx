import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, Type, AlertCircle } from "lucide-react";
import { listFonts, uploadFont, deleteFont } from "../lib/api";
import type { FontInfo } from "../lib/types";
import { Card } from "./ui/card";
import { cn } from "../lib/utils";

// Mirrors lib/rendering/pil.py _FONT_STYLES: for each style the FIRST
// installed file in the list is used.
const FONT_SLOTS = [
  { name: "ComicNeue-Bold.ttf", style: "regular · bold", note: "1st choice for speech and shouting" },
  { name: "ComicNeue-Regular.ttf", style: "thought · narration", note: "1st choice" },
  { name: "AnimeAce.ttf", style: "regular · thought · narration", note: "used if ComicNeue is missing" },
  { name: "Bangers-Regular.ttf", style: "bold", note: "used if ComicNeue-Bold is missing" },
  { name: "CC Wild Words Roman.ttf", style: "regular", note: "after AnimeAce" },
  { name: "NotoSansCJK-Regular.ttc", style: "CJK", note: "Japanese, Korean, Chinese text" },
];

export function FontsCard() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["fonts"],
    queryFn: listFonts,
  });

  const upload = useMutation({
    mutationFn: uploadFont,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fonts"] });
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const remove = useMutation({
    mutationFn: deleteFont,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fonts"] }),
  });

  const fonts: FontInfo[] = data?.fonts ?? [];

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      upload.mutate(f);
    }
  };

  return (
    <Card className="mb-4">
      <h2 className="mb-1 text-sm font-medium flex items-center gap-2">
        <Type size={13} className="text-[hsl(var(--accent2))]" />
        fonts
      </h2>
      <p className="mb-4 text-xs text-[hsl(var(--text-muted))] leading-relaxed">
        Upload fonts via drag-and-drop below, or copy them manually to{" "}
        <code className="font-mono text-xs bg-[hsl(var(--bg-subtle))] px-1 rounded">
          src/yomeru/assets/fonts/
        </code>
        . The renderer picks fonts by file name: for each style it uses the first
        installed file in the order below. Other uploaded fonts are only used as a
        last resort. Re-rendering picks up font changes.
      </p>

      {/* recommended slots */}
      <div className="mb-4 rounded-md border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))]">
        {FONT_SLOTS.map((slot) => {
          const installed = fonts.some((f) => f.name === slot.name);
          return (
            <div key={slot.name} className="flex items-center gap-3 px-3 py-2">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full shrink-0",
                  installed
                    ? "bg-[hsl(var(--success))]"
                    : "bg-[hsl(var(--border-strong))]",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="font-mono text-xs text-[hsl(var(--text))] truncate">
                  {slot.name}
                </p>
                <p className="text-xs text-[hsl(var(--text-muted))]">
                  {slot.style} — {slot.note}
                </p>
              </div>
              <span
                className={cn(
                  "text-xs shrink-0",
                  installed
                    ? "text-[hsl(var(--success))]"
                    : "text-[hsl(var(--text-muted)/.5)]",
                )}
              >
                {installed ? "installed" : "missing"}
              </span>
            </div>
          );
        })}
      </div>

      {/* installed fonts (including any extra ones) */}
      {fonts.length > 0 && (
        <div className="mb-4 space-y-1">
          <p className="text-xs uppercase tracking-widest text-[hsl(var(--text-muted))] mb-2">
            installed ({fonts.length})
          </p>
          {fonts.map((f) => (
            <div
              key={f.name}
              className="flex items-center gap-2 rounded px-2 py-1 hover:bg-[hsl(var(--bg-subtle))] group"
            >
              <Type size={11} className="text-[hsl(var(--text-muted))]" />
              <span className="font-mono text-xs flex-1 truncate">
                {f.name}
              </span>
              <span className="text-xs text-[hsl(var(--text-muted)/.6)]">
                {f.size_kb} KB
              </span>
              <button
                onClick={() => remove.mutate(f.name)}
                className="opacity-0 group-hover:opacity-100 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--danger))] transition-all"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {isLoading && (
        <p className="text-xs text-[hsl(var(--text-muted))]">
          loading fonts…
        </p>
      )}

      {/* upload area */}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 transition-colors",
          upload.isPending
            ? "border-[hsl(var(--accent2)/.5)] bg-[hsl(var(--accent2)/.04)]"
            : "border-[hsl(var(--border))] hover:border-[hsl(var(--accent2)/.5)] hover:bg-[hsl(var(--bg-subtle))]",
        )}
      >
        <Upload size={16} className="text-[hsl(var(--text-muted))]" />
        <p className="text-xs text-[hsl(var(--text-muted))] text-center">
          {upload.isPending
            ? "uploading…"
            : "drop .ttf / .otf / .ttc here, or click to browse"}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".ttf,.otf,.ttc"
          multiple
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {error && (
        <div className="mt-2 flex items-center gap-2 text-xs text-[hsl(var(--danger))]">
          <AlertCircle size={12} />
          {error}
        </div>
      )}
    </Card>
  );
}
