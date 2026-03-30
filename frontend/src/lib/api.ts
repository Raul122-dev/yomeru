const B = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(B + path, init);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ── runs ──────────────────────────────────────────────────────────────────────
export interface Run {
  id: string;
  name: string;
  model: string;
  comic_format: string;
  provider: string;
  source_language: string;
  translate: boolean;
  target_language: string | null;
  global_context: string;
  ui_language: string;
  status: "pending" | "running" | "done" | "failed";
  total_pages: number;
  processed_pages: number;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  detector_backend?: string;
  detector_threshold?: number;
  // phase sub-statuses
  detection_status: "pending" | "running" | "done" | "failed";
  analysis_status: "pending" | "running" | "done" | "failed";
  detected_pages?: number;
  typeset_status?: "pending" | "running" | "done" | "failed";
}

export const listRuns = () => req<Run[]>("/runs");
export const getRun = (id: str) => req<Run>(`/runs/${id}`);
export const startDetection = (id: str) =>
  req<Run>(`/runs/${id}/detect`, { method: "POST" });
export const startAnalysis = (id: str) =>
  req<Run>(`/runs/${id}/analyze`, { method: "POST" });
export const runAll = (id: str) =>
  req<Run>(`/runs/${id}/run-all`, { method: "POST" });

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

export interface CreateRunOpts {
  detector_backend?: string;
  detector_threshold?: number;
  auto_start?: boolean;
}
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
export interface AppConfig {
  providers: Record<string, { api_key?: string; base_url?: string }>;
  defaults: {
    model: string;
    format: string;
    provider: string;
    ui_language: string;
    source_language: string;
  };
}

export const getConfig = () => req<AppConfig>("/config");
export const getFormats = () =>
  req<{ key: string; name: string; reading_order: string; origin: string }[]>(
    "/config/formats",
  );
export const getLocalModels = () =>
  req<{ id: string; name: string }[]>("/config/models/local");

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
  ui_language?: string;
  source_language?: string;
  provider?: string;
}) =>
  req("/config/defaults", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// ── websocket ─────────────────────────────────────────────────────────────────
type str = string;

export function connectWS(
  runId: string,
  onEvent: (e: Record<string, unknown>) => void,
): () => void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/runs/${runId}/ws`);
  ws.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {}
  };
  return () => ws.close();
}

export interface ProviderInfo {
  key: string;
  label: string;
  ready: boolean;
}

export const getProviders = () => req<ProviderInfo[]>("/config/providers");

export const getAnalyses = (id: str) => req<unknown[]>(`/runs/${id}/analyses`);
export const pageImageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/pages/${filename}`;

// annotations
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

// edits
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

// retry

// per-stage all-pages runners
export const runMatchingStage = (id: str, body?: object) =>
  req<{ ok: boolean }>(`/runs/${id}/typeset/run/matching`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  });
export const runInpaintingStage = (id: str, body?: object) =>
  req<{ ok: boolean }>(`/runs/${id}/typeset/run/inpainting`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  });
export const runRenderingStage = (id: str, body?: object) =>
  req<{ ok: boolean }>(`/runs/${id}/typeset/run/rendering`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  });

// matching refinements
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
export const reRunMatching = (id: str, page: number) =>
  req<{ ok: boolean }>(`/runs/${id}/typeset/stages/matching/${page}`, {
    method: "POST",
  });

// mask refinements
export const saveMask = (id: str, page: number, maskDataUrl: str) =>
  fetch(`/api/runs/${id}/typeset/masks/${page}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mask_data_url: maskDataUrl }),
  });
export const reRunInpainting = (id: str, page: number) =>
  req<{ ok: boolean }>(`/runs/${id}/typeset/stages/inpainting/${page}`, {
    method: "POST",
  });

// debug image by filename

export const retryRun = (id: str) =>
  req<Run>(`/runs/${id}/retry`, { method: "POST" });

// typesetting
export interface TypesetStatus {
  status: "not_started" | "done";
  pages: string[];
  active: boolean;
}

export interface TypesetCapabilities {
  ready: boolean;
  device: string;
  detectors: { key: string; label: string; available: boolean }[];
  inpainter: string;
  message?: string;
}

export const getTypesetCapabilities = () =>
  req<TypesetCapabilities>("/runs/typeset/capabilities");
export const getTypesetStatus = (id: str) =>
  req<TypesetStatus>(`/runs/${id}/typeset/status`);
export const startTypeset = (id: str, body?: object) =>
  req(`/runs/${id}/typeset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
export const typesetPageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/typeset/pages/${filename}`;

export const getDebugImages = (id: str) =>
  req<{ images: string[] }>(`/runs/${id}/typeset/debug`);
export const debugImageUrl = (id: str, filename: str) =>
  `/api/runs/${id}/typeset/debug/${filename}`;

export interface DetectionRegion {
  id: number;
  label: string;
  score: number;
  bbox: [number, number, number, number];
  size: [number, number];
}

export interface MatchEvent {
  dialogue_index: number;
  region_id: number | null;
  match_type: "direct" | "fallback";
  region: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    label: string;
    score: number;
  };
  scores: { spatial: number; text: number; position: number; total: number };
  ocr_text: string | null;
  dialogue_text: string;
}

export interface RenderEvent {
  dialogue_index: number;
  region_id: number | null;
  text: string;
  status: "ok" | "skip";
  skip_reason?: string;
  lines?: string[];
  font_size?: number;
  font_style?: string;
  line_source?: string;
  tone?: string;
  bubble_type?: string;
  bbox?: number[];
  box_size?: number[];
}

export interface OrphanedRegion {
  region_id: number;
  label: string;
  bbox: [number, number, number, number];
  size: [number, number];
  score: number;
  ocr_text: string | null;
  issue: string;
}

export interface StageLog {
  page_number: number;
  image_size: { w: number; h: number };
  s2_detection: {
    regions_found: number;
    source: "saved" | "fresh";
    regions: DetectionRegion[];
  };
  s3_matching: {
    total_dialogues: number;
    matched: number;
    unmatched_dialogues: number;
    direct: number;
    fallback: number;
    orphaned_regions: number;
    matches: MatchEvent[];
    unmatched: { dialogue_index: number; text: string }[];
    orphaned: OrphanedRegion[];
  };
  s4_inpainting: {
    backend: string;
    mask_pixels: number;
    total_pixels: number;
    coverage_pct: number;
    skipped: boolean;
  };
  s5_rendering: {
    ok: number;
    skipped: number;
    renders: RenderEvent[];
  };
}

export const getRenderLog = (id: string, pageNum: number) =>
  req<StageLog>(`/runs/${id}/typeset/render-log/${pageNum}`);

export interface FontInfo {
  name: string;
  size_kb: number;
}

export const listFonts = () =>
  req<{ fonts: FontInfo[] }>("/runs/typeset/fonts");
export const deleteFont = (name: string) =>
  fetch(B + `/runs/typeset/fonts/${encodeURIComponent(name)}`, {
    method: "DELETE",
  }).then((r) => r.json());
export const uploadFont = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(B + "/runs/typeset/fonts/upload", {
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
