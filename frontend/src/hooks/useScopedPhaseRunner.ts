/**
 * useScopedPhaseRunner — hook for per-page phase reruns inside editors.
 *
 * Differences from usePhaseRunner:
 *   - Waits for WebSocket `open` before starting the phase (prevents race)
 *   - Always sends `page_scope` in the payload
 *   - Provides an `onComplete` callback for data refresh
 *   - Handles fast single-page runs gracefully (status text over progress bar)
 *   - `launch` replaces the plain phase start (e.g. an endpoint that edits inputs first)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { connectPhaseWs, getRun, startPhase } from "../lib/api";
import type { PhaseName, PhaseStartPayload } from "../lib/types";

type ScopedStatus = "idle" | "running" | "done" | "failed";

interface ScopedProgress {
  status: ScopedStatus;
  error?: string;
}

interface UseScopedPhaseRunnerOptions {
  runId: string;
  phase: PhaseName;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

export function useScopedPhaseRunner({
  runId,
  phase,
  onComplete,
  onError,
}: UseScopedPhaseRunnerOptions) {
  const [progress, setProgress] = useState<ScopedProgress>({ status: "idle" });
  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<number | null>(null);
  const completedRef = useRef(false);

  const cleanup = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null;
      ws.close();
    }
  }, []);

  // If the socket drops mid-run, the editor would spin forever: fall back to
  // polling the run's phase status until the job ends.
  const finish = useCallback((failed: boolean, error?: string) => {
    if (completedRef.current) return;
    completedRef.current = true;
    setProgress({ status: failed ? "failed" : "done", error: failed ? error : undefined });
    cleanup();
    if (failed) onError?.(error || "This step failed");
    else onComplete?.();
  }, [cleanup, onComplete, onError]);

  const pollUntilDone = useCallback(() => {
    if (pollRef.current !== null) return;
    pollRef.current = window.setInterval(async () => {
      try {
        const run = await getRun(runId);
        const st = run.phase_status?.[phase];
        if (st && st !== "running") finish(st === "failed", run.error ?? undefined);
      } catch { /* keep polling */ }
    }, 3000);
  }, [runId, phase, finish]);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(
    async (pageScope: number[], extraOptions?: Record<string, unknown>, launch?: () => Promise<unknown>) => {
      cleanup();
      completedRef.current = false;
      setProgress({ status: "running" });

      // Build payload
      const payload: PhaseStartPayload = {
        page_scope: pageScope,
        ...(extraOptions ? { options: extraOptions } : {}),
      };

      // Create WS and wait for it to open before starting the phase
      const ws = connectPhaseWs(runId, (event) => {
        // Only listen to events for our phase
        if (event.phase && event.phase !== phase) return;

        if (event.type === "phase_done" || event.type === "phase_error") {
          finish(event.type === "phase_error" || event.status === "failed", event.error);
        }
      });

      wsRef.current = ws;
      ws.addEventListener("close", () => {
        if (wsRef.current === ws && !completedRef.current) pollUntilDone();
      });

      // Wait for WS to be open before starting
      await new Promise<void>((resolve, reject) => {
        const onOpen = () => {
          ws.removeEventListener("open", onOpen);
          ws.removeEventListener("error", onErr);
          resolve();
        };
        const onErr = () => {
          ws.removeEventListener("open", onOpen);
          ws.removeEventListener("error", onErr);
          reject(new Error("Lost the connection to the server"));
        };

        if (ws.readyState === WebSocket.OPEN) {
          resolve();
        } else {
          ws.addEventListener("open", onOpen);
          ws.addEventListener("error", onErr);
        }
      });

      // Now start the phase
      try {
        await (launch ? launch() : startPhase(runId, phase, payload));
      } catch (err) {
        cleanup();
        const msg = err instanceof Error ? err.message : String(err);
        setProgress({ status: "failed", error: msg });
        onError?.(msg);
      }
    },
    [runId, phase, cleanup, onError, finish, pollUntilDone],
  );

  const reset = useCallback(() => {
    cleanup();
    setProgress({ status: "idle" });
  }, [cleanup]);

  return { progress, start, reset };
}
