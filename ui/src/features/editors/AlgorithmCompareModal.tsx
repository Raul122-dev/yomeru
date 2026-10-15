/**
 * AlgorithmCompareModal — shows Hungarian algorithm-only matching results
 * for comparison with the VLM+algorithm combined approach.
 */
import { useState } from "react";
import { X, Loader2, FlaskConical, CheckCircle2, XCircle } from "lucide-react";
import { runAlgorithmOnlyMatching, debugImageUrl, type AlgorithmMatchResult } from "../../lib/api";
import { cn } from "../../lib/utils";

interface Props {
  runId: string;
  pageNum: number;
  isOpen: boolean;
  onClose: () => void;
}

export function AlgorithmCompareModal({ runId, pageNum, isOpen, onClose }: Props) {
  const [data, setData] = useState<AlgorithmMatchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runComparison = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runAlgorithmOnlyMatching(runId, pageNum);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not run the algorithm-only matching");
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative flex max-h-[85vh] w-full max-w-3xl flex-col rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-3">
          <div className="flex items-center gap-2">
            <FlaskConical size={16} className="text-[hsl(var(--accent2))]" />
            <h2 className="text-sm font-semibold">Algorithm-only matching — page {pageNum}</h2>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-[hsl(var(--bg-subtle))]">
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {!data && !loading && (
            <div className="flex flex-col items-center gap-4 py-10">
              <p className="text-sm text-[hsl(var(--text-muted))] text-center max-w-md">
                Match this page without the reading model's bubble choices, to see how lines are paired 
                with regions using only their position and the text OCR finds in each region.
              </p>
              <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] p-4 text-xs space-y-2 max-w-md">
                <p className="font-medium text-[hsl(var(--text-primary))]">How it works</p>
                <ul className="space-y-1 text-[hsl(var(--text-muted))] list-disc list-inside">
                  <li><strong>Spatial score (40%)</strong> — Overlap between the box the model gave for each line and each detected region, plus whether its center falls inside</li>
                  <li><strong>Text score (40%)</strong> — OCR reads each region; its text is compared with each line</li>
                  <li><strong>Assignment</strong> — Finds the best one-to-one pairing of lines and regions (Hungarian algorithm)</li>
                  <li><strong>Threshold</strong> — Pairs with a total score below 0.05 are dropped</li>
                </ul>
              </div>
              <button
                onClick={runComparison}
                className="flex items-center gap-2 rounded-md bg-[hsl(var(--accent2))] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                <FlaskConical size={14} />
                Run algorithm-only matching
              </button>
            </div>
          )}

          {loading && (
            <div className="flex flex-col items-center gap-3 py-16">
              <Loader2 size={24} className="animate-spin text-[hsl(var(--accent2))]" />
              <p className="text-sm text-[hsl(var(--text-muted))]">Reading regions with OCR and matching…</p>
            </div>
          )}

          {error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {data && !loading && (
            <>
              {/* Summary */}
              <div className="grid grid-cols-4 gap-3">
                <StatCard label="Matched" value={data.matches.length} total={data.dialogues_total} />
                <StatCard label="Unmatched" value={data.unmatched.length} total={data.dialogues_total} variant="danger" />
                <StatCard label="Regions" value={data.regions_used} />
                <StatCard label="Model agreement" value={`${data.agreement_rate}%`} variant={data.agreement_rate > 70 ? "success" : "warning"} />
              </div>

              {/* Matches table */}
              <div className="space-y-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
                  Matches ({data.matches.length})
                </h3>
                <div className="rounded border border-[hsl(var(--border))] overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-[hsl(var(--bg-subtle))]">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Line</th>
                        <th className="px-3 py-2 text-left font-medium">Region</th>
                        <th className="px-3 py-2 text-center font-medium">Spatial</th>
                        <th className="px-3 py-2 text-center font-medium">Text</th>
                        <th className="px-3 py-2 text-center font-medium">Total</th>
                        <th className="px-3 py-2 text-center font-medium" title="Same region the reading model chose">Model</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[hsl(var(--border))]">
                      {data.matches.map((m) => (
                        <tr key={m.dialogue_index} className="hover:bg-[hsl(var(--bg-subtle))]">
                          <td className="px-3 py-2">
                            <div className="font-mono text-xs text-[hsl(var(--text-muted))]">D{m.dialogue_index}</div>
                            <div className="truncate max-w-[180px]" title={m.dialogue_text}>{m.dialogue_text}</div>
                            {m.speaker && <div className="text-xs text-[hsl(var(--accent2))]">{m.speaker}</div>}
                          </td>
                          <td className="px-3 py-2">
                            <span className="font-mono">R{m.region_id}</span>
                            <span className="ml-1 text-xs text-[hsl(var(--text-muted))]">{m.region_label}</span>
                            {m.ocr_text && (
                              <div className="mt-0.5 text-xs text-[hsl(var(--text-muted))] italic truncate max-w-[120px]" title={m.ocr_text}>
                                OCR: {m.ocr_text}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <ScoreCell value={m.scores.spatial} />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <ScoreCell value={m.scores.text} />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <ScoreCell value={m.scores.total} bold />
                          </td>
                          <td className="px-3 py-2 text-center">
                            {m.agrees_with_vlm ? (
                              <CheckCircle2 size={14} className="inline text-green-500" />
                            ) : (
                              <span className="flex flex-col items-center">
                                <XCircle size={14} className="text-yellow-500" />
                                {m.vlm_region_id != null && (
                                  <span className="text-xs text-[hsl(var(--text-muted))]">Model: R{m.vlm_region_id}</span>
                                )}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Unmatched */}
              {data.unmatched.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-medium uppercase tracking-wide text-red-400">
                    Unmatched lines ({data.unmatched.length})
                  </h3>
                  <div className="space-y-1">
                    {data.unmatched.map((u) => (
                      <div key={u.dialogue_index} className="flex items-center gap-2 rounded border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs">
                        <span className="font-mono text-[hsl(var(--text-muted))]">D{u.dialogue_index}</span>
                        <span className="truncate">{u.dialogue_text}</span>
                        {u.speaker && <span className="ml-auto text-xs text-[hsl(var(--accent2))]">{u.speaker}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Debug image */}
              {data.debug_image && (
                <div className="space-y-2">
                  <h3 className="text-xs font-medium uppercase tracking-wide text-[hsl(var(--text-muted))]">
                    Visual result
                  </h3>
                  <div className="rounded border border-[hsl(var(--border))] overflow-hidden">
                    <img
                      src={`${debugImageUrl(runId, data.debug_image)}?v=${Date.now()}`}
                      alt="Algorithm-only matching result"
                      className="w-full h-auto"
                    />
                  </div>
                  <p className="text-xs text-[hsl(var(--text-muted))] text-center">
                    Blue = matched by the algorithm · Red = unmatched regions
                  </p>
                </div>
              )}

              {/* Re-run button */}
              <div className="flex justify-center pt-2">
                <button
                  onClick={runComparison}
                  className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs hover:bg-[hsl(var(--bg-subtle))]"
                >
                  <FlaskConical size={12} />
                  Re-run
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, total, variant }: { label: string; value: number | string; total?: number; variant?: "success" | "danger" | "warning" }) {
  const color = variant === "danger" ? "text-red-400" : variant === "success" ? "text-green-400" : variant === "warning" ? "text-yellow-400" : "text-[hsl(var(--text-primary))]";
  return (
    <div className="rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-3 py-2 text-center">
      <div className={cn("text-lg font-bold font-mono", color)}>{value}</div>
      <div className="text-xs text-[hsl(var(--text-muted))]">
        {label}{total != null ? ` / ${total}` : ""}
      </div>
    </div>
  );
}

function ScoreCell({ value, bold }: { value: number; bold?: boolean }) {
  const color = value > 0.6 ? "text-green-400" : value > 0.3 ? "text-yellow-400" : value > 0.05 ? "text-orange-400" : "text-red-400";
  return (
    <span className={cn("font-mono", color, bold && "font-bold")}>
      {value.toFixed(2)}
    </span>
  );
}
