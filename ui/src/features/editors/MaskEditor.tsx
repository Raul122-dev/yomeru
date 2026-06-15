/**
 * MaskEditor — paint/erase the inpainting mask directly on the page.
 *
 * Shows the original page with the current mask overlaid in magenta.
 * User can paint (add mask) or erase (remove mask) with a brush.
 * Save → PUT /runs/{id}/typeset/masks/{page}  (sends base64 PNG)
 * Re-inpaint → POST /runs/{id}/typeset/stages/inpainting/{page}
 *
 * Keyboard shortcuts:
 *   B — paint mode
 *   E — erase mode
 *   [ / ] — decrease/increase brush size
 *   Ctrl+Z — undo last stroke
 *   Ctrl+S — save mask
 *   R — toggle inpainted reference overlay
 */
import { useRef, useState, useEffect, useCallback } from "react";
import { Stage, Layer, Image as KonvaImage, Line } from "react-konva";
import useImage from "use-image";
import type Konva from "konva";
import {
  Save,
  RotateCcw,
  RefreshCw,
  Brush,
  Eraser,
  Eye,
  EyeOff,
  Undo2,
  Trash2,
  Info,
} from "lucide-react";
import {
  pageImageUrl,
  saveMask,
  debugImageUrl,
} from "../../lib/api";
import { useScopedPhaseRunner } from "../../hooks/useScopedPhaseRunner";
import { cn } from "../../lib/utils";
import type { StageLog } from "../../lib/types";

interface MaskPoint {
  x: number;
  y: number;
}
interface Stroke {
  points: MaskPoint[];
  mode: "paint" | "erase";
  size: number;
}

interface MaskEditorProps {
  runId: string;
  pageNum: number;
  filename: string;
  stageLog: StageLog;
  originalW: number;
  originalH: number;
  onSaved?: () => void;
}

// Mask overlay color — magenta for high visibility on both light and dark manga pages
const MASK_COLOR = "#ff00ff";
const ERASE_COLOR = "#000000";

export function MaskEditor({
  runId,
  pageNum,
  filename,
  stageLog,
  originalW,
  originalH,
  onSaved,
}: MaskEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);

  // Load background (original page image) and inpainted reference
  const pageUrl = pageImageUrl(runId, filename);
  const [bgImage] = useImage(pageUrl, "anonymous");
  const inpaintedUrl = debugImageUrl(
    runId,
    `p${String(pageNum).padStart(2, "0")}_s4_inpainted.jpg`,
  );
  const [inpaintedImg] = useImage(inpaintedUrl, "anonymous");

  const s4 = stageLog.s4_inpainting;
  const hasMask = !s4?.skipped && (s4?.mask_pixels ?? 0) > 0;

  const [containerW, setContainerW] = useState(600);
  useEffect(() => {
    if (!containerRef.current) return;
    const ob = new ResizeObserver((e) => setContainerW(e[0].contentRect.width));
    ob.observe(containerRef.current);
    return () => ob.disconnect();
  }, []);

  const maxDispH =
    typeof window !== "undefined" ? window.innerHeight * 0.75 : 600;
  const scaleW = containerW / (originalW || 1);
  const scaleH = maxDispH / (originalH || 600);
  const scale = Math.min(scaleW, scaleH, 1);
  const dispW = (originalW || 600) * scale;
  const dispH = (originalH || 600) * scale;

  // Editor state
  const [mode, setMode] = useState<"paint" | "erase">("paint");
  const [brushSize, setBrushSize] = useState(20);
  const [opacity, setOpacity] = useState(0.6);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [current, setCurrent] = useState<Stroke | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [showReference, setShowReference] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { progress: rerunProgress, start: startRerun } = useScopedPhaseRunner({
    runId,
    phase: "inpainting",
    onComplete: () => onSaved?.(),
    onError: (msg) => setError(msg),
  });
  const isInpainting = rerunProgress.status === "running";

  // ── keyboard shortcuts ────────────────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      if ((e.target as HTMLElement).tagName === "INPUT") return;

      if (e.key === "b" || e.key === "B") {
        e.preventDefault();
        setMode("paint");
      } else if (e.key === "e" || e.key === "E") {
        e.preventDefault();
        setMode("erase");
      } else if (e.key === "[") {
        e.preventDefault();
        setBrushSize((s) => Math.max(4, s - 4));
      } else if (e.key === "]") {
        e.preventDefault();
        setBrushSize((s) => Math.min(80, s + 4));
      } else if (e.key === "z" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setStrokes((prev) => prev.slice(0, -1));
      } else if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (isDirty) handleSave();
      } else if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        setShowReference((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isDirty]);

  // ── drawing ────────────────────────────────────────────────────────────────

  const getPos = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return null;
    const pos = stage.getPointerPosition();
    if (!pos) return null;
    return { x: pos.x / scale, y: pos.y / scale };
  }, [scale]);

  const onMouseDown = useCallback(
    (e: Konva.KonvaEventObject<MouseEvent>) => {
      e.evt.preventDefault();
      const pos = getPos();
      if (!pos) return;
      setIsDrawing(true);
      setCurrent({ points: [pos], mode, size: brushSize / scale });
    },
    [mode, brushSize, scale, getPos],
  );

  const onMouseMove = useCallback(
    (e: Konva.KonvaEventObject<MouseEvent>) => {
      e.evt.preventDefault();
      if (!isDrawing || !current) return;
      const pos = getPos();
      if (!pos) return;
      setCurrent((prev) =>
        prev ? { ...prev, points: [...prev.points, pos] } : null,
      );
    },
    [isDrawing, current, getPos],
  );

  const onMouseUp = useCallback(() => {
    if (!isDrawing || !current || current.points.length < 1) {
      setIsDrawing(false);
      setCurrent(null);
      return;
    }
    setStrokes((prev) => [...prev, current]);
    setCurrent(null);
    setIsDrawing(false);
    setIsDirty(true);
  }, [isDrawing, current]);

  const undo = () => {
    setStrokes((prev) => prev.slice(0, -1));
    setIsDirty(strokes.length > 1);
  };

  const clearAll = () => {
    setStrokes([]);
    setIsDirty(false);
  };

  // ── export mask as PNG ─────────────────────────────────────────────────────

  const exportMask = useCallback((): string => {
    const canvas = document.createElement("canvas");
    canvas.width = originalW;
    canvas.height = originalH;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, originalW, originalH);

    for (const stroke of [...strokes, ...(current ? [current] : [])]) {
      if (stroke.points.length < 1) continue;
      ctx.globalCompositeOperation =
        stroke.mode === "paint" ? "source-over" : "destination-out";
      ctx.strokeStyle = "white";
      ctx.lineWidth = stroke.size;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
      for (let i = 1; i < stroke.points.length; i++) {
        ctx.lineTo(stroke.points[i].x, stroke.points[i].y);
      }
      ctx.stroke();
    }

    return canvas.toDataURL("image/png");
  }, [strokes, current, originalW, originalH]);

  // ── save / re-inpaint ──────────────────────────────────────────────────────

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const dataUrl = exportMask();
      await saveMask(runId, pageNum, dataUrl);
      setIsDirty(false);
      onSaved?.();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setIsSaving(false);
    }
  };

  const handleReInpaint = async () => {
    setError(null);
    try {
      if (isDirty) {
        const dataUrl = exportMask();
        await saveMask(runId, pageNum, dataUrl);
        setIsDirty(false);
      }
      await startRerun([pageNum]);
    } catch (e: unknown) {
      setError(String(e));
    }
  };

  const toKonvaPoints = (pts: MaskPoint[]) =>
    pts.flatMap((p) => [p.x * scale, p.y * scale]);

  return (
    <div className="flex min-h-0 h-full overflow-hidden rounded-lg border border-[hsl(var(--border))]">
      {/* canvas area */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
          <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
            mask editor · p{pageNum}
          </span>
          {isDirty && (
            <span className="text-[9px] text-[hsl(var(--accent2))]">
              unsaved
            </span>
          )}
          {error && (
            <span className="text-[10px] text-[hsl(var(--danger))] truncate max-w-32">
              {error}
            </span>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => setShowReference((v) => !v)}
              className={cn(
                "flex items-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors",
                showReference
                  ? "border-[hsl(var(--accent2)/.4)] text-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
              )}
              title="Toggle inpainted result overlay (R)"
            >
              {showReference ? <EyeOff size={10} /> : <Eye size={10} />}
              {showReference ? "hide result" : "show result"}
            </button>
            <button
              onClick={undo}
              disabled={strokes.length === 0}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
              title="Undo last stroke (Ctrl+Z)"
            >
              <Undo2 size={9} />
            </button>
            <button
              onClick={clearAll}
              disabled={strokes.length === 0}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
              title="Clear all strokes"
            >
              <Trash2 size={9} />
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
              title="Save mask (Ctrl+S)"
            >
              <Save size={9} /> {isSaving ? "saving…" : "save"}
            </button>
            <button
              onClick={handleReInpaint}
              disabled={isInpainting}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-[11px] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
              title="Save mask and re-run inpainting for this page"
            >
              <RefreshCw
                size={10}
                className={isInpainting ? "animate-spin" : ""}
              />
              {isInpainting ? "inpainting…" : "re-inpaint"}
            </button>
          </div>
        </div>

        {/* canvas — centered */}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto bg-[hsl(var(--bg))] flex items-center justify-center p-2"
          style={{ cursor: mode === "paint" ? "crosshair" : "cell" }}
        >
          <Stage
            ref={stageRef}
            width={dispW}
            height={dispH}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
          >
            {/* background image */}
            <Layer>
              {bgImage && (
                <KonvaImage
                  image={bgImage}
                  width={dispW}
                  height={dispH}
                  listening={false}
                />
              )}
            </Layer>

            {/* optional inpainted reference overlay — full opacity to clearly show result */}
            {showReference && inpaintedImg && (
              <Layer listening={false}>
                <KonvaImage image={inpaintedImg} width={dispW} height={dispH} />
              </Layer>
            )}

            {/* mask strokes overlay — magenta for visibility */}
            {!showReference && (
              <Layer listening={false}>
                {[...strokes, ...(current ? [current] : [])].map((stroke, i) => {
                  const pts = toKonvaPoints(stroke.points);
                  if (pts.length < 2) return null;
                  return (
                    <Line
                      key={i}
                      points={pts}
                      stroke={stroke.mode === "paint" ? MASK_COLOR : ERASE_COLOR}
                      strokeWidth={stroke.size * scale}
                      lineCap="round"
                      lineJoin="round"
                      opacity={stroke.mode === "paint" ? opacity : 1}
                      globalCompositeOperation={
                        stroke.mode === "erase"
                          ? "destination-out"
                          : "source-over"
                      }
                      listening={false}
                    />
                  );
                })}
              </Layer>
            )}
          </Stage>
        </div>
      </div>

      {/* sidebar controls */}
      <div className="w-56 shrink-0 border-l border-[hsl(var(--border))] flex flex-col p-3 gap-4 overflow-y-auto">
        {/* mode selector */}
        <div>
          <p className="mb-1.5 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
            tool
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {(["paint", "erase"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "flex flex-col items-center gap-1 rounded border py-2 text-xs transition-colors",
                  mode === m
                    ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                    : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
                )}
                title={m === "paint" ? "Paint mask (B)" : "Erase mask (E)"}
              >
                {m === "paint" ? <Brush size={14} /> : <Eraser size={14} />}
                <span className="text-[10px]">{m}</span>
              </button>
            ))}
          </div>
          <p className="mt-1 text-[9px] text-[hsl(var(--text-muted)/.6)]">
            {mode === "paint"
              ? "Paint over text areas to mark them for removal"
              : "Erase painted areas to exclude them from removal"}
          </p>
        </div>

        {/* brush size */}
        <div>
          <div className="flex justify-between mb-1">
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              brush size
            </p>
            <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
              {brushSize}px
            </span>
          </div>
          <input
            type="range"
            min={4}
            max={80}
            value={brushSize}
            onChange={(e) => setBrushSize(parseInt(e.target.value))}
            className="w-full h-1 accent-[hsl(var(--accent2))] cursor-pointer"
          />
          <p className="mt-0.5 text-[9px] text-[hsl(var(--text-muted)/.6)]">
            Shortcuts: [ decrease · ] increase
          </p>
        </div>

        {/* mask opacity */}
        <div>
          <div className="flex justify-between mb-1">
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              mask visibility
            </p>
            <span className="font-mono text-[10px] text-[hsl(var(--accent2))]">
              {Math.round(opacity * 100)}%
            </span>
          </div>
          <input
            type="range"
            min={10}
            max={90}
            value={opacity * 100}
            onChange={(e) => setOpacity(parseInt(e.target.value) / 100)}
            className="w-full h-1 accent-[hsl(var(--accent2))] cursor-pointer"
          />
          <p className="mt-0.5 text-[9px] text-[hsl(var(--text-muted)/.6)]">
            How visible the magenta overlay appears
          </p>
        </div>

        {/* stats */}
        {hasMask && (
          <div className="rounded border border-[hsl(var(--border))] p-2.5 space-y-1.5 text-[11px]">
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))] mb-1">
              current mask info
            </p>
            <div className="flex justify-between">
              <span className="text-[hsl(var(--text-muted))]">backend</span>
              <span className="font-mono">{s4?.backend}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[hsl(var(--text-muted))]">mask pixels</span>
              <span className="font-mono">{(s4?.mask_pixels ?? 0).toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[hsl(var(--text-muted))]">coverage</span>
              <span className="font-mono">{s4?.coverage_pct}%</span>
            </div>
            <p className="text-[9px] text-[hsl(var(--text-muted)/.6)] pt-1 border-t border-[hsl(var(--border))]">
              Coverage = % of total image pixels marked for removal. Lower is better — only text should be masked.
            </p>
          </div>
        )}

        {/* legend + shortcuts */}
        <div className="rounded border border-[hsl(var(--border))] p-2.5 space-y-2">
          <div className="flex items-center gap-1.5">
            <Info size={10} className="text-[hsl(var(--text-muted))]" />
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              help
            </p>
          </div>
          <div className="space-y-1 text-[10px] text-[hsl(var(--text-muted))]">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: MASK_COLOR }} />
              <span>Masked area (will be inpainted)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-sm border border-[hsl(var(--border))]" />
              <span>Original (preserved)</span>
            </div>
          </div>
          <div className="pt-1.5 border-t border-[hsl(var(--border))] space-y-0.5 text-[9px] text-[hsl(var(--text-muted)/.6)]">
            <p className="font-medium text-[hsl(var(--text-muted))]">Shortcuts</p>
            <p><kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">B</kbd> paint · <kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">E</kbd> erase</p>
            <p><kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">[</kbd> <kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">]</kbd> brush size</p>
            <p><kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">Ctrl+Z</kbd> undo</p>
            <p><kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">Ctrl+S</kbd> save</p>
            <p><kbd className="font-mono bg-[hsl(var(--bg-subtle))] px-1 rounded">R</kbd> toggle result</p>
          </div>
        </div>
      </div>
    </div>
  );
}

