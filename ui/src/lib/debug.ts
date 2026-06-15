export type DebugStageKey =
  | "s2_detection"
  | "s3_matching"
  | "s4_inpainted"
  | "s5_final";

export type DebugImageGroups = Record<
  string,
  Partial<Record<DebugStageKey, string>>
>;

const DEBUG_STAGE_KEYS: DebugStageKey[] = [
  "s2_detection",
  "s3_matching",
  "s4_inpainted",
  "s5_final",
];

export function getDebugPageKey(pageNum: number) {
  return `p${String(pageNum).padStart(2, "0")}`;
}

export function groupDebugImages(images: string[]): DebugImageGroups {
  const groups: DebugImageGroups = {};

  for (const img of images) {
    const match = img.match(/^(p\d+)_(.+)\.(jpg|png)$/i);
    if (!match) continue;

    const [, pageKey, rawStage] = match;
    const normalizedStage = DEBUG_STAGE_KEYS.find((key) =>
      rawStage.includes(key),
    );

    if (!normalizedStage) continue;
    if (!groups[pageKey]) groups[pageKey] = {};
    groups[pageKey][normalizedStage] = img;
  }

  return groups;
}

export function getStageDebugImage(
  groups: DebugImageGroups,
  pageNum: number,
  stageKey: DebugStageKey,
) {
  const pageKey = getDebugPageKey(pageNum);
  return groups[pageKey]?.[stageKey] ?? null;
}
