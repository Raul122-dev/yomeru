import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ImageViewer } from "../ui/ImageViewer";
import { RenderLog } from "./RenderLog";
import { MatchingEditor } from "./MatchingEditor";
import { MaskEditor } from "./MaskEditor";
import { debugImageUrl } from "../../lib/api";
import type {
  StageLog,
  MatchEvent,
  DetectionRegion,
  RenderEvent,
  OrphanedRegion,
} from "../../lib/api";
import { cn } from "../../lib/utils";

// ── shared sub-components ─────────────────────────────────────────────────────

function DataPanel({
  title,
  count,
  children,
  defaultOpen = false,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded border border-[hsl(var(--border))] overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 bg-[hsl(var(--bg-subtle))] hover:bg-[hsl(var(--border)/.3)] transition-colors text-left"
      >
        <span className="text-[10px] font-medium uppercase tracking-widest text-[hsl(var(--text-muted))]">
          {title}
        </span>
        <div className="flex items-center gap-2">
          {count != null && (
            <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
              {count}
            </span>
          )}
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </div>
      </button>
      {open && <div className="p-2.5 space-y-1.5">{children}</div>}
    </div>
  );
}

function KV({
  k,
  v,
  mono = false,
}: {
  k: string;
  v: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-[10px]">
      <span className="text-[hsl(var(--text-muted))] shrink-0">{k}</span>
      <span
        className={cn(
          "truncate text-right",
          mono && "font-mono text-[hsl(var(--accent2))]",
        )}
      >
        {v}
      </span>
    </div>
  );
}

function ScoreBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-16 rounded-full bg-[hsl(var(--border))] overflow-hidden shrink-0">
        <div
          className="h-full rounded-full bg-[hsl(var(--accent2))]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

// ── S2 detection data ─────────────────────────────────────────────────────────

function S2Data({ data }: { data: StageLog["s2_detection"] }) {
  return (
    <DataPanel title="detection data" count={data.regions_found ?? 0}>
      <KV k="source" v={data.source} mono />
      <KV k="regions found" v={data.regions_found} mono />
      {data.regions.length > 0 && (
        <div className="mt-1 rounded border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))]">
          {data.regions.map((r: DetectionRegion) => (
            <div
              key={r.id}
              className="flex items-center gap-2 px-2 py-1 font-mono text-[10px]"
            >
              <span className="text-[hsl(var(--accent2))] w-5 text-right shrink-0">
                [{r.id}]
              </span>
              <span className="text-[hsl(var(--text-muted))] w-20 shrink-0">
                {r.label}
              </span>
              <span className="text-[hsl(var(--text-muted))]">
                {r.size[0]}×{r.size[1]}px
              </span>
              <span className="ml-auto text-[hsl(var(--text-muted)/.7)]">
                {(r.score * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </DataPanel>
  );
}

// ── S3 matching data ──────────────────────────────────────────────────────────

function S3Data({ data }: { data: StageLog["s3_matching"] }) {
  const hasOrphans = data.orphaned_regions > 0;
  return (
    <DataPanel title="matching data" count={data.matched}>
      {/* summary */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <KV k="total dialogues" v={data.total_dialogues} mono />
        <KV k="matched" v={data.matched} mono />
        <KV k="direct (region_id)" v={data.direct} mono />
        <KV k="fallback (hungarian)" v={data.fallback} mono />
        <KV k="unmatched dialogues" v={data.unmatched_dialogues} mono />
        <KV
          k="orphaned regions"
          v={
            <span className={hasOrphans ? "text-[hsl(var(--danger))]" : ""}>
              {data.orphaned_regions}
            </span>
          }
        />
      </div>

      {/* orphaned regions — bubbles the VLM missed */}
      {hasOrphans && (
        <div className="mt-2 rounded border border-[hsl(var(--danger)/.4)] bg-[hsl(var(--danger)/.04)] overflow-hidden">
          <div className="px-2.5 py-1.5 border-b border-[hsl(var(--danger)/.2)] flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-widest text-[hsl(var(--danger))]">
              ⚠ orphaned regions — VLM missed these bubbles
            </span>
            <span className="font-mono text-[10px] text-[hsl(var(--danger)/.7)]">
              {data.orphaned.length}
            </span>
          </div>
          <div className="divide-y divide-[hsl(var(--danger)/.15)]">
            {data.orphaned.map((r: OrphanedRegion) => (
              <div
                key={r.region_id}
                className="px-2.5 py-1.5 text-[10px] space-y-0.5"
              >
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[hsl(var(--danger))] shrink-0">
                    r{r.region_id}
                  </span>
                  <span className="text-[hsl(var(--text-muted))] shrink-0">
                    {r.label}
                  </span>
                  <span className="text-[hsl(var(--text-muted))]">
                    {r.size[0]}×{r.size[1]}px
                  </span>
                  <span className="ml-auto font-mono text-[hsl(var(--text-muted)/.6)]">
                    {(r.score * 100).toFixed(0)}%
                  </span>
                </div>
                {r.ocr_text ? (
                  <div className="font-mono text-[hsl(var(--danger)/.8)] pl-8">
                    ocr: "{r.ocr_text.slice(0, 60)}
                    {r.ocr_text.length > 60 ? "…" : ""}"
                  </div>
                ) : (
                  <div className="text-[hsl(var(--text-muted)/.5)] pl-8 italic">
                    no OCR text
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* matched dialogues */}
      {data.matches.length > 0 && (
        <div className="mt-1 rounded border border-[hsl(var(--border))] divide-y divide-[hsl(var(--border))] max-h-52 overflow-y-auto">
          {data.matches.map((m: MatchEvent) => (
            <div
              key={m.dialogue_index}
              className="px-2 py-1.5 text-[10px] space-y-0.5"
            >
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[hsl(var(--text-muted))] shrink-0">
                  dlg {m.dialogue_index}
                </span>
                <span className="font-mono text-[hsl(var(--accent2))] shrink-0">
                  → r{m.region_id ?? "?"}
                </span>
                <span
                  className={cn(
                    "text-[9px] px-1 rounded shrink-0",
                    m.match_type === "direct"
                      ? "bg-[hsl(var(--success)/.15)] text-[hsl(var(--success))]"
                      : "bg-[hsl(var(--accent2)/.1)] text-[hsl(var(--accent2))]",
                  )}
                >
                  {m.match_type}
                </span>
                <span
                  className="truncate text-[hsl(var(--text-muted))] flex-1"
                  title={m.dialogue_text}
                >
                  "{m.dialogue_text.slice(0, 30)}
                  {m.dialogue_text.length > 30 ? "…" : ""}"
                </span>
              </div>
              {m.match_type === "fallback" && (
                <div className="flex gap-3 pl-16">
                  {(["spatial", "text", "position", "total"] as const).map(
                    (k) => (
                      <div key={k} className="flex items-center gap-1">
                        <span className="text-[hsl(var(--text-muted)/.7)]">
                          {k[0]}
                        </span>
                        <ScoreBar value={m.scores[k]} />
                      </div>
                    ),
                  )}
                </div>
              )}
              {m.ocr_text && (
                <div className="pl-16 text-[hsl(var(--text-muted)/.7)] truncate">
                  ocr: "{m.ocr_text.slice(0, 40)}"
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* dialogues without region */}
      {data.unmatched.length > 0 && (
        <div className="mt-1">
          <p className="text-[9px] text-[hsl(var(--danger)/.7)] mb-1">
            dialogues without region ({data.unmatched.length})
          </p>
          {data.unmatched.map((u) => (
            <div
              key={u.dialogue_index}
              className="font-mono text-[10px] text-[hsl(var(--danger)/.7)]"
            >
              dlg {u.dialogue_index}: "{u.text.slice(0, 40)}"
            </div>
          ))}
        </div>
      )}
    </DataPanel>
  );
}

// ── S4 inpainting data ────────────────────────────────────────────────────────

function S4Data({ data }: { data: StageLog["s4_inpainting"] }) {
  return (
    <DataPanel title="inpainting data">
      <KV
        k="backend"
        v={data.skipped ? "skipped (no mask)" : (data.backend ?? "auto")}
        mono
      />
      {!data.skipped && (
        <>
          <KV k="pixels erased" v={data.mask_pixels.toLocaleString()} mono />
          <KV k="coverage" v={`${data.coverage_pct}%`} mono />
          <div className="h-1.5 w-full rounded-full bg-[hsl(var(--border))] overflow-hidden">
            <div
              className="h-full rounded-full bg-[hsl(var(--accent2))]"
              style={{ width: `${Math.min(100, data.coverage_pct * 10)}%` }}
            />
          </div>
        </>
      )}
    </DataPanel>
  );
}

// ── main component ────────────────────────────────────────────────────────────

const STAGE_KEYS = [
  "s2_detection",
  "s3_matching",
  "s4_inpainted",
  "s5_final",
] as const;
const STAGE_LABELS: Record<string, string> = {
  s2_detection: "S2 — detected",
  s3_matching: "S3 — matched",
  s4_inpainted: "S4 — inpainted",
  s5_final: "S5 — rendered",
};

interface PipelineDebugProps {
  runId: string;
  pageNum: number;
  filename?: string;
  stages: Record<string, string>;
  stageLog?: StageLog | null;
  originalW?: number;
  originalH?: number;
  onStageUpdated?: () => void;
}

export function PipelineDebug({
  runId,
  pageNum,
  filename,
  stages,
  stageLog,
  originalW = 0,
  originalH = 0,
  onStageUpdated,
}: PipelineDebugProps) {
  const [showMatchEditor, setShowMatchEditor] = useState(false);
  const [showMaskEditor, setShowMaskEditor] = useState(false);
  const hasImages = Object.keys(stages).length > 0;

  return (
    <div className="space-y-4">
      {/* stage images row */}
      {hasImages ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {STAGE_KEYS.map((key) => (
            <div key={key} className="space-y-1">
              <p className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                {STAGE_LABELS[key]}
              </p>
              {stages[key] ? (
                <ImageViewer
                  src={debugImageUrl(runId, stages[key])}
                  alt={STAGE_LABELS[key]}
                  label={`${STAGE_LABELS[key]} · p${pageNum}`}
                />
              ) : (
                <div className="flex h-28 items-center justify-center rounded border border-dashed border-[hsl(var(--border))] text-[10px] text-[hsl(var(--text-muted))]">
                  —
                </div>
              )}
              {key === "s3_matching" && stageLog && filename && (
                <button
                  onClick={() => {
                    setShowMatchEditor((v) => !v);
                    setShowMaskEditor(false);
                  }}
                  className="w-full mt-1 rounded border border-[hsl(var(--border))] py-0.5 text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] hover:border-[hsl(var(--accent2)/.3)] transition-colors"
                >
                  {showMatchEditor ? "close match editor" : "edit matches"}
                </button>
              )}
              {key === "s4_inpainted" && stageLog && filename && (
                <button
                  onClick={() => {
                    setShowMaskEditor((v) => !v);
                    setShowMatchEditor(false);
                  }}
                  className="w-full mt-1 rounded border border-[hsl(var(--border))] py-0.5 text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent2))] hover:border-[hsl(var(--accent2)/.3)] transition-colors"
                >
                  {showMaskEditor ? "close mask editor" : "edit mask"}
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded border border-dashed border-[hsl(var(--border))] px-4 py-6 text-center">
          <p className="text-xs text-[hsl(var(--text-muted))]">
            no debug images for p{pageNum}
          </p>
          <p className="mt-1 text-[10px] text-[hsl(var(--text-muted)/.6)]">
            enable save_debug in options and re-run
          </p>
        </div>
      )}

      {/* inline editors */}
      {showMatchEditor && stageLog && filename && (
        <div className="h-[480px]">
          <MatchingEditor
            runId={runId}
            pageNum={pageNum}
            filename={filename}
            stageLog={stageLog}
            originalW={originalW}
            originalH={originalH}
            onSaved={onStageUpdated}
          />
        </div>
      )}
      {showMaskEditor && stageLog && filename && (
        <div className="h-[480px]">
          <MaskEditor
            runId={runId}
            pageNum={pageNum}
            filename={filename}
            stageLog={stageLog}
            originalW={originalW}
            originalH={originalH}
            onSaved={onStageUpdated}
          />
        </div>
      )}

      {/* actual stage data */}
      {stageLog && (
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
            stage data · p{pageNum}
            <span className="ml-2 normal-case font-normal text-[hsl(var(--text-muted)/.6)]">
              {stageLog.image_size?.w ?? "?"}×{stageLog.image_size?.h ?? "?"}px
            </span>
          </p>

          {stageLog.s2_detection && <S2Data data={stageLog.s2_detection} />}
          {stageLog.s3_matching && <S3Data data={stageLog.s3_matching} />}
          {stageLog.s4_inpainting && <S4Data data={stageLog.s4_inpainting} />}

          {(stageLog.s5_rendering?.renders?.length ?? 0) > 0 && (
            <DataPanel
              title="rendering data"
              count={stageLog.s5_rendering?.ok}
              defaultOpen
            >
              <RenderLog
                renders={stageLog.s5_rendering!.renders}
                pageNum={pageNum}
                compact
              />
            </DataPanel>
          )}
        </div>
      )}
    </div>
  );
}
