import {
  runMatchingStage,
  runInpaintingStage,
  runRenderingStage,
} from "../api";

export type TypesetStage =
  | "typeset_matching"
  | "typeset_inpainting"
  | "typeset_rendering";

export interface StageConfig {
  key: TypesetStage;
  label: string;
  debugKey: "s3_matching" | "s4_inpainted" | "s5_final";
  statusKey:
    | "typeset_matching_status"
    | "typeset_inpainting_status"
    | "typeset_rendering_status";
  runLabel: string;
  runFn: (runId: string, body?: object) => Promise<{ ok: boolean }>;
  nextStage: TypesetStage | null;
  nextLabel: string | null;
}

export const STAGE_CONFIG: Record<TypesetStage, StageConfig> = {
  typeset_matching: {
    key: "typeset_matching",
    label: "S3 — Matching",
    debugKey: "s3_matching",
    statusKey: "typeset_matching_status",
    runFn: runMatchingStage,
    runLabel: "run matching",
    nextStage: "typeset_inpainting",
    nextLabel: "go to inpainting →",
  },
  typeset_inpainting: {
    key: "typeset_inpainting",
    label: "S4 — Inpainting",
    debugKey: "s4_inpainted",
    statusKey: "typeset_inpainting_status",
    runFn: runInpaintingStage,
    runLabel: "run inpainting",
    nextStage: "typeset_rendering",
    nextLabel: "go to rendering →",
  },
  typeset_rendering: {
    key: "typeset_rendering",
    label: "S5 — Rendering",
    debugKey: "s5_final",
    statusKey: "typeset_rendering_status",
    runFn: runRenderingStage,
    runLabel: "run rendering",
    nextStage: null,
    nextLabel: null,
  },
};
