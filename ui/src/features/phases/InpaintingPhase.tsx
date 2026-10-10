import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { debugImageUrl, getDebugImages, maskDebugUrl, pageImageUrl } from "../../lib/api";
import { getStageDebugImage, groupDebugImages } from "../../lib/debug";
import { usePhaseView } from "../../hooks/usePhaseView";
import { MaskEditor } from "../editors/MaskEditor";
import { ImageViewer } from "../../components/ui/ImageViewer";
import { EmptyState, Label, PageStrip, Panel, PhaseHeader } from "./PhaseShell";

interface InpaintingPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
}

const MASK_LEGEND = [
  { color: "#ff00ff", label: "text in bubble" },
  { color: "#00c8ff", label: "free text" },
  { color: "#ffa500", label: "sound effect" },
];

export function InpaintingPhase({ runId, pages }: InpaintingPhaseProps) {
  const qc = useQueryClient();
  const v = usePhaseView(runId, "inpainting", pages, { withLogs: true, invalidate: ["debug-images"] });
  const { data: debugImages } = useQuery({
    queryKey: ["debug-images", runId],
    queryFn: () => getDebugImages(runId),
    enabled: v.hasOutput,
    staleTime: 0,
    retry: false,
  });
  const groups = useMemo(() => groupDebugImages(debugImages?.images ?? []), [debugImages?.images]);
  const sel = v.selectedLog;
  const after = sel ? getStageDebugImage(groups, sel.page, "s4_inpainted") : null;
  const s4 = sel?.log?.s4_inpainting;

  return (
    <div className="flex flex-col gap-4">
      <PhaseHeader
        runId={runId}
        title="Inpainting"
        description="Erases the original text so the translation can be drawn on a clean page."
        status={v.status}
        canRun={v.canRun}
        blockedReason={v.blockedReason}
        onRun={() => void v.start()}
        processed={v.processed}
        total={v.total}
      />

      {!v.hasOutput ? (
        <EmptyState>Run inpainting once matching is done to review the cleaned pages and fix masks.</EmptyState>
      ) : v.pageLogs.length === 0 ? (
        <EmptyState>No inpainting output yet.</EmptyState>
      ) : (
        <>
          <PageStrip
            items={v.pageLogs.map((e) => {
              const img = getStageDebugImage(groups, e.page, "s4_inpainted");
              return {
                page: e.page,
                filename: e.filename,
                src: img ? `${debugImageUrl(runId, img)}?v=${v.nonce}` : `${pageImageUrl(runId, e.filename)}?v=${v.nonce}`,
                meta: e.log?.s4_inpainting ? `${e.log.s4_inpainting.coverage_pct}%` : "—",
                flag: img ? undefined : "error",
              };
            })}
            selected={v.selectedPage}
            onSelect={v.setSelectedPage}
          />

          {sel?.log && (
            <Panel
              title={<>Page {sel.page} <span className="font-mono text-xs font-normal text-[hsl(var(--text-muted))]">{sel.filename}</span></>}
              aside={s4 ? `${s4.backend} · ${((s4.mask_pixels ?? 0) / 1000).toFixed(1)}k px masked · ${s4.coverage_pct}% of page` : undefined}
            >
              <div className="grid gap-5 lg:grid-cols-2">
                <div>
                  <Label>Before</Label>
                  <ImageViewer src={`${pageImageUrl(runId, sel.filename)}?v=${v.nonce}`} alt={sel.filename} label={`before · p${sel.page}`} />
                </div>
                <div>
                  <Label>After</Label>
                  {after ? (
                    <ImageViewer src={`${debugImageUrl(runId, after)}?v=${v.nonce}`} alt={`inpainted p${sel.page}`} label={`after · p${sel.page}`} />
                  ) : (
                    <EmptyState>No cleaned image for this page.</EmptyState>
                  )}
                </div>
              </div>

              <details className="mt-5">
                <summary className="eyebrow cursor-pointer select-none hover:text-[hsl(var(--text))]">Generated masks per region</summary>
                <div className="mt-3 max-w-xl">
                  <ImageViewer src={`${maskDebugUrl(runId, sel.page)}?v=${v.nonce}`} alt={`mask debug p${sel.page}`} label={`masks · p${sel.page}`} />
                  <div className="mt-2 flex flex-wrap gap-4 text-xs text-[hsl(var(--text-muted))]">
                    {MASK_LEGEND.map((l) => (
                      <span key={l.label} className="flex items-center gap-1.5">
                        <span className="size-2.5 rounded-sm" style={{ background: l.color }} />
                        {l.label}
                      </span>
                    ))}
                  </div>
                </div>
              </details>

              <div className="mt-5">
                <MaskEditor
                  key={sel.page}
                  runId={runId}
                  pageNum={sel.page}
                  filename={sel.filename}
                  stageLog={sel.log}
                  originalW={sel.log.image_size?.w ?? 0}
                  originalH={sel.log.image_size?.h ?? 0}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ["inpainting-logs", runId] });
                    qc.invalidateQueries({ queryKey: ["debug-images", runId] });
                    v.bump();
                  }}
                />
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
