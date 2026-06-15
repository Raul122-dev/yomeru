import type { RenderEvent } from "../../lib/types";

interface RenderLogProps {
  renders: RenderEvent[];
  pageNum: number;
  compact?: boolean;
}

export function RenderLog({
  renders,
  pageNum,
  compact = false,
}: RenderLogProps) {
  const ok = renders.filter((r) => r.status === "ok").length;
  const skipped = renders.filter((r) => r.status === "skip").length;

  return (
    <div className="space-y-1.5">
      {!compact && (
        <div className="flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--accent2))]">
            render log · p{pageNum}
          </p>
          <span className="font-mono text-[10px] text-[hsl(var(--text-muted))]">
            {ok} ok{skipped > 0 && ` · ${skipped} skip`}
          </span>
        </div>
      )}
      <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] divide-y divide-[hsl(var(--border))] max-h-72 overflow-y-auto">
        {renders.map((ev, i) => (
          <div
            key={i}
            className="px-3 py-1.5 font-mono text-[10px] leading-relaxed"
          >
            <div className="flex items-baseline gap-2 flex-wrap">
              <span
                className={
                  ev.status === "ok"
                    ? "text-[hsl(var(--success))]"
                    : "text-[hsl(var(--danger))]"
                }
              >
                {ev.status === "ok" ? "✓" : "✗"}
              </span>
              <span className="text-[hsl(var(--text-muted))] shrink-0">
                [{ev.region_id != null ? `r${ev.region_id}` : "—"}]
              </span>
              <span
                className="truncate text-[hsl(var(--text))]"
                title={ev.text}
              >
                {ev.text.slice(0, 32)}
                {ev.text.length > 32 ? "…" : ""}
              </span>
              <span className="ml-auto shrink-0 text-[hsl(var(--text-muted))]">
                {ev.status === "ok" ? (
                  `${ev.lines?.length}L · ${ev.font_size}px · ${ev.font_style} · [${ev.line_source}]`
                ) : (
                  <span className="text-[hsl(var(--danger)/.7)]">
                    {ev.skip_reason}
                  </span>
                )}
              </span>
            </div>
            {ev.status === "ok" && ev.lines && ev.lines.length > 0 && (
              <div className="mt-0.5 pl-4 flex flex-wrap gap-1">
                {ev.lines.map((l, j) => (
                  <span
                    key={j}
                    className="rounded bg-[hsl(var(--bg-subtle))] px-1 text-[hsl(var(--text-muted))]"
                  >
                    "{l}"
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
