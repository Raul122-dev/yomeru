import { useCallback, useEffect, useRef, useState } from "react";
import { connectPhaseWs, startPhase } from "../lib/api";
import type { PhaseName, PhaseStartPayload, PhaseStatus } from "../lib/types";

interface PhaseEvent {
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
  /** Non-token events only (bounded); tokens go to `tokens` per page. */
  events: PhaseEvent[];
  /** Streamed model text per page (analysis). */
  tokens: Record<number, string>;
}

const MAX_EVENTS = 500;
const TERMINAL = new Set(["phase_done", "phase_error", "phase_cancelled"]);

/**
 * Live progress of one phase over the run's WebSocket.
 *
 * The server's phase_status is the source of truth: `effectiveStatus()` only
 * lets the live status win while it says "running" — once a phase ends, the
 * polled server status (done / partial / stale / cancelled…) is shown.
 * The socket reconnects with backoff if it drops mid-phase.
 */
export function usePhaseRunner(runId: string, autoListenPhase?: PhaseName) {
  const [progress, setProgress] = useState<PhaseProgress | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const phaseRef = useRef<PhaseName | null>(null);
  const retryRef = useRef<{ timer?: number; attempts: number }>({ attempts: 0 });

  const stop = useCallback(() => {
    phaseRef.current = null;
    window.clearTimeout(retryRef.current.timer);
    retryRef.current.attempts = 0;
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
  }, []);

  useEffect(() => stop, [stop]);

  const onEvent = useCallback((phase: PhaseName, event: PhaseEvent) => {
    const mine =
      event.phase === phase || (phase === "analysis" && event.type === "token");
    if (!mine) return;
    setProgress((prev) => {
      if (!prev || prev.phase !== phase) return prev;
      if (event.type === "token") {
        const p = Number(event.page);
        return { ...prev, tokens: { ...prev.tokens, [p]: (prev.tokens[p] ?? "") + (event.token ?? "") } };
      }
      const events = [...prev.events, event].slice(-MAX_EVENTS);
      switch (event.type) {
        case "phase_start":
          return event.replay ? { ...prev, events } : { ...prev, status: "running", events, tokens: {} };
        case "phase_progress":
          return { ...prev, total: event.total ?? prev.total, processed: event.processed ?? prev.processed, events };
        case "page_done":
          return { ...prev, processed: prev.processed + 1, events };
        case "phase_done":
          return { ...prev, status: event.status === "failed" ? "failed" : "done", events };
        case "phase_error":
          return { ...prev, status: "failed", events };
        case "phase_cancelled":
          return { ...prev, status: "idle", events };
        default:
          return { ...prev, events };
      }
    });
    if (TERMINAL.has(event.type ?? "") && !event.replay) stop();
  }, [stop]);

  const connect = useCallback((phase: PhaseName) => {
    const ws = connectPhaseWs(runId, (ev) => onEvent(phase, ev));
    wsRef.current = ws;
    ws.onopen = () => { retryRef.current.attempts = 0; };
    ws.onclose = () => {
      if (wsRef.current !== ws || phaseRef.current !== phase) return; // closed on purpose
      const attempts = ++retryRef.current.attempts;
      if (attempts > 8) return;
      retryRef.current.timer = window.setTimeout(() => {
        if (phaseRef.current === phase) connect(phase);
      }, Math.min(500 * 2 ** attempts, 8000));
    };
  }, [runId, onEvent]);

  const listen = useCallback((phase: PhaseName) => {
    if (phaseRef.current === phase && wsRef.current) return;
    stop();
    phaseRef.current = phase;
    setProgress((prev) =>
      prev?.phase === phase && prev.status === "running"
        ? prev
        : { phase, status: "running", total: 0, processed: 0, events: [], tokens: {} },
    );
    connect(phase);
  }, [stop, connect]);

  useEffect(() => {
    if (autoListenPhase && !phaseRef.current && !progress) listen(autoListenPhase);
  }, [autoListenPhase, listen, progress]);

  const start = useCallback(async (phase: PhaseName, payload?: PhaseStartPayload) => {
    listen(phase);
    setProgress({ phase, status: "running", total: 0, processed: 0, events: [], tokens: {} });
    try {
      await startPhase(runId, phase, payload);
    } catch (error) {
      stop();
      const message = error instanceof Error ? error.message : String(error);
      setProgress((prev) => (prev && prev.phase === phase ? { ...prev, status: "idle" } : prev));
      // Callers show it as a toast; rethrowing would be an unhandled rejection
      return { error: message };
    }
    return { error: null };
  }, [runId, listen, stop]);

  /** Server status unless the live stream says this phase is running. */
  const effectiveStatus = useCallback(
    (phase: PhaseName, serverStatus: PhaseStatus): PhaseStatus =>
      progress?.phase === phase && progress.status === "running" ? "running" : serverStatus,
    [progress],
  );

  return { progress, start, stop, listen, effectiveStatus };
}
