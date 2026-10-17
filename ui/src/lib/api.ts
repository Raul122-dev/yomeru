import type {
  AllPhasesStatus,
  AppConfig,
  CreateRunOpts,
  DetectionRegion,
  FontInfo,
  MatchEvent,
  Connection,
  ModelInfo,
  OrphanedRegion,
  PipelineSettings,
  Preset,
  Protocol,
  DeepPartial,
  PhaseName,
  PhaseStartPayload,
  PhaseStatus,
  PhaseStatusResponse,
  RenderEvent,
  Run,
  StageLog,
  BackendInfo,
  LocalModelsInfo,
  TypesetStatus,
} from "./types";

export type {
  AllPhasesStatus,
  AppConfig,
  CreateRunOpts,
  DetectionRegion,
  FontInfo,
  MatchEvent,
  Connection,
  ModelInfo,
  OrphanedRegion,
  PipelineSettings,
  Preset,
  Protocol,
  DeepPartial,
  PhaseName,
  PhaseStartPayload,
  PhaseStatus,
  PhaseStatusResponse,
  RenderEvent,
  Run,
  StageLog,
  BackendInfo,
  TypesetStatus,
} from "./types";

const B = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(B + path, init);
  if (!r.ok) {
    const text = await r.text();
    let msg = text;
    try {
      const d = JSON.parse(text).detail;
      msg = typeof d === "string" ? d : JSON.stringify(d);
    } catch { /* plain text */ }
    throw new Error(msg || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

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

/** Image-edit rendering: ask the model again (new seed) for some dialogues
 * of a page, or for every one it drew or tried (`dialogues` null). */
export const rerenderWithModel = (runId: string, page: number, dialogues: number[] | null) =>
  req<{ status: string; dialogues: number[] }>(`/phases/${runId}/rendering/rerender/${page}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dialogues }),
  });

export const getPhaseStatus = (runId: string, phase: PhaseName) =>
  req<PhaseStatusResponse>(`/phases/${runId}/${phase}/status`);

export const getAllPhasesStatus = (runId: string) =>
  req<AllPhasesStatus>(`/phases/${runId}/status`);

export const startAllPhases = (runId: string, options?: object, startFrom?: PhaseName) =>
  req<{ status: string }>(`/phases/${runId}/start-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ options: options || {}, ...(startFrom ? { start_from: startFrom } : {}) }),
  });

export const cancelRun = (runId: string) =>
  req<{ status: string }>(`/phases/${runId}/cancel`, { method: "POST" });

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
  if (opts.auto_start !== undefined) form.append("auto_start", String(opts.auto_start));
  if (opts.preset_id) form.append("preset_id", opts.preset_id);
  if (opts.settings) form.append("settings", JSON.stringify(opts.settings));
  return req<Run>("/runs", { method: "POST", body: form });
};

// ── config ────────────────────────────────────────────────────────────────────
export const getConfig = () => req<AppConfig>("/config");
export const getFormats = () =>
  req<{ key: string; name: string; reading_order: string; origin: string }[]>(
    "/config/formats",
  );

export interface ConnectionInput {
  name: string;
  protocol: Protocol;
  base_url: string;
  /** Omit or send the masked value to keep the stored key */
  api_key?: string;
}
export const createConnection = (c: ConnectionInput) =>
  req<AppConfig>("/config/connections", json("POST", c));
export const updateConnection = (id: string, c: ConnectionInput) =>
  req<AppConfig>(`/config/connections/${id}`, json("PUT", c));
export const deleteConnection = (id: string) =>
  req<AppConfig>(`/config/connections/${id}`, { method: "DELETE" });
export const getConnectionModels = (id: string) =>
  req<ModelInfo[]>(`/config/connections/${id}/models`);
export const testConnection = (id: string) =>
  req<{ ok: boolean; models?: number; error?: string }>(`/config/connections/${id}/test`, { method: "POST" });
export const testConnectionDraft = (c: ConnectionInput) =>
  req<{ ok: boolean; models?: number; error?: string }>("/config/connections/test", json("POST", c));

export const updateSettings = (patch: DeepPartial<PipelineSettings>) =>
  req<AppConfig>("/config/settings", json("PATCH", patch));

export const createPreset = (name: string, settings?: PipelineSettings) =>
  req<AppConfig>("/config/presets", json("POST", { name, settings }));
export const updatePreset = (p: Preset) =>
  req<AppConfig>(`/config/presets/${p.id}`, json("PUT", { name: p.name, settings: p.settings }));
export const deletePreset = (id: string) =>
  req<AppConfig>(`/config/presets/${id}`, { method: "DELETE" });

// ── helpers ───────────────────────────────────────────────────────────────────
type str = string;


export const getAnalyses = (id: str) => req<unknown[]>(`/runs/${id}/analyses`);
export const pageImageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/pages/${filename}`;
/**
 * Background for canvas editors: big enough for a full-width editor on a
 * 2× screen, never the multi-MB source. Masks (PNG) are NOT routed here —
 * they are edited pixel-exact.
 */
export const editorImageUrl = (url: string, w = 1600) =>
  `${url}${url.includes("?") ? "&" : "?"}w=${w}`;

/** Resized WebP of a source page for strips/grids (server snaps w, see core/images.py). */
export const pageThumbUrl = (id: str, filename: str, w = 320) =>
  `/api/runs/${id}/pages/${encodeURIComponent(filename)}?w=${w}`;

// ── edits ─────────────────────────────────────────────────────────────────────
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
    scores: { spatial: number; text: number; total: number };
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
/** Registered techniques for a phase (yomeru/plugins), with their options schema. */
export const getBackends = (phase: PhaseName) =>
  req<BackendInfo[]>(`/config/backends/${phase}`);
/** Local model server (Ollama): status, installed models, GPU, suggestion, downloads. */
export const getLocalModels = (server?: string) =>
  req<LocalModelsInfo>(`/config/local-models${server ? `?server=${encodeURIComponent(server)}` : ""}`);
export const pullLocalModel = (model: string, server?: string) =>
  req<{ started: boolean; model: string }>(`/config/local-models/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, server }),
  });
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
        throw new Error(e.detail ?? "Upload failed");
      });
    return r.json() as Promise<FontInfo>;
  });
};


// ── translation review & run metadata ───────────────────────────────────────
export interface GlossaryEntry { source: string; target: string }
export interface TranslationState {
  glossary: GlossaryEntry[];
  review: Record<string, string>;      // "p3.d5" → why it needs a look
  model?: string | null;
  retranslated_lines: number;
}
export const getTranslation = (runId: string) => req<TranslationState>(`/phases/${runId}/translation`);
export const retranslate = (runId: string, body: { scope: "all" | "affected"; glossary?: GlossaryEntry[] }) =>
  req<{ status: string; affected?: number | null }>(`/phases/${runId}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
export const patchRun = (runId: string, body: {
  name?: string; series?: string; chapter?: string; global_context?: string;
  character_names?: Record<string, string>;
}) =>
  req<Run & { stale: string[] }>(`/runs/${runId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export interface ReviewItem { region_id: number; kind: "overflow" | "located" | "split_sfx"; text: string }
export const getTypesetReview = (runId: string) =>
  req<Record<string, ReviewItem[]>>(`/runs/${runId}/typeset/review`);
