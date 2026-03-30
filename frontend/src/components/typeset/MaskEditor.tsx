/**
 * MaskEditor — paint/erase the inpainting mask directly on the page.
 *
 * Shows the original page with the current mask overlaid in red.
 * User can paint (add mask) or erase (remove mask) with a brush.
 * Save → PUT /runs/{id}/typeset/masks/{page}  (sends base64 PNG)
 * Re-inpaint → POST /runs/{id}/typeset/stages/inpainting/{page}
 */
import { useRef, useState, useEffect, useCallback } from "react";
import { Stage, Layer, Image as KonvaImage, Line } from "react-konva";
import useImage from "use-image";
import type Konva from "konva";
import { Save, RotateCcw, RefreshCw, Brush, Eraser } from "lucide-react";
import {
  pageImageUrl,
  saveMask,
  reRunInpainting,
  debugImageUrl,
} from "../../lib/api";
import { cn } from "../../lib/utils";
import type { StageLog } from "../../lib/api";

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
  const maskCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // Load background (original page image) and inpainted reference
  const pageUrl = pageImageUrl(runId, filename);
  const [bgImage] = useImage(pageUrl, "anonymous");
  // Load inpainted debug image as overlay reference (to show what was already cleaned)
  const inpaintedUrl = debugImageUrl(
    runId,
    `p${String(pageNum).padStart(2, "0")}_s4_inpainted.jpg`,
  );
  const [inpaintedImg] = useImage(inpaintedUrl, "anonymous");

  // Load current inpainted image as reference overlay (optional)
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
  const [opacity, setOpacity] = useState(0.5);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [current, setCurrent] = useState<Stroke | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [showReference, setShowReference] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isInpainting, setIsInpainting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── drawing ────────────────────────────────────────────────────────────────

  const getPos = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return null;
    const pos = stage.getPointerPosition();
    if (!pos) return null;
    return { x: pos.x / scale, y: pos.y / scale }; // back to original coords
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
    setIsInpainting(true);
    setError(null);
    try {
      if (isDirty) {
        const dataUrl = exportMask();
        await saveMask(runId, pageNum, dataUrl);
        setIsDirty(false);
      }
      await reRunInpainting(runId, pageNum);
      onSaved?.();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setIsInpainting(false);
    }
  };

  // Convert stroke to Konva points array [x, y, x, y, ...]
  const toKonvaPoints = (pts: MaskPoint[]) =>
    pts.flatMap((p) => [p.x * scale, p.y * scale]);

  return (
    <div className="flex min-h-0 h-full overflow-hidden rounded-lg border border-[hsl(var(--border))]">
      {/* canvas */}
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
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setShowReference((v) => !v)}
              className={cn(
                "rounded border px-2 py-1 text-[11px] transition-colors",
                showReference
                  ? "border-[hsl(var(--accent2)/.4)] text-[hsl(var(--accent2))]"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
              )}
            >
              {showReference ? "hide inpainted" : "show inpainted"}
            </button>
            <button
              onClick={undo}
              disabled={strokes.length === 0}
              className="rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
            >
              undo
            </button>
            <button
              onClick={clearAll}
              disabled={strokes.length === 0}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
            >
              <RotateCcw size={9} /> clear
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] disabled:opacity-40 transition-colors"
            >
              <Save size={9} /> {isSaving ? "saving…" : "save mask"}
            </button>
            <button
              onClick={handleReInpaint}
              disabled={isInpainting}
              className="flex items-center gap-1.5 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-[11px] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            >
              <RefreshCw
                size={10}
                className={isInpainting ? "animate-spin" : ""}
              />
              {isInpainting ? "re-inpainting…" : "▶ re-inpaint"}
            </button>
          </div>
        </div>

        {/* canvas */}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto bg-[hsl(var(--bg))] p-2"
          style={{
            cursor: mode === "paint" ? "crosshair" : "cell",
            position: "relative",
          }}
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

            {/* optional inpainted reference overlay */}
            {showReference && inpaintedImg && (
              <Layer opacity={0.5} listening={false}>
                <KonvaImage image={inpaintedImg} width={dispW} height={dispH} />
              </Layer>
            )}

            {/* mask strokes overlay — red paint layer */}
            <Layer opacity={opacity} listening={false}>
              {[...strokes, ...(current ? [current] : [])].map((stroke, i) => {
                const pts = toKonvaPoints(stroke.points);
                if (pts.length < 2) return null;
                return (
                  <Line
                    key={i}
                    points={pts}
                    stroke={stroke.mode === "paint" ? "#ff2222" : "#000000"}
                    strokeWidth={stroke.size * scale}
                    lineCap="round"
                    lineJoin="round"
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
          </Stage>
        </div>
      </div>

      {/* sidebar controls */}
      <div className="w-52 shrink-0 border-l border-[hsl(var(--border))] flex flex-col p-3 gap-4 overflow-y-auto">
        {/* mode */}
        <div>
          <p className="mb-1.5 text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
            mode
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {(["paint", "erase"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "flex items-center justify-center gap-1.5 rounded border py-2 text-xs transition-colors",
                  mode === m
                    ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)] text-[hsl(var(--accent2))]"
                    : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))]",
                )}
              >
                {m === "paint" ? <Brush size={11} /> : <Eraser size={11} />}
                {m}
              </button>
            ))}
          </div>
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
        </div>

        {/* mask opacity */}
        <div>
          <div className="flex justify-between mb-1">
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              overlay opacity
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
        </div>

        {/* stats */}
        {hasMask && (
          <div className="rounded border border-[hsl(var(--border))] p-2.5 space-y-1 text-[11px]">
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))] mb-1">
              original mask
            </p>
            <div className="flex justify-between">
              <span className="text-[hsl(var(--text-muted))]">backend</span>
              <span className="font-mono">{s4?.backend}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[hsl(var(--text-muted))]">coverage</span>
              <span className="font-mono">{s4?.coverage_pct}%</span>
            </div>
          </div>
        )}

        <div className="text-[9px] text-[hsl(var(--text-muted)/.5)] leading-relaxed space-y-1">
          <p>Red = pixels to erase.</p>
          <p>
            Paint over text to add to mask. Erase mode removes painted areas.
          </p>
          <p>Save mask then re-inpaint to apply changes.</p>
        </div>
      </div>
    </div>
  );
}
