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
  | "partial";

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
  ui_language: string;
  execution_mode: "sequential" | "manual";
  status: "pending" | "running" | "done" | "failed";
  phase_status: Record<PhaseName, PhaseStatus>;
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
  detector_backend?: string;
  detector_threshold?: number;
  auto_start?: boolean;
}

export interface AppConfig {
  providers: Record<string, { api_key?: string; base_url?: string }>;
  defaults: {
    model: string;
    format: string;
    provider: string;
    source_language: string;
    target_language: string;
  };
  translation: {
    enabled: boolean;
    model: string;
    provider: string;
    base_url: string;
    api_key: string;
  };
  phases: {
    detection: { backend: string; threshold: number };
    matching: {
      backend: string;
      ocr_weight: number;
      spatial_weight: number;
      position_weight: number;
      min_score: number;
    };
    inpainting: { backend: string };
    rendering: {
      backend: string;
      use_translation: boolean;
      skip_sfx: boolean;
      skip_narration: boolean;
      padding: number;
      min_font_size: number;
      max_font_size: number;
    };
  };
}

export interface ModelInfo {
  id: string;
  name: string;
  vision: boolean | null;
}

export interface ProviderInfo {
  key: string;
  label: string;
  ready: boolean;
}

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

export interface FontInfo {
  name: string;
  size_kb: number;
}
