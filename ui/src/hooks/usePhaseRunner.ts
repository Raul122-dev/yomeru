import { useCallback, useEffect, useRef, useState } from "react";
import { connectPhaseWs, startPhase } from "../lib/api";
import type { PhaseName, PhaseStartPayload } from "../lib/types";

export interface PhaseEvent {
  type?: string;
  phase?: PhaseName | string;
  total?: number;
  processed?: number;
  status?: string;
  page?: number;
  filename?: string;
  error?: string;
  failed?: number[];
  token?: string;
  [key: string]: unknown;
}

interface PhaseProgress {
  phase: PhaseName;
  status: "idle" | "running" | "done" | "failed";
  total: number;
  processed: number;
  events: PhaseEvent[];
}

export function usePhaseRunner(runId: string, autoListenPhase?: PhaseName) {
  const [progress, setProgress] = useState<PhaseProgress | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const listeningRef = useRef(false);

  const stop = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    listeningRef.current = false;
  }, []);

  useEffect(() => stop, [stop]);

  // Connect WS and listen for events on a specific phase
  const listen = useCallback(
    (phase: PhaseName) => {
      if (listeningRef.current && progress?.phase === phase) return;
      stop();
      listeningRef.current = true;
      // Always reset to running — if phase already completed, we're starting fresh
      setProgress((prev) =>
        prev?.phase === phase && prev.status === "running"
          ? prev
          : { phase, status: "running", total: 0, processed: 0, events: [] },
      );

      wsRef.current = connectPhaseWs(runId, (event: PhaseEvent) => {
        const isCurrentPhaseEvent =
          event.phase === phase ||
          event.type === "heartbeat" ||
          (phase === "analysis" && event.type === "token");

        if (!isCurrentPhaseEvent) return;

        setProgress((prev) => {
          if (!prev || prev.phase !== phase) return prev;
          const events = [...prev.events, event];

          if (event.type === "phase_progress") {
            return {
              ...prev,
              total: event.total ?? prev.total,
              processed: event.processed ?? prev.processed,
              events,
            };
          }
          if (event.type === "page_done") {
            return {
              ...prev,
              processed: Math.max(prev.processed + 1, event.processed ?? 0),
              events,
            };
          }
          if (event.type === "phase_done") {
            return {
              ...prev,
              status: event.status === "done" ? "done" : "failed",
              total: event.total ?? prev.total,
              processed: event.processed ?? prev.processed,
              events,
            };
          }
          if (event.type === "phase_error") {
            return { ...prev, status: "failed", events };
          }
          return { ...prev, events };
        });

        if (event.type === "phase_done" || event.type === "phase_error") {
          listeningRef.current = false;
        }
      });
    },
    [runId, stop, progress?.phase],
  );

  // Auto-listen when phase is already running server-side
  useEffect(() => {
    if (autoListenPhase && !listeningRef.current && !progress) {
      listen(autoListenPhase);
    }
  }, [autoListenPhase, listen, progress]);

  const start = useCallback(
    async (phase: PhaseName, payload?: PhaseStartPayload) => {
      stop();
      setProgress({
        phase,
        status: "running",
        total: 0,
        processed: 0,
        events: [],
      });
      listeningRef.current = true;

      wsRef.current = connectPhaseWs(runId, (event: PhaseEvent) => {
        const isCurrentPhaseEvent =
          event.phase === phase ||
          event.type === "heartbeat" ||
          (phase === "analysis" && event.type === "token");

        if (!isCurrentPhaseEvent) return;

        setProgress((prev) => {
          if (!prev || prev.phase !== phase) return prev;

          const events = [...prev.events, event];

          if (event.type === "phase_progress") {
            return {
              ...prev,
              total: event.total ?? prev.total,
              processed: event.processed ?? prev.processed,
              events,
            };
          }

          if (event.type === "page_done") {
            return {
              ...prev,
              processed: Math.max(prev.processed + 1, event.processed ?? 0),
              events,
            };
          }

          if (event.type === "phase_done") {
            return {
              ...prev,
              status: event.status === "done" ? "done" : "failed",
              total: event.total ?? prev.total,
              processed: event.processed ?? prev.processed,
              events,
            };
          }

          if (event.type === "phase_error") {
            return { ...prev, status: "failed", events };
          }

          return { ...prev, events };
        });

        if (event.type === "phase_done" || event.type === "phase_error") {
          stop();
        }
      });

      try {
        await startPhase(runId, phase, payload);
      } catch (error) {
        stop();
        const message = error instanceof Error ? error.message : String(error);
        setProgress((prev) => {
          if (!prev || prev.phase !== phase) return prev;
          return {
            ...prev,
            status: "failed",
            events: [
              ...prev.events,
              { type: "phase_error", phase, error: message },
            ],
          };
        });
        throw error;
      }
    },
    [runId, stop],
  );

  return { progress, start, stop, listen };
}
