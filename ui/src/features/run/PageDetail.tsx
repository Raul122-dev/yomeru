import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  X,
  Code,
  MessageSquare,
  Hash,
  ArrowRight,
  Edit3,
  Check,
  AlertTriangle,
  Send,
  MapPin,
  Loader2,
} from "lucide-react";
import {
  pageImageUrl,
  saveEdit,
} from "../../lib/api";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

interface Dialogue {
  panel_index: number;
  speaker_id: string | null;
  text: string;
  text_translated?: string;
  tone: string;
  bubble_type: string;
  region_id?: number | null;
  font_style?: string | null;
  line_break_hint?: string | null;
  skip?: boolean;
}
interface Character {
  id: string;
  description: string;
  emotional_state: string;
  last_action: string;
}
interface Scene {
  location: string;
  mood: string;
  narrative_beat: string;
}
interface PageAnalysis {
  page_number: number;
  panel_count: number;
  reading_order: number[];
  dialogues: Dialogue[];
  characters_seen: Character[];
  scene: Scene;
  page_summary: string;
  _edited_at?: string;
}

type Tab = "dialogues" | "characters" | "json";

const BUBBLE_STYLES: Record<string, { icon: string; color: string; label: string }> = {
  speech: { icon: "💬", color: "#3b82f6", label: "Speech" },
  thought: { icon: "💭", color: "#a78bfa", label: "Thought" },
  narration: { icon: "📋", color: "#22c55e", label: "Narration" },
  sfx: { icon: "💥", color: "#ef4444", label: "SFX" },
  internal: { icon: "🗣", color: "#f59e0b", label: "Internal" },
};

interface PageDetailProps {
  runId: string;
  analysis: PageAnalysis;
  filename: string;
  onClose: () => void;
  onRequestReanalysis?: (corrections: Record<number, string>) => void;
  isPhaseRunning?: boolean;
}

export function PageDetail({
  runId,
  analysis: orig,
  filename,
  onClose,
  onRequestReanalysis,
  isPhaseRunning = false,
}: PageDetailProps) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("dialogues");
  const [imgError, setImgError] = useState(false);

  // Per-dialogue editing (translation only)
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editTranslation, setEditTranslation] = useState("");

  // Per-dialogue corrections for re-analysis
  const [corrections, setCorrections] = useState<Record<number, string>>({});
  const [showCorrectionIdx, setShowCorrectionIdx] = useState<number | null>(null);
  const [correctionDraft, setCorrectionDraft] = useState("");

  const hasCorrections = Object.keys(corrections).length > 0;

  const saveTranslationMut = useMutation({
    mutationFn: (payload: { idx: number; translation: string }) => {
      const updated = { ...orig, dialogues: orig.dialogues.map((d, i) =>
        i === payload.idx ? { ...d, text_translated: payload.translation } : d
      )};
      return saveEdit(runId, orig.page_number, updated);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
      setEditingIdx(null);
      setEditTranslation("");
    },
  });

  const toggleSkipMut = useMutation({
    mutationFn: (idx: number) => {
      const updated = { ...orig, dialogues: orig.dialogues.map((d, i) =>
        i === idx ? { ...d, skip: !d.skip } : d
      )};
      return saveEdit(runId, orig.page_number, updated);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
    },
  });

  const handleReanalysis = useCallback(() => {
    if (!onRequestReanalysis || !hasCorrections) return;
    onRequestReanalysis(corrections);
    setCorrections({});
  }, [onRequestReanalysis, hasCorrections, corrections]);

  const startEdit = (idx: number) => {
    setEditingIdx(idx);
    setEditTranslation(orig.dialogues[idx].text_translated ?? "");
  };

  const cancelEdit = () => {
    setEditingIdx(null);
    setEditTranslation("");
  };

  const saveTranslation = () => {
    if (editingIdx === null) return;
    saveTranslationMut.mutate({ idx: editingIdx, translation: editTranslation });
  };

  const addCorrection = useCallback((idx: number) => {
    if (!correctionDraft.trim()) return;
    setCorrections((prev) => ({ ...prev, [idx]: correctionDraft.trim() }));
    setCorrectionDraft("");
    setShowCorrectionIdx(null);
  }, [correctionDraft]);

  const removeCorrection = (idx: number) => {
    setCorrections((prev) => {
      const next = { ...prev };
      delete next[idx];
      return next;
    });
  };

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    {
      id: "dialogues",
      label: `Dialogues (${orig.dialogues.length})`,
      icon: <MessageSquare size={14} />,
    },
    {
      id: "characters",
      label: `Characters (${orig.characters_seen.length})`,
      icon: null,
    },
    { id: "json", label: "JSON", icon: <Code size={14} /> },
  ];

  const activeDialogues = orig.dialogues.filter((d) => !d.skip).length;
  const skippedDialogues = orig.dialogues.length - activeDialogues;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] shrink-0 px-5 py-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <span className="font-mono text-sm font-bold text-[hsl(var(--accent2))]">
              Page {orig.page_number}
            </span>
            {orig._edited_at && (
              <span className="rounded-full bg-[hsl(var(--accent2)/.15)] px-2 py-0.5 text-xs text-[hsl(var(--accent2))]">
                edited
              </span>
            )}
            <span className="text-sm text-[hsl(var(--text-muted))]">
              {activeDialogues} active{skippedDialogues > 0 && (
                <span className="text-[hsl(var(--danger))]"> · {skippedDialogues} skipped</span>
              )} / {orig.dialogues.length} total
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] hover:bg-[hsl(var(--bg))] transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Scene info */}
        <div className="flex gap-4">
          {!imgError && (
            <img
              src={pageImageUrl(runId, filename)}
              alt={filename}
              className="h-20 w-14 rounded border border-[hsl(var(--border))] object-cover shrink-0"
              onError={() => setImgError(true)}
            />
          )}
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-sm leading-relaxed text-[hsl(var(--text))]">
              {orig.page_summary}
            </p>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[hsl(var(--text-muted))]">
              <span className="flex items-center gap-1">
                <MapPin size={12} /> {orig.scene.location}
              </span>
              <span className="text-[hsl(var(--accent2))] font-medium">{orig.scene.mood}</span>
              <span>{orig.panel_count} panels</span>
            </div>
            {orig.scene.narrative_beat && (
              <p className="text-xs italic text-[hsl(var(--text-muted))]">
                {orig.scene.narrative_beat}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Tabs + Re-analysis bar */}
      <div className="flex items-center border-b border-[hsl(var(--border))] px-3 shrink-0">
        <div className="flex items-center gap-1 overflow-x-auto">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 px-4 py-2.5 text-sm transition-colors border-b-2",
                tab === t.id
                  ? "border-[hsl(var(--accent2))] text-[hsl(var(--accent2))] font-medium"
                  : "border-transparent text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {(hasCorrections || isPhaseRunning) && (
          <div className="ml-auto flex items-center gap-3 pr-1">
            {isPhaseRunning ? (
              <div className="flex items-center gap-2 text-sm text-[hsl(var(--accent))]">
                <Loader2 size={14} className="animate-spin" />
                Re-analyzing…
              </div>
            ) : (
              <>
                <span className="text-xs text-[hsl(var(--accent))] font-medium">
                  {Object.keys(corrections).length} correction{Object.keys(corrections).length > 1 ? "s" : ""} pending
                </span>
                <Button
                  size="sm"
                  onClick={handleReanalysis}
                  className="h-7 text-xs px-3 gap-1.5"
                >
                  <Send size={12} /> Re-analyze
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* ── dialogues ── */}
        {tab === "dialogues" &&
          (orig.dialogues.length === 0 ? (
            <p className="py-12 text-center text-sm text-[hsl(var(--text-muted))]">
              No dialogue detected on this page
            </p>
          ) : (
            orig.dialogues.map((d, i) => {
              const style = BUBBLE_STYLES[d.bubble_type] ?? BUBBLE_STYLES.speech;
              const isEditing = editingIdx === i;
              const hasCorr = corrections[i] !== undefined;
              const isSkipped = !!d.skip;

              return (
                <div
                  key={i}
                  className={cn(
                    "rounded-lg border overflow-hidden border-l-4 transition-all",
                    isSkipped ? "opacity-40 border-[hsl(var(--border))]" : "border-[hsl(var(--border))]",
                  )}
                  style={{ borderLeftColor: isSkipped ? "hsl(var(--text-muted))" : style.color }}
                >
                  {/* Dialogue header */}
                  <div className="flex items-center gap-3 px-4 py-2.5 bg-[hsl(var(--bg-subtle))] border-b border-[hsl(var(--border))]">
                    <span className="text-base">{style.icon}</span>
                    <span className="text-sm font-medium" style={{ color: isSkipped ? undefined : style.color }}>
                      {d.speaker_id ?? "narrator"}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded bg-[hsl(var(--bg))] text-[hsl(var(--text-muted))]">
                      {style.label}
                    </span>

                    <div className="ml-auto flex items-center gap-2 text-xs text-[hsl(var(--text-muted))]">
                      {d.region_id != null && (
                        <span className="flex items-center gap-0.5 rounded bg-[hsl(var(--accent2)/.1)] px-2 py-0.5 text-[hsl(var(--accent2))] font-mono text-xs">
                          <Hash size={10} />R{d.region_id}
                        </span>
                      )}
                      <span>Panel {d.panel_index}</span>
                      <span className="capitalize">{d.tone}</span>
                      {d.font_style && d.font_style !== "regular" && (
                        <span className="italic">{d.font_style}</span>
                      )}

                      {/* Skip toggle — proper switch style */}
                      <button
                        onClick={() => toggleSkipMut.mutate(i)}
                        disabled={toggleSkipMut.isPending}
                        className={cn(
                          "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-all border",
                          isSkipped
                            ? "bg-[hsl(var(--danger)/.1)] border-[hsl(var(--danger)/.3)] text-[hsl(var(--danger))] hover:bg-[hsl(var(--danger)/.2)]"
                            : "bg-[hsl(var(--success)/.1)] border-[hsl(var(--success)/.3)] text-[hsl(var(--success))] hover:bg-[hsl(var(--success)/.2)]",
                        )}
                        title={isSkipped ? "Click to include in next phases" : "Click to skip in next phases"}
                      >
                        {toggleSkipMut.isPending ? (
                          <Loader2 size={10} className="animate-spin" />
                        ) : isSkipped ? (
                          "Skipped"
                        ) : (
                          "Active"
                        )}
                      </button>

                      {/* Edit translation button */}
                      {!isEditing && !isSkipped && (
                        <button
                          onClick={() => startEdit(i)}
                          className="p-1 rounded text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.1)] transition-colors"
                          title="Edit translation"
                        >
                          <Edit3 size={13} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Content */}
                  <div className="p-4 space-y-2">
                    <p className={cn("text-sm leading-relaxed", isSkipped && "line-through")}>{d.text}</p>

                    {isEditing ? (
                      <div className="space-y-2 pt-1">
                        <textarea
                          className="w-full rounded border border-[hsl(var(--accent2)/.4)] bg-[hsl(var(--bg))] px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[hsl(var(--accent2)/.3)]"
                          rows={2}
                          value={editTranslation}
                          onChange={(e) => setEditTranslation(e.target.value)}
                          placeholder="Enter translation…"
                          autoFocus
                        />
                        <div className="flex gap-2">
                          <Button size="sm" onClick={saveTranslation} disabled={saveTranslationMut.isPending} className="h-7 text-xs gap-1">
                            <Check size={12} /> Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={cancelEdit} className="h-7 text-xs">
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : d.text_translated ? (
                      <div className="flex items-start gap-2 mt-1">
                        <ArrowRight size={14} className="mt-0.5 shrink-0 text-[hsl(var(--accent2))]" />
                        <p className={cn("text-sm leading-relaxed text-[hsl(var(--accent2))]", isSkipped && "line-through")}>
                          {d.text_translated}
                        </p>
                      </div>
                    ) : null}

                    {d.line_break_hint && !isSkipped && (
                      <p className="text-xs text-[hsl(var(--text-muted))] font-mono mt-1">
                        line breaks: {d.line_break_hint.replace(/\n/g, " / ")}
                      </p>
                    )}
                  </div>

                  {/* Correction section */}
                  {!isEditing && !isSkipped && (
                    <div className="border-t border-[hsl(var(--border))]">
                      {hasCorr ? (
                        <div className="flex items-start gap-2 px-4 py-2.5 bg-[hsl(var(--accent)/.06)]">
                          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[hsl(var(--accent))]" />
                          <p className="flex-1 text-sm text-[hsl(var(--accent))] leading-relaxed">
                            {corrections[i]}
                          </p>
                          <button
                            onClick={() => removeCorrection(i)}
                            className="shrink-0 p-1 rounded text-[hsl(var(--text-muted))] hover:text-[hsl(var(--danger))] hover:bg-[hsl(var(--danger)/.1)] transition-colors"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : showCorrectionIdx === i ? (
                        <div className="flex items-center gap-2 px-4 py-2.5">
                          <input
                            className="flex-1 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-1.5 text-sm placeholder:text-[hsl(var(--text-muted)/.5)] focus:outline-none focus:ring-2 focus:ring-[hsl(var(--accent)/.3)]"
                            placeholder="Describe the correction for re-analysis…"
                            value={correctionDraft}
                            onChange={(e) => setCorrectionDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") addCorrection(i);
                              if (e.key === "Escape") { setShowCorrectionIdx(null); setCorrectionDraft(""); }
                            }}
                            autoFocus
                          />
                          <Button size="sm" onClick={() => addCorrection(i)} disabled={!correctionDraft.trim()} className="h-7 text-xs px-3">
                            Add
                          </Button>
                          <button
                            onClick={() => { setShowCorrectionIdx(null); setCorrectionDraft(""); }}
                            className="p-1 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => { setShowCorrectionIdx(i); setCorrectionDraft(""); }}
                          className="w-full px-4 py-2 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] hover:bg-[hsl(var(--bg-subtle))] transition-colors text-left"
                        >
                          + Add correction for re-analysis
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          ))}

        {/* ── characters ── */}
        {tab === "characters" &&
          (orig.characters_seen.length === 0 ? (
            <p className="py-12 text-center text-sm text-[hsl(var(--text-muted))]">
              No characters identified
            </p>
          ) : (
            <div className="space-y-3">
              {orig.characters_seen.map((c, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-[hsl(var(--border))] p-4 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-[hsl(var(--accent))]">
                      {c.id}
                    </span>
                    <span className="text-xs rounded-full bg-[hsl(var(--accent2)/.1)] px-2.5 py-0.5 text-[hsl(var(--accent2))]">
                      {c.emotional_state}
                    </span>
                  </div>
                  <p className="text-sm text-[hsl(var(--text-muted))] leading-relaxed">
                    {c.description}
                  </p>
                  {c.last_action && (
                    <p className="text-xs text-[hsl(var(--text-muted))] italic">
                      → {c.last_action}
                    </p>
                  )}
                </div>
              ))}
            </div>
          ))}

        {/* ── json ── */}
        {tab === "json" && (
          <pre className="overflow-auto rounded-lg bg-[hsl(var(--bg))] border border-[hsl(var(--border))] p-4 font-mono text-xs text-[hsl(var(--text-muted))] leading-relaxed">
            {JSON.stringify(orig, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
