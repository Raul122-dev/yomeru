import { useQueryClient } from "@tanstack/react-query";
import { pageImageUrl } from "../../lib/api";
import { usePhaseView } from "../../hooks/usePhaseView";
import { RenderEditor } from "../editors/RenderEditor";
import { ImageViewer } from "../../components/ui/ImageViewer";
import { EmptyState, Label, PageStrip, Panel, PhaseHeader } from "./PhaseShell";

interface RenderingPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
}

export function RenderingPhase({ runId, pages }: RenderingPhaseProps) {
  const qc = useQueryClient();
  const v = usePhaseView(runId, "rendering", pages, { withLogs: true, invalidate: ["typeset-status"] });
  const sel = v.selectedLog;
  const prodUrl = (p: number) => `/api/phases/${runId}/rendering/scanline-production/${p}?v=${v.nonce}`;

  return (
    <div className="flex flex-col gap-4">
      <PhaseHeader
        runId={runId}
        title="Rendering"
        description="Typesets the translation inside each bubble, following its shape."
        status={v.status}
        canRun={v.canRun}
        blockedReason={v.blockedReason}
        onRun={() => void v.start()}
        processed={v.processed}
        total={v.total}
      />

      {!v.hasOutput ? (
        <EmptyState>Run rendering once inpainting is done to see the typeset pages here.</EmptyState>
      ) : v.pageLogs.length === 0 ? (
        <EmptyState>No rendering output yet.</EmptyState>
      ) : (
        <>
          <PageStrip
            items={v.pageLogs.map((e) => ({
              page: e.page,
              filename: e.filename,
              src: prodUrl(e.page),
              meta: e.log?.s5_rendering ? `${e.log.s5_rendering.ok} ok` : "—",
              flag: e.log?.s5_rendering?.skipped ? "warn" : undefined,
            }))}
            selected={v.selectedPage}
            onSelect={v.setSelectedPage}
          />

          {sel?.log && (
            <Panel
              title={<>Page {sel.page} <span className="font-mono text-xs font-normal text-[hsl(var(--text-muted))]">{sel.filename}</span></>}
              aside={`${sel.log.s5_rendering?.ok ?? 0} rendered · ${sel.log.s5_rendering?.skipped ?? 0} skipped`}
            >
              <div className="grid gap-5 lg:grid-cols-2">
                <div>
                  <Label>Original</Label>
                  <ImageViewer src={`${pageImageUrl(runId, sel.filename)}?v=${v.nonce}`} alt={sel.filename} label={`original · p${sel.page}`} />
                </div>
                <div>
                  <Label>Rendered</Label>
                  <ImageViewer key={`prod-${sel.page}`} src={`${prodUrl(sel.page)}&p=${sel.page}`} alt={`rendered p${sel.page}`} label={`rendered · p${sel.page}`} />
                </div>
              </div>
              <details className="mt-5 group">
                <summary className="eyebrow cursor-pointer select-none hover:text-[hsl(var(--text))]">Layout debug — bubble contours</summary>
                <div className="mt-3 max-w-xl">
                  <ImageViewer
                    key={`debug-${sel.page}`}
                    src={`/api/phases/${runId}/rendering/scanline-preview/${sel.page}?v=${v.nonce}&p=${sel.page}`}
                    alt={`debug p${sel.page}`}
                    label={`debug · p${sel.page}`}
                  />
                  <p className="mt-2 text-xs text-[hsl(var(--text-muted))]">Green outline = detected bubble contour used to fit the text.</p>
                </div>
              </details>
              <div className="mt-5">
                <RenderEditor
                  key={sel.page}
                  runId={runId}
                  pageNum={sel.page}
                  stageLog={sel.log}
                  onReRendered={() => {
                    qc.invalidateQueries({ queryKey: ["rendering-logs", runId] });
                    qc.invalidateQueries({ queryKey: ["typeset-status", runId] });
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
