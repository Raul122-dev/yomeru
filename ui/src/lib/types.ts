export type PhaseName =
  | "detection"
  | "analysis"
  | "matching"
  | "inpainting"
  | "rendering";

export type PhaseStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "partial"
  | "stale"
  | "cancelled";

export interface PhaseStatusResponse {
  phase: PhaseName;
  status: PhaseStatus;
  dependencies_met: boolean;
  dependencies: PhaseName[];
}

export interface AllPhasesStatus {
  run_id: string;
  phases: PhaseStatusResponse[];
}

export interface Run {
  id: string;
  name: string;
  model: string;
  comic_format: string;
  provider: string;
  source_language: string;
  target_language: string;
  global_context: string;
  execution_mode: "sequential" | "manual";
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  phase_status: Record<PhaseName, PhaseStatus>;
  connection_name?: string;
  settings?: PipelineSettings;
  total_pages: number;
  processed_pages: number;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  detector_backend?: string;
  detector_threshold?: number;
  detected_pages?: number;
  typeset_status?: PhaseStatus;
  detection_status: PhaseStatus;
  analysis_status: PhaseStatus;
  typeset_matching_status: PhaseStatus;
  typeset_inpainting_status: PhaseStatus;
  typeset_rendering_status: PhaseStatus;
}

export interface PhaseStartPayload {
  options?: Record<string, unknown>;
  page_scope?: number[];
}

export interface CreateRunOpts {
  auto_start?: boolean;
  preset_id?: string;
  /** Partial PipelineSettings applied on top of global → preset */
  settings?: DeepPartial<PipelineSettings>;
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K] };

export type Protocol = "openai" | "anthropic";

export interface Connection {
  id: string;
  name: string;
  protocol: Protocol;
  base_url: string;
  /** Masked (••••abcd); send it back unchanged to keep the stored key */
  api_key: string;
  has_key: boolean;
}

export interface ModelRef {
  connection_id: string;
  model: string;
}

export interface PipelineSettings {
  analysis_model: ModelRef;
  translation_model: ModelRef;
  language: { source: string; target: string; comic_format: string };
  analysis: {
    backend: string;
    options: Record<string, unknown>;
    separate_translation?: SeparateTranslation;
  };
  detection: { backend: string; options: Record<string, unknown>; threshold: number };
  matching: { backend: string; options: { ocr_weight?: number; spatial_weight?: number; min_score?: number } & Record<string, unknown> };
  inpainting: { backend: string; options: Record<string, unknown> };
  rendering: { use_translation: boolean; backend: string; options: Record<string, unknown> };
}

export interface Preset {
  id: string;
  name: string;
  settings: PipelineSettings;
}

export interface AppConfig {
  schema_version: number;
  connections: Connection[];
  settings: PipelineSettings;
  presets: Preset[];
}

export interface ModelInfo {
  id: string;
  name: string;
  vision: boolean | null;
}


export interface TypesetStatus {
  status: "not_started" | "done";
  pages: string[];
  active: boolean;
}

/** A registered technique of a phase (GET /config/backends/{phase}). */
export interface BackendOptionSchema {
  type?: "string" | "number" | "integer" | "boolean";
  enum?: string[];
  default?: unknown;
  title?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  json_schema_extra_hidden?: boolean;
}

export interface LocalModelsInfo {
  running: boolean;
  version?: string;
  error?: string;
  server: string;
  models: { name: string; size_gb: number; vision: boolean | null }[];
  gpu: { name: string; total_gb: number; free_gb: number } | null;
  suggested: { tag: string; note: string };
  catalogue: { tag: string; min_vram_gb: number; note: string }[];
  pulls: Record<string, { status: string; completed: number; total: number; done: boolean; error: string | null }>;
}

export interface BackendInfo {
  name: string;
  description: string;
  needs_gpu: boolean;
  version: string;
  schema_version: number;
  compatible: boolean;
  defaults: Record<string, unknown>;
  options: { properties?: Record<string, BackendOptionSchema> };
}

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
  scores: { spatial: number; text: number; total: number };
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

export interface FontInfo {
  name: string;
  size_kb: number;
}

export interface SeparateTranslation {
  enabled: boolean;
  local: boolean;
  local_model: string;
  local_server: string;
}
