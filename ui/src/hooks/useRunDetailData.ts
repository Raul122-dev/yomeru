import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getRun, getTypesetStatus } from "../lib/api";
import type { Run } from "../lib/types";
import {
  getDerivedRunPhaseState,
  type DerivedRunPhaseState,
} from "../lib/phase";

export interface RunPage {
  page: number;
  filename: string;
}

async function getPages(runId: string): Promise<RunPage[]> {
  const res = await fetch(`/api/runs/${runId}/pages`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function getRunRefetchInterval(run?: Run) {
  if (!run) return 2000;

  const unifiedStatuses = Object.values(run.phase_status ?? {});
  const active =
    run.status === "running" ||
    unifiedStatuses.some((status) => status === "running") ||
    run.detection_status === "running" ||
    run.analysis_status === "running" ||
    run.typeset_matching_status === "running" ||
    run.typeset_inpainting_status === "running" ||
    run.typeset_rendering_status === "running";

  return active ? 2000 : false;
}

export function useRunDetailData(runId: string) {
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (q: { state: { data?: Run } }) =>
      getRunRefetchInterval(q.state.data),
  });

  const typesetStatusQuery = useQuery({
    queryKey: ["typeset-status", runId],
    queryFn: () => getTypesetStatus(runId),
    refetchInterval: 5000,
    retry: false,
    enabled: !!runId,
  });

  const pagesQuery = useQuery({
    queryKey: ["pages", runId],
    queryFn: () => getPages(runId),
    enabled: !!runQuery.data,
  });

  const derived = useMemo<DerivedRunPhaseState | null>(() => {
    if (!runQuery.data) return null;
    return getDerivedRunPhaseState(runQuery.data, typesetStatusQuery.data);
  }, [runQuery.data, typesetStatusQuery.data]);

  return {
    run: runQuery.data,
    pages: pagesQuery.data ?? [],
    typesetStatus: typesetStatusQuery.data,
    derived,

    isLoading: runQuery.isLoading,
    isError: runQuery.isError,
    error: runQuery.error,

    refetchRun: runQuery.refetch,
    refetchPages: pagesQuery.refetch,
    refetchTypesetStatus: typesetStatusQuery.refetch,
  };
}
