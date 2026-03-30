/**
 * DialogueEditor — per-page editor for VLM analysis output.
 *
 * Lets users correct translations, speaker labels, tone, bubble_type,
 * and mark dialogues to skip during typesetting.
 *
 * Saves to page_analyses_refined.json via PUT /runs/{id}/analyses/{page}
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RotateCcw, ChevronDown, ChevronUp, X } from "lucide-react";
import { cn } from "../lib/utils";

// ── types ─────────────────────────────────────────────────────────────────────

export interface Dialogue {
  region_id?: number | null;
  speaker?: string;
  tone?: string;
  bubble_type?: string;
  text?: string;
  text_translated?: string;
  text_position?: string;
}

export interface PageAnalysis {
  page_number: number;
  dialogues: Dialogue[];
  page_summary?: string;
  source_language?: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function saveAnalysisPage(
  runId: string,
  pageNum: number,
  pageData: PageAnalysis,
) {
  const res = await fetch(`/api/runs/${runId}/analyses/${pageNum}/refined`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pageData),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function revertAnalysisPage(runId: string, pageNum: number) {
  const res = await fetch(`/api/runs/${runId}/analyses/${pageNum}/refined`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── constants ─────────────────────────────────────────────────────────────────

const TONES = [
  "neutral",
  "shouting",
  "whispering",
  "laughing",
  "crying",
  "thinking",
  "surprised",
];
const BUBBLE_TYPES = ["speech", "thought", "narration", "sfx", "internal"];

// ── single dialogue row ───────────────────────────────────────────────────────

function DialogueRow({
  dialogue,
  index,
  onChange,
}: {
  dialogue: Dialogue;
  index: number;
  onChange: (d: Dialogue) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-[hsl(var(--border))] last:border-0">
      {/* main row */}
      <div className="flex items-start gap-2 px-3 py-2.5">
        {/* region id + index */}
        <div className="flex items-center gap-1.5 shrink-0 mt-1">
          <span className="font-mono text-[10px] text-[hsl(var(--text-muted))]">
            {index}
          </span>
          {dialogue.region_id != null && (
            <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
              r{dialogue.region_id}
            </span>
          )}
        </div>

        {/* translation text */}
        <div className="flex-1 min-w-0 space-y-1">
          {/* original (readonly reference) */}
          {dialogue.text && (
            <p className="text-[10px] text-[hsl(var(--text-muted)/.6)] truncate italic">
              "{dialogue.text}"
            </p>
          )}
          {/* translated (editable) */}
          <textarea
            value={dialogue.text_translated ?? ""}
            onChange={(e) =>
              onChange({ ...dialogue, text_translated: e.target.value })
            }
            placeholder={
              dialogue.text_translated ? undefined : "no translation"
            }
            rows={2}
            className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-1 text-[11px] leading-relaxed resize-none focus:border-[hsl(var(--accent2))] focus:outline-none"
          />
        </div>

        {/* expand toggle */}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-[hsl(var(--text-muted)/.4)] hover:text-[hsl(var(--text-muted))] transition-colors shrink-0"
        >
          {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
      </div>

      {/* expanded fields */}
      {expanded && (
        <div className="px-3 pb-3 pt-0 grid grid-cols-3 gap-3">
          {/* speaker */}
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              speaker
            </p>
            <input
              value={dialogue.speaker ?? ""}
              onChange={(e) =>
                onChange({ ...dialogue, speaker: e.target.value })
              }
              placeholder="unknown"
              className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-0.5 text-[11px] focus:border-[hsl(var(--accent2))] focus:outline-none"
            />
          </div>

          {/* tone */}
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              tone
            </p>
            <select
              value={dialogue.tone ?? "neutral"}
              onChange={(e) => onChange({ ...dialogue, tone: e.target.value })}
              className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-1.5 py-0.5 text-[11px] focus:border-[hsl(var(--accent2))] focus:outline-none"
            >
              {TONES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          {/* bubble type */}
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              type
            </p>
            <select
              value={dialogue.bubble_type ?? "speech"}
              onChange={(e) =>
                onChange({ ...dialogue, bubble_type: e.target.value })
              }
              className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-1.5 py-0.5 text-[11px] focus:border-[hsl(var(--accent2))] focus:outline-none"
            >
              {BUBBLE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

interface DialogueEditorProps {
  runId: string;
  pageNum: number;
  pageData: PageAnalysis;
  onClose?: () => void;
  onSaved?: () => void;
}

export function DialogueEditor({
  runId,
  pageNum,
  pageData,
  onClose,
  onSaved,
}: DialogueEditorProps) {
  const qc = useQueryClient();
  const [dialogues, setDialogues] = useState<Dialogue[]>(
    pageData.dialogues ?? [],
  );
  const [isDirty, setIsDirty] = useState(false);

  const updateDialogue = (index: number, d: Dialogue) => {
    setDialogues((prev) => prev.map((x, i) => (i === index ? d : x)));
    setIsDirty(true);
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      saveAnalysisPage(runId, pageNum, { ...pageData, dialogues }),
    onSuccess: () => {
      setIsDirty(false);
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
      onSaved?.();
    },
  });

  const revertMutation = useMutation({
    mutationFn: () => revertAnalysisPage(runId, pageNum),
    onSuccess: () => {
      setDialogues(pageData.dialogues ?? []);
      setIsDirty(false);
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
      onSaved?.();
    },
  });

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden">
      {/* header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
        <span className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
          dialogue editor · p{pageNum}
        </span>
        <span className="text-[10px] text-[hsl(var(--text-muted)/.5)]">
          {dialogues.length} dialogues
        </span>
        {isDirty && (
          <span className="text-[9px] text-[hsl(var(--accent2))]">unsaved</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => revertMutation.mutate()}
            disabled={revertMutation.isPending}
            className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
          >
            <RotateCcw size={9} /> revert
          </button>
          <button
            onClick={() => saveMutation.mutate()}
            disabled={!isDirty || saveMutation.isPending}
            className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-[11px] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
          >
            <Save size={10} />{" "}
            {saveMutation.isPending ? "saving…" : "save refined"}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--text))] transition-colors"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* dialogues */}
      {dialogues.length === 0 ? (
        <div className="px-4 py-8 text-center text-xs text-[hsl(var(--text-muted))]">
          no dialogues on this page
        </div>
      ) : (
        <div className="max-h-96 overflow-y-auto">
          {dialogues.map((d, i) => (
            <DialogueRow
              key={i}
              dialogue={d}
              index={i}
              onChange={(updated) => updateDialogue(i, updated)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
