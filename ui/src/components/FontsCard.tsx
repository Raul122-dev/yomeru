import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, Type, AlertCircle } from "lucide-react";
import { listFonts, uploadFont, deleteFont } from "../lib/api";
import type { FontInfo } from "../lib/types";
import { Card } from "./ui/card";
import { cn } from "../lib/utils";

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
        Fonts
      </h2>
      <p className="mb-4 text-xs text-[hsl(var(--text-muted))] leading-relaxed">
        Fonts yomeru can letter with. Choose which one draws speech, shouting,
        thought, narration and sound effects in the pipeline settings (Rendering → Fonts);
        by default each style uses the font made for the target language.
      </p>

      {(["user", "shipped"] as const).map((source) => {
        const list = fonts.filter((f) => f.source === source);
        if (!list.length) return null;
        return (
          <div key={source} className="mb-4 space-y-1">
            <p className="text-xs uppercase tracking-widest text-[hsl(var(--text-muted))] mb-2">
              {source === "user" ? `Your fonts (${list.length})` : `Included (${list.length})`}
            </p>
            {list.map((f) => (
              <div key={f.name}
                className="flex items-center gap-2 rounded px-2 py-1 hover:bg-[hsl(var(--bg-subtle))] group">
                <Type size={11} className="text-[hsl(var(--text-muted))]" />
                <span className="font-mono text-xs flex-1 truncate">{f.name}</span>
                <span className="text-xs text-[hsl(var(--text-muted)/.6)]">
                  {f.size_kb >= 1024 ? `${(f.size_kb / 1024).toFixed(1)} MB` : `${Math.round(f.size_kb)} KB`}
                </span>
                {source === "user" && (
                  <button onClick={() => remove.mutate(f.name)} aria-label={`Remove ${f.name}`} title="Remove"
                    className="opacity-0 group-hover:opacity-100 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--danger))] transition-all">
                    <Trash2 size={12} />
                  </button>
                )}
              </div>
            ))}
            {source === "shipped" && (
              <p className="px-2 pt-1 text-xs text-[hsl(var(--text-muted)/.8)]">
                Free fonts (SIL Open Font License, DejaVu license) — they can't be removed.
              </p>
            )}
          </div>
        );
      })}

      {isLoading && (
        <p className="text-xs text-[hsl(var(--text-muted))]">
          Loading fonts…
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
            ? "Uploading…"
            : "Drop .ttf / .otf / .ttc here, or click to browse"}
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
