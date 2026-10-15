/**
 * Review flags of the typesetting steps: what deserves a human look per page
 * (text past its box, regions found by OCR, repeated sounds that were split).
 */
import { useQuery } from "@tanstack/react-query";
import { getTypesetReview, type ReviewItem } from "./api";

export const REVIEW_LABEL: Record<ReviewItem["kind"], { short: string; hint: string }> = {
  overflow: { short: "Overflow", hint: "Didn't fit at the smallest size — drawn past its box. Shorten the text or resize it." },
  located: { short: "Found by OCR", hint: "The detector missed this text; it was found by reading the page. Check its box." },
  split_sfx: { short: "Split sound", hint: "A repeated sound read as one line was split, one per place it appears. Check each copy." },
};

export function useTypesetReview(runId: string, nonce?: number) {
  const { data = {} } = useQuery({
    queryKey: ["typeset-review", runId, nonce],
    queryFn: () => getTypesetReview(runId),
    retry: false,
  });
  return data;
}

export function ReviewBadge({ kind }: { kind: ReviewItem["kind"] }) {
  const l = REVIEW_LABEL[kind];
  return (
    <span title={l.hint}
          className="rounded border border-[hsl(var(--warning)/.6)] px-1 text-[10px] leading-4 text-[hsl(var(--warning-deep))]">
      {l.short}
    </span>
  );
}
