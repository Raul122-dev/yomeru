/**
 * useScopedPhaseRunner — hook for per-page phase reruns inside editors.
 *
 * Differences from usePhaseRunner:
 *   - Waits for WebSocket `open` before starting the phase (prevents race)
 *   - Always sends `page_scope` in the payload
 *   - Provides an `onComplete` callback for data refresh
 *   - Handles fast single-page runs gracefully (status text over progress bar)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { connectPhaseWs, startPhase } from "../lib/api";
import type { PhaseName, PhaseStartPayload } from "../lib/types";

export type ScopedStatus = "idle" | "running" | "done" | "failed";

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
  const completedRef = useRef(false);

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(
    async (pageScope: number[], extraOptions?: Record<string, unknown>) => {
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
          if (completedRef.current) return;
          completedRef.current = true;

          const failed = event.type === "phase_error" || event.status === "failed";
          setProgress({
            status: failed ? "failed" : "done",
            error: failed ? event.error : undefined,
          });

          cleanup();

          if (failed) {
            onError?.(event.error || "Phase failed");
          } else {
            onComplete?.();
          }
        }
      });

      wsRef.current = ws;

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
          reject(new Error("WebSocket connection failed"));
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
        await startPhase(runId, phase, payload);
      } catch (err) {
        cleanup();
        const msg = err instanceof Error ? err.message : String(err);
        setProgress({ status: "failed", error: msg });
        onError?.(msg);
      }
    },
    [runId, phase, cleanup, onComplete, onError],
  );

  const reset = useCallback(() => {
    cleanup();
    setProgress({ status: "idle" });
  }, [cleanup]);

  return { progress, start, reset };
}
