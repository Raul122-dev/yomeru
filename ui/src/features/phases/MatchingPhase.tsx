import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { debugImageUrl, getDebugImages, pageImageUrl } from "../../lib/api";
import { getStageDebugImage, groupDebugImages } from "../../lib/debug";
import { usePhaseView } from "../../hooks/usePhaseView";
import { useTypesetReview } from "../../lib/review";
import { MatchingEditor } from "../editors/MatchingEditor";
import { ImageViewer } from "../../components/ui/ImageViewer";
import { EmptyState, Label, PageStrip, Panel, PhaseHeader } from "./PhaseShell";

interface MatchingPhaseProps {
  runId: string;
  pages: { page: number; filename: string }[];
}

export function MatchingPhase({ runId, pages }: MatchingPhaseProps) {
  const qc = useQueryClient();
  const v = usePhaseView(runId, "matching", pages, { withLogs: true, invalidate: ["debug-images"] });
  const review = useTypesetReview(runId, v.nonce);
  const { data: debugImages } = useQuery({
    queryKey: ["debug-images", runId],
    queryFn: () => getDebugImages(runId),
    enabled: v.hasOutput,
    staleTime: 0,
    retry: false,
  });
  const groups = useMemo(() => groupDebugImages(debugImages?.images ?? []), [debugImages?.images]);
  const sel = v.selectedLog;
  const debugImg = sel ? getStageDebugImage(groups, sel.page, "s3_matching") : null;

  return (
    <div className="flex flex-col gap-4">
      <PhaseHeader
        runId={runId}
        title="Matching"
        description="Pairs each translated line with the speech bubble it belongs to."
        status={v.status}
        canRun={v.canRun}
        blockedReason={v.blockedReason}
        onRun={() => void v.start()}
        processed={v.processed}
        total={v.total}
      />

      {!v.hasOutput ? (
        <EmptyState>Run matching once read & translate is done to review which line goes in which bubble.</EmptyState>
      ) : v.pageLogs.length === 0 ? (
        <EmptyState>No matching output yet.</EmptyState>
      ) : (
        <>
          <PageStrip
            items={v.pageLogs.map((e) => {
              const m = e.log?.s3_matching;
              const unmatched = m?.unmatched_dialogues ?? 0;
              return {
                page: e.page,
                filename: e.filename,
                src: pageImageUrl(runId, e.filename),
                meta: m ? `${m.matched}/${m.total_dialogues}` : "—",
                flag: unmatched > 0 || review[e.page] ? "warn" : undefined,
                review: review[e.page]?.length,
              };
            })}
            selected={v.selectedPage}
            onSelect={v.setSelectedPage}
          />

          {sel?.log && (
            <Panel
              title={<>Page {sel.page} <span className="font-mono text-xs font-normal text-[hsl(var(--text-muted))]">{sel.filename}</span></>}
              aside={sel.log.s3_matching
                ? `${sel.log.s3_matching.direct} direct · ${sel.log.s3_matching.fallback} fallback · ${sel.log.s3_matching.unmatched_dialogues} unmatched · ${sel.log.s3_matching.orphaned_regions} empty bubbles`
                : undefined}
            >
              <div className="grid gap-5 lg:grid-cols-2">
                <div>
                  <Label>Original</Label>
                  <ImageViewer src={`${pageImageUrl(runId, sel.filename)}?v=${v.nonce}`} alt={sel.filename} label={`original · p${sel.page}`} />
                </div>
                <div>
                  <Label>Assignments</Label>
                  {debugImg ? (
                    <ImageViewer src={`${debugImageUrl(runId, debugImg)}?v=${v.nonce}`} alt={`matching p${sel.page}`} label={`matching · p${sel.page}`} />
                  ) : (
                    <EmptyState>No matching preview for this page.</EmptyState>
                  )}
                </div>
              </div>
              <div className="mt-5">
                <MatchingEditor
                  key={sel.page}
                  runId={runId}
                  pageNum={sel.page}
                  filename={sel.filename}
                  stageLog={sel.log}
                  originalW={sel.log.image_size?.w ?? 0}
                  originalH={sel.log.image_size?.h ?? 0}
                  onSaved={() => {
                    qc.invalidateQueries({ queryKey: ["matching-logs", runId] });
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
