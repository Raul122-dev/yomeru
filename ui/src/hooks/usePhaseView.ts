import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getRenderLog, getRun } from "../lib/api";
import { getRunPhaseStatus, isPhaseComplete } from "../lib/phase";
import type { PhaseName, Run, StageLog } from "../lib/types";
import { usePhaseRunner } from "./usePhaseRunner";

export interface PageStageLog {
  page: number;
  filename: string;
  log: StageLog | null;
}

const PREV: Record<PhaseName, PhaseName | null> = {
  detection: null, analysis: "detection", matching: "analysis", inpainting: "matching", rendering: "inpainting",
};

/** Everything a phase view needs: status, run/cancel, progress, page logs, selection. */
export function usePhaseView(
  runId: string,
  phase: PhaseName,
  pages: { page: number; filename: string }[],
  opts: { withLogs?: boolean; invalidate?: string[] } = {},
) {
  const qc = useQueryClient();
  const runner = usePhaseRunner(runId);
  const { progress, listen, effectiveStatus } = runner;
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [nonce, setNonce] = useState(() => Date.now());

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (q: { state: { data?: Run } }) =>
      q.state.data && Object.values(q.state.data.phase_status ?? {}).includes("running") ? 2000 : false,
  });

  const serverStatus = run ? getRunPhaseStatus(run, phase) : "pending";
  const status = effectiveStatus(phase, serverStatus);
  const isRunning = status === "running";
  const hasOutput = isPhaseComplete(serverStatus) || serverStatus === "stale" || serverStatus === "cancelled";
  const prev = PREV[phase];
  const canRun = !run ? false : prev === null ? true : isPhaseComplete(getRunPhaseStatus(run, prev));
  const blockedReason = prev ? `Finish ${prev} first.` : undefined;

  useEffect(() => {
    if (serverStatus === "running" && !progress) listen(phase);
  }, [serverStatus, progress, listen, phase]);

  const logsKey = [`${phase}-logs`, runId, pages.map((p) => p.page).join(",")];
  const { data: pageLogs = [] } = useQuery({
    queryKey: logsKey,
    enabled: !!opts.withLogs && hasOutput,
    staleTime: 0,
    queryFn: () =>
      Promise.all(
        pages.map(async (p): Promise<PageStageLog> => {
          try {
            return { ...p, log: await getRenderLog(runId, p.page) };
          } catch {
            return { ...p, log: null };
          }
        }),
      ),
  });

  // Phase finished (live) → refresh everything derived from it
  const done = progress?.phase === phase && progress.status !== "running" && progress.status !== "idle";
  useEffect(() => {
    if (!done) return;
    qc.invalidateQueries({ queryKey: ["run", runId] });
    qc.invalidateQueries({ queryKey: [`${phase}-logs`, runId] });
    for (const k of opts.invalidate ?? []) qc.invalidateQueries({ queryKey: [k, runId] });
    setNonce(Date.now());
  }, [done]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = opts.withLogs ? pageLogs : pages;
  useEffect(() => {
    if (selectedPage !== null && list.some((e) => e.page === selectedPage)) return;
    setSelectedPage(list[0]?.page ?? null);
  }, [list, selectedPage]);

  const run_ = async (payload?: Parameters<typeof runner.start>[1]) => {
    const { error } = await runner.start(phase, payload);
    if (error) toast.error(error);
    else qc.invalidateQueries({ queryKey: ["run", runId] });
  };

  const total = progress?.phase === phase && progress.total > 0 ? progress.total : pages.length;
  const processed = progress?.phase === phase ? progress.processed : 0;

  return {
    run, status, serverStatus, isRunning, hasOutput, canRun, blockedReason,
    start: run_, progress, total, processed,
    pageLogs, selectedPage, setSelectedPage,
    selectedLog: pageLogs.find((e) => e.page === selectedPage) ?? null,
    nonce, bump: () => setNonce(Date.now()),
  };
}
