import type {
  AllPhasesStatus,
  AppConfig,
  CreateRunOpts,
  DetectionRegion,
  FontInfo,
  MatchEvent,
  ModelInfo,
  OrphanedRegion,
  PhaseName,
  PhaseStartPayload,
  PhaseStatus,
  PhaseStatusResponse,
  ProviderInfo,
  RenderEvent,
  Run,
  StageLog,
  TypesetCapabilities,
  TypesetStatus,
} from "./types";

export type {
  AllPhasesStatus,
  AppConfig,
  CreateRunOpts,
  DetectionRegion,
  FontInfo,
  MatchEvent,
  ModelInfo,
  OrphanedRegion,
  PhaseName,
  PhaseStartPayload,
  PhaseStatus,
  PhaseStatusResponse,
  ProviderInfo,
  RenderEvent,
  Run,
  StageLog,
  TypesetCapabilities,
  TypesetStatus,
} from "./types";

const B = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(B + path, init);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ── runs ──────────────────────────────────────────────────────────────────────

export const listRuns = () => req<Run[]>("/runs");
export const getRun = (id: str) => req<Run>(`/runs/${id}`);

// ── phases (new unified API) ──────────────────────────────────────────────────
export const startPhase = (
  runId: string,
  phase: PhaseName,
  payload?: PhaseStartPayload,
) =>
  req<{ status: string }>(`/phases/${runId}/${phase}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });

export const retryPhase = (
  runId: string,
  phase: PhaseName,
  pageScope?: number[],
) =>
  req<{ status: string }>(`/phases/${runId}/${phase}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page_scope: pageScope }),
  });

export const getPhaseStatus = (runId: string, phase: PhaseName) =>
  req<PhaseStatusResponse>(`/phases/${runId}/${phase}/status`);

export const getAllPhasesStatus = (runId: string) =>
  req<AllPhasesStatus>(`/phases/${runId}/status`);

export const startAllPhases = (runId: string, options?: object) =>
  req<{ status: string }>(`/phases/${runId}/start-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ options: options || {} }),
  });

export const reanalyzeWithCorrections = (
  runId: string,
  pageNumber: number,
  corrections: Record<string, string>,
) =>
  req<{ status: string }>(`/phases/${runId}/analysis/reanalyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page_number: pageNumber, corrections }),
  });

export function connectPhaseWs(
  runId: string,
  onEvent: (ev: any) => void,
): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/phases/${runId}/ws`);
  ws.onmessage = (e) => onEvent(JSON.parse(e.data));
  return ws;
}

// detections
export const getDetections = (id: str) => req<any[]>(`/runs/${id}/detections`);
export const getPageDetections = (id: str, page: number) =>
  req<any>(`/runs/${id}/detections/${page}`);
export const savePageDetections = (id: str, page: number, body: object) =>
  req<{ ok: boolean; regions: number }>(`/runs/${id}/detections/${page}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const revertPageDetections = (id: str, page: number) =>
  fetch(`/api/runs/${id}/detections/${page}/refined`, { method: "DELETE" });
export const deleteRun = (id: str) =>
  fetch(B + `/runs/${id}`, { method: "DELETE" });
export const getContext = (id: str) =>
  req<Record<string, unknown>>(`/runs/${id}/context`);

export const createRun = (form: FormData, opts: CreateRunOpts = {}) => {
  if (opts.detector_backend)
    form.append("detector_backend", opts.detector_backend);
  if (opts.detector_threshold != null)
    form.append("detector_threshold", String(opts.detector_threshold));
  if (opts.auto_start !== undefined)
    form.append("auto_start", String(opts.auto_start));
  if (opts.auto_start === false) form.append("auto_start", "false");
  return fetch(B + "/runs", { method: "POST", body: form }).then((r) => {
    if (!r.ok)
      return r.text().then((t) => {
        throw new Error(t);
      });
    return r.json() as Promise<Run>;
  });
};

// ── config ────────────────────────────────────────────────────────────────────
export const getConfig = () => req<AppConfig>("/config");
export const getFormats = () =>
  req<{ key: string; name: string; reading_order: string; origin: string }[]>(
    "/config/formats",
  );
export const getLocalModels = () =>
  req<ModelInfo[]>("/config/models/local");

export const testConnection = () =>
  req<{ ok: boolean; error?: string; endpoint?: string }>("/config/models/test-connection");

export const updateProvider = (
  provider: string,
  body: { api_key?: string; base_url?: string },
) =>
  req(`/config/providers/${provider}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateDefaults = (body: {
  model?: string;
  format?: string;
  source_language?: string;
  target_language?: string;
  provider?: string;
}) =>
  req("/config/defaults", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateTranslation = (body: {
  enabled?: boolean;
  model?: string;
  provider?: string;
  base_url?: string;
  api_key?: string;
}) =>
  req("/config/translation", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updatePhases = (body: {
  detection?: Record<string, unknown>;
  matching?: Record<string, unknown>;
  inpainting?: Record<string, unknown>;
  rendering?: Record<string, unknown>;
}) =>
  req("/config/phases", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// ── helpers ───────────────────────────────────────────────────────────────────
type str = string;

export const getProviders = () => req<ProviderInfo[]>("/config/providers");

export const getAnalyses = (id: str) => req<unknown[]>(`/runs/${id}/analyses`);
export const pageImageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/pages/${filename}`;

// ── annotations ───────────────────────────────────────────────────────────────
export const getAnnotations = (id: str) =>
  req<{ annotations: Record<string, unknown[]>; summary: unknown }>(
    `/runs/${id}/annotations`,
  );
export const addAnnotation = (id: str, page: number, body: object) =>
  req(`/runs/${id}/annotations/${page}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const deleteAnnotation = (id: str, page: number, annId: str) =>
  fetch(`/api/runs/${id}/annotations/${page}/${annId}`, { method: "DELETE" });

// ── edits ─────────────────────────────────────────────────────────────────────
export const getEdits = (id: str) =>
  req<Record<string, unknown>>(`/runs/${id}/edits`);
export const saveEdit = (id: str, page: number, body: object) =>
  req(`/runs/${id}/edits/${page}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const revertEdit = (id: str, page: number) =>
  fetch(`/api/runs/${id}/edits/${page}`, { method: "DELETE" });

// ── editing (artifact CRUD) ───────────────────────────────────────────────────
export const savePageMatches = (id: str, page: number, body: object) =>
  req<{ ok: boolean }>(`/runs/${id}/typeset/matches/${page}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const revertPageMatches = (id: str, page: number) =>
  fetch(`/api/runs/${id}/typeset/matches/${page}/refined`, {
    method: "DELETE",
  });

// ── algorithm-only matching comparison ────────────────────────────────────────
export interface AlgorithmMatchResult {
  page: number;
  matches: {
    dialogue_index: number;
    dialogue_text: string;
    speaker: string;
    region_id: number | null;
    region_label: string | null;
    region_bbox: [number, number, number, number];
    scores: { spatial: number; text: number; position: number; total: number };
    ocr_text: string | null;
    vlm_region_id: number | null;
    agrees_with_vlm: boolean;
  }[];
  unmatched: { dialogue_index: number; dialogue_text: string; speaker: string }[];
  regions_used: number;
  dialogues_total: number;
  agreement_rate: number;
  debug_image: string;
}
export const runAlgorithmOnlyMatching = (id: string, pageNum: number) =>
  req<AlgorithmMatchResult>(`/phases/${id}/matching/algorithm-only/${pageNum}`, { method: "POST" });

export const saveMask = (id: str, page: number, maskDataUrl: str) =>
  fetch(`/api/runs/${id}/typeset/masks/${page}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mask_data_url: maskDataUrl }),
  });

// ── outputs (read-only file access) ──────────────────────────────────────────
export const getTypesetCapabilities = () =>
  req<TypesetCapabilities>("/config/capabilities");
export const getTypesetStatus = (id: str) =>
  req<TypesetStatus>(`/runs/${id}/typeset/status`);
export const typesetPageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/typeset/pages/${filename}`;
export const getDebugImages = (id: str) =>
  req<{ images: string[] }>(`/runs/${id}/typeset/debug`);
export const debugImageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/typeset/debug/${filename}`;
export const getRenderLog = (id: string, pageNum: number) =>
  req<StageLog>(`/runs/${id}/typeset/render-log/${pageNum}`);
export const maskDebugUrl = (id: string, pageNum: number) =>
  `/api/phases/${id}/inpainting/mask-debug/${pageNum}`;

// ── fonts ─────────────────────────────────────────────────────────────────────
export const listFonts = () =>
  req<{ fonts: FontInfo[] }>("/fonts");
export const deleteFont = (name: string) =>
  fetch(B + `/fonts/${encodeURIComponent(name)}`, {
    method: "DELETE",
  }).then((r) => r.json());
export const uploadFont = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(B + "/fonts/upload", {
    method: "POST",
    body: fd,
  }).then((r) => {
    if (!r.ok)
      return r.json().then((e) => {
        throw new Error(e.detail ?? "upload failed");
      });
    return r.json() as Promise<FontInfo>;
  });
};
