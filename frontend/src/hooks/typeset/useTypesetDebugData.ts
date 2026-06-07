import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getDebugImages,
  getRenderLog,
  getTypesetCapabilities,
  type StageLog,
} from "../../lib/api";
import {
  getStageDebugImage,
  groupDebugImages,
  type DebugStageKey,
} from "../../lib/typeset/debug";

interface UseTypesetDebugDataOptions {
  runId: string;
  currentPageNum: number;
  enabled?: boolean;
  showDebug?: boolean;
  stageDebugKey?: DebugStageKey;
}

export function useTypesetDebugData({
  runId,
  currentPageNum,
  enabled = true,
  showDebug = true,
  stageDebugKey,
}: UseTypesetDebugDataOptions) {
  const capabilitiesQuery = useQuery({
    queryKey: ["typeset-capabilities"],
    queryFn: getTypesetCapabilities,
    staleTime: Infinity,
  });

  const debugImagesQuery = useQuery({
    queryKey: ["debug-images", runId],
    queryFn: () => getDebugImages(runId),
    enabled: enabled && showDebug,
    staleTime: 0,
    retry: false,
  });

  const stageLogQuery = useQuery<StageLog>({
    queryKey: ["stage-log", runId, currentPageNum],
    queryFn: () => getRenderLog(runId, currentPageNum),
    enabled: enabled && showDebug && currentPageNum > 0,
    staleTime: 0,
    retry: false,
  });

  const debugGroups = useMemo(
    () => groupDebugImages(debugImagesQuery.data?.images ?? []),
    [debugImagesQuery.data?.images],
  );

  const stageImage = stageDebugKey
    ? getStageDebugImage(debugGroups, currentPageNum, stageDebugKey)
    : null;

  return {
    capabilities: capabilitiesQuery.data,
    debugImages: debugImagesQuery.data,
    stageLog: stageLogQuery.data,
    debugGroups,
    stageImage,
    refetchDebugImages: debugImagesQuery.refetch,
    refetchStageLog: stageLogQuery.refetch,
  };
}
