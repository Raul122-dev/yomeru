import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  X,
  Code,
  MessageSquare,
  Users,
  Image,
  Edit3,
  StickyNote,
  RotateCcw,
  Check,
  Plus,
  Trash2,
} from "lucide-react";
import {
  pageImageUrl,
  getAnnotations,
  addAnnotation,
  deleteAnnotation,
  saveEdit,
  revertEdit,
} from "../lib/api";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";

interface Dialogue {
  panel_index: number;
  speaker_id: string | null;
  text: string;
  text_translated?: string;
  tone: string;
  bubble_type: string;
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

type Tab =
  | "overview"
  | "dialogues"
  | "characters"
  | "annotate"
  | "edit"
  | "json";

const BUBBLE_ICONS: Record<string, string> = {
  speech: "💬",
  thought: "💭",
  narration: "📋",
  sfx: "💥",
  internal: "🗣",
};

interface PageDetailProps {
  runId: string;
  analysis: PageAnalysis;
  filename: string;
  onClose: () => void;
}

export function PageDetail({
  runId,
  analysis: orig,
  filename,
  onClose,
}: PageDetailProps) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");
  const [imgError, setImgError] = useState(false);

  // edit state — deep copy of analysis
  const [editDraft, setEditDraft] = useState<PageAnalysis>(() =>
    JSON.parse(JSON.stringify(orig)),
  );
  const [editDirty, setEditDirty] = useState(false);

  // annotation state
  const [newNote, setNewNote] = useState("");
  const [newField, setNewField] = useState("");

  const { data: annData } = useQuery({
    queryKey: ["annotations", runId, orig.page_number],
    queryFn: () => getAnnotations(runId),
    enabled: tab === "annotate",
  });
  const pageAnnotations = (annData?.annotations?.[String(orig.page_number)] ??
    []) as Record<string, string>[];

  const isEdited = !!orig._edited_at;

  const saveEditMut = useMutation({
    mutationFn: () => saveEdit(runId, orig.page_number, editDraft),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
      setEditDirty(false);
    },
  });

  const revertEditMut = useMutation({
    mutationFn: () => revertEdit(runId, orig.page_number),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analyses", runId] });
      setEditDirty(false);
    },
  });

  const addAnn = useMutation({
    mutationFn: () =>
      addAnnotation(runId, orig.page_number, {
        field: newField,
        note: newNote,
        original_value: "",
      }),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["annotations", runId, orig.page_number],
      });
      setNewNote("");
      setNewField("");
    },
  });

  const delAnn = useMutation({
    mutationFn: (id: string) => deleteAnnotation(runId, orig.page_number, id),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ["annotations", runId, orig.page_number],
      }),
  });

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: "overview", label: "overview", icon: <Image size={12} /> },
    {
      id: "dialogues",
      label: `${orig.dialogues.length}d`,
      icon: <MessageSquare size={12} />,
    },
    {
      id: "characters",
      label: `${orig.characters_seen.length}c`,
      icon: <Users size={12} />,
    },
    {
      id: "annotate",
      label: `notes${pageAnnotations.length ? ` (${pageAnnotations.length})` : ""}`,
      icon: <StickyNote size={12} />,
    },
    {
      id: "edit",
      label: isEdited ? "edited ✓" : "edit",
      icon: <Edit3 size={12} />,
    },
    { id: "json", label: "json", icon: <Code size={12} /> },
  ];

  const updateDraft = (path: string[], value: unknown) => {
    setEditDraft((prev) => {
      const next = JSON.parse(JSON.stringify(prev));
      let cur: Record<string, unknown> = next;
      for (let i = 0; i < path.length - 1; i++)
        cur = cur[path[i]] as Record<string, unknown>;
      cur[path[path.length - 1]] = value;
      return next;
    });
    setEditDirty(true);
  };

  return (
    <div className="flex h-full flex-col text-sm">
      {/* header */}
      <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="font-mono font-medium">
            p{String(orig.page_number).padStart(2, "0")}
          </span>
          <span className="text-xs text-[hsl(var(--accent2))]">
            {orig.scene.mood}
          </span>
          {isEdited && (
            <span className="rounded-full bg-[hsl(var(--accent2)/.1)] px-2 py-0.5 text-[10px] text-[hsl(var(--accent2))]">
              edited
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* tabs */}
      <div className="flex gap-0.5 overflow-x-auto border-b border-[hsl(var(--border))] px-3 pt-1.5">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex shrink-0 items-center gap-1 rounded-t px-2.5 py-1 text-xs transition-colors",
              tab === t.id
                ? "border-b-2 border-[hsl(var(--accent2))] text-[hsl(var(--accent2))]"
                : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* ── overview ── */}
        {tab === "overview" && (
          <>
            {!imgError && (
              <img
                src={pageImageUrl(runId, filename)}
                alt={filename}
                className="w-full rounded border border-[hsl(var(--border))] object-contain max-h-72"
                onError={() => setImgError(true)}
              />
            )}
            <p className="text-xs leading-relaxed">{orig.page_summary}</p>
            <div className="rounded bg-[hsl(var(--bg-subtle))] p-2.5 text-xs space-y-1.5">
              {[
                ["location", orig.scene.location],
                ["mood", orig.scene.mood],
                ["panels", String(orig.panel_count)],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-[hsl(var(--text-muted))]">{k}</span>
                  <span
                    className={k === "mood" ? "text-[hsl(var(--accent2))]" : ""}
                  >
                    {v}
                  </span>
                </div>
              ))}
              <div className="flex justify-between">
                <span className="text-[hsl(var(--text-muted))]">
                  reading order
                </span>
                <span className="font-mono text-[10px]">
                  [{orig.reading_order.join(",")}]
                </span>
              </div>
            </div>
            <p className="text-xs text-[hsl(var(--text-muted))]">
              {orig.scene.narrative_beat}
            </p>
          </>
        )}

        {/* ── dialogues ── */}
        {tab === "dialogues" &&
          (orig.dialogues.length === 0 ? (
            <p className="text-xs text-[hsl(var(--text-muted))]">no dialogue</p>
          ) : (
            orig.dialogues.map((d, i) => (
              <div
                key={i}
                className="rounded border border-[hsl(var(--border))] p-2.5 space-y-1"
              >
                <div className="flex items-center gap-2 text-xs">
                  <span>{BUBBLE_ICONS[d.bubble_type] ?? "💬"}</span>
                  <span className="font-medium text-[hsl(var(--accent))]">
                    {d.speaker_id ?? "narrator"}
                  </span>
                  <span className="ml-auto text-[hsl(var(--text-muted))]">
                    p{d.panel_index} · {d.tone}
                  </span>
                </div>
                <p className="text-xs leading-relaxed">{d.text}</p>
              </div>
            ))
          ))}

        {/* ── characters ── */}
        {tab === "characters" &&
          (orig.characters_seen.length === 0 ? (
            <p className="text-xs text-[hsl(var(--text-muted))]">
              no characters
            </p>
          ) : (
            orig.characters_seen.map((c, i) => (
              <div
                key={i}
                className="rounded border border-[hsl(var(--border))] p-2.5 space-y-1"
              >
                <p className="text-xs font-medium text-[hsl(var(--accent))]">
                  {c.id}
                </p>
                <p className="text-xs text-[hsl(var(--text-muted))]">
                  {c.description}
                </p>
                <div className="flex gap-3 text-xs">
                  <span className="text-[hsl(var(--accent2))]">
                    {c.emotional_state}
                  </span>
                  <span className="text-[hsl(var(--text-muted))]">
                    {c.last_action}
                  </span>
                </div>
              </div>
            ))
          ))}

        {/* ── annotate ── */}
        {tab === "annotate" && (
          <div className="space-y-3">
            <div className="space-y-2">
              <input
                className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2.5 py-1.5 text-xs placeholder:text-[hsl(var(--text-muted))]"
                value={newField}
                onChange={(e) => setNewField(e.target.value)}
                placeholder="field (optional) — e.g. dialogues[0].text, scene.mood"
              />
              <textarea
                className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2.5 py-1.5 text-xs placeholder:text-[hsl(var(--text-muted))] resize-none"
                rows={3}
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                placeholder="describe the issue or correction needed…"
              />
              <Button
                size="sm"
                onClick={() => addAnn.mutate()}
                disabled={!newNote.trim() || addAnn.isPending}
              >
                <Plus size={12} /> add note
              </Button>
            </div>
            <div className="space-y-2">
              {pageAnnotations.length === 0 && (
                <p className="text-xs text-[hsl(var(--text-muted))]">
                  no notes yet
                </p>
              )}
              {pageAnnotations.map((a) => (
                <div
                  key={a.id}
                  className="rounded border border-[hsl(var(--border))] p-2.5"
                >
                  {a.field && (
                    <p className="mb-1 font-mono text-[10px] text-[hsl(var(--accent2))]">
                      {a.field}
                    </p>
                  )}
                  <p className="text-xs">{a.note}</p>
                  <div className="mt-1.5 flex items-center justify-between">
                    <span className="text-[10px] text-[hsl(var(--text-muted))]">
                      {new Date(a.created_at).toLocaleString()}
                    </span>
                    <button
                      onClick={() => delAnn.mutate(a.id)}
                      className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--danger))] transition-colors"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── edit ── */}
        {tab === "edit" && (
          <div className="space-y-3">
            <p className="text-xs text-[hsl(var(--text-muted))]">
              Edit the model output directly. Original is always preserved in
              page_analyses.json.
            </p>

            {/* scene */}
            <div className="rounded border border-[hsl(var(--border))] p-2.5 space-y-2">
              <p className="text-xs font-medium">scene</p>
              {(["location", "mood", "narrative_beat"] as const).map(
                (field) => (
                  <div key={field}>
                    <label className="text-[10px] text-[hsl(var(--text-muted))] uppercase tracking-wide">
                      {field}
                    </label>
                    <input
                      className="mt-0.5 w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-1 text-xs"
                      value={editDraft.scene[field]}
                      onChange={(e) =>
                        updateDraft(["scene", field], e.target.value)
                      }
                    />
                  </div>
                ),
              )}
            </div>

            {/* dialogues */}
            <div className="space-y-2">
              <p className="text-xs font-medium">dialogues</p>
              {editDraft.dialogues.map((d, i) => (
                <div
                  key={i}
                  className="rounded border border-[hsl(var(--border))] p-2.5 space-y-1.5"
                >
                  <div className="flex items-center gap-1.5 text-[10px] text-[hsl(var(--text-muted))]">
                    <span>p{d.panel_index}</span>
                    <span>·</span>
                    <span>{d.speaker_id ?? "narrator"}</span>
                    <span>·</span>
                    <span>{d.tone}</span>
                  </div>
                  <textarea
                    className="w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-1 text-xs resize-none"
                    rows={2}
                    value={d.text}
                    onChange={(e) =>
                      updateDraft(
                        ["dialogues", String(i), "text"],
                        e.target.value,
                      )
                    }
                  />
                  {d.text_translated !== undefined && (
                    <div>
                      <label className="text-[9px] uppercase tracking-wide text-[hsl(var(--accent2))]">
                        translation
                      </label>
                      <textarea
                        className="mt-0.5 w-full rounded border border-[hsl(var(--accent2)/.3)] bg-[hsl(var(--accent2)/.04)] px-2 py-1 text-xs resize-none"
                        rows={2}
                        value={d.text_translated ?? ""}
                        onChange={(e) =>
                          updateDraft(
                            ["dialogues", String(i), "text_translated"],
                            e.target.value,
                          )
                        }
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* page summary */}
            <div>
              <label className="text-[10px] text-[hsl(var(--text-muted))] uppercase tracking-wide">
                page summary
              </label>
              <textarea
                className="mt-0.5 w-full rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-2 py-1 text-xs resize-none"
                rows={3}
                value={editDraft.page_summary}
                onChange={(e) => updateDraft(["page_summary"], e.target.value)}
              />
            </div>

            <div className="flex gap-2 pt-1">
              <Button
                size="sm"
                onClick={() => saveEditMut.mutate()}
                disabled={!editDirty || saveEditMut.isPending}
              >
                <Check size={12} />{" "}
                {saveEditMut.isPending ? "saving…" : "save edits"}
              </Button>
              {isEdited && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => revertEditMut.mutate()}
                  disabled={revertEditMut.isPending}
                >
                  <RotateCcw size={12} /> revert to original
                </Button>
              )}
            </div>
          </div>
        )}

        {/* ── json ── */}
        {tab === "json" && (
          <pre className="overflow-auto rounded bg-[hsl(var(--bg))] p-2.5 font-mono text-[10px] text-[hsl(var(--text-muted))] leading-relaxed">
            {JSON.stringify(orig, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
