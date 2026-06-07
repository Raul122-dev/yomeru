import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { getRun } from "../../lib/api";
import { STAGE_CONFIG, type TypesetStage } from "../../lib/typeset/stage";

interface UseStageRunnerOptions {
  runId: string;
  stage: TypesetStage;
  onDone?: (status: "done" | "failed") => void;
  onSettled?: () => void;
  body?: object;
}

async function pollStageStatus(
  runId: string,
  statusKey: string,
  timeoutMs = 120_000,
): Promise<"done" | "failed" | "timeout"> {
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    await new Promise((resolve) => setTimeout(resolve, 1000));

    try {
      const run = await getRun(runId);
      const status = (run as unknown as Record<string, unknown>)[statusKey];

      if (status === "done" || status === "failed") {
        return status;
      }
    } catch {
      // seguimos intentando
    }
  }

  return "timeout";
}

export function useStageRunner({
  runId,
  stage,
  onDone,
  onSettled,
  body,
}: UseStageRunnerOptions) {
  const qc = useQueryClient();
  const [isRunning, setIsRunning] = useState(false);

  const cfg = STAGE_CONFIG[stage];

  const mutation = useMutation({
    mutationFn: async () => {
      setIsRunning(true);
      await cfg.runFn(runId, body);
      return pollStageStatus(runId, cfg.statusKey);
    },
    onSuccess: async (result) => {
      let finalStatus: "done" | "failed";

      if (result === "failed" || result === "timeout") {
        finalStatus = "failed";
      } else {
        finalStatus = "done";
      }

      await Promise.all([
        qc.invalidateQueries({ queryKey: ["run", runId] }),
        qc.invalidateQueries({ queryKey: ["typeset-status", runId] }),
        qc.invalidateQueries({ queryKey: ["debug-images", runId] }),
      ]);

      onDone?.(finalStatus);
    },
    onError: () => {
      onDone?.("failed");
    },
    onSettled: () => {
      setIsRunning(false);
      onSettled?.();
    },
  });

  const runStage = useCallback(() => mutation.mutate(), [mutation]);

  return {
    isRunning,
    runStage,
    mutation,
    stageConfig: cfg,
  };
}
