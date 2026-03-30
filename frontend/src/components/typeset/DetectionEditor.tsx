/**
 * DetectionEditor — interactive editor for S1 detected regions.
 *
 * Features:
 *  - View detected regions as colored boxes over the page image
 *  - Click to select a region → handles appear for resize/move
 *  - Delete key or trash button to remove a region
 *  - Drag on empty canvas to draw a new region
 *  - Change label of selected region
 *  - Save refined → PUT /runs/{id}/detections/{page}
 *  - Revert to original → DELETE /runs/{id}/detections/{page}/refined
 *
 * Coordinate system:
 *   All Konva coords are in *display* space (scaled to fit container).
 *   Original image coords = display_coords / scale.
 *   Saved regions always use original image coordinates.
 */
import { useRef, useState, useEffect, useCallback } from "react";
import {
  Stage,
  Layer,
  Rect,
  Text,
  Transformer,
  Image as KonvaImage,
} from "react-konva";
import useImage from "use-image";
import type Konva from "konva";
import { Trash2, Plus, RotateCcw, Save, X, ChevronDown } from "lucide-react";
import {
  savePageDetections,
  revertPageDetections,
  pageImageUrl,
} from "../../lib/api";
import { cn } from "../../lib/utils";

// ── types ─────────────────────────────────────────────────────────────────────

export interface Region {
  id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: string;
  score: number;
  isNew?: boolean;
}

interface KonvaRegion extends Region {
  // display coords (original * scale)
  kx: number;
  ky: number;
  kw: number;
  kh: number;
}

// ── constants ─────────────────────────────────────────────────────────────────

const LABEL_COLORS: Record<string, string> = {
  bubble: "#1e8cff",
  text_bubble: "#1e8cff",
  text_free: "#ff8c1e",
  sfx: "#dc3c3c",
  caption: "#3cb43c",
};
const DEFAULT_COLOR = "#6464c8";
const LABELS = ["bubble", "text_bubble", "text_free", "sfx", "caption"];

function regionColor(label: string) {
  return LABEL_COLORS[label] ?? DEFAULT_COLOR;
}

function toHex(color: string, alpha: number) {
  // color is already hex — just return with opacity via rgba string
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

let _nextId = 10000;

// ── sub-components ────────────────────────────────────────────────────────────

function RegionShape({
  r,
  isSelected,
  scale,
  onClick,
  onDragEnd,
  onTransformEnd,
}: {
  r: KonvaRegion;
  isSelected: boolean;
  scale: number;
  onClick: () => void;
  onDragEnd: (id: number, x: number, y: number) => void;
  onTransformEnd: (id: number, node: Konva.Node) => void;
}) {
  const shapeRef = useRef<Konva.Rect>(null);
  const color = regionColor(r.label);

  return (
    <Rect
      ref={shapeRef}
      id={String(r.id)}
      x={r.kx}
      y={r.ky}
      width={r.kw}
      height={r.kh}
      fill={toHex(color, isSelected ? 0.2 : 0.12)}
      stroke={color}
      strokeWidth={isSelected ? 2.5 : 1.5}
      draggable
      onClick={onClick}
      onTap={onClick}
      onDragEnd={(e) => onDragEnd(r.id, e.target.x(), e.target.y())}
      onTransformEnd={(e) => onTransformEnd(r.id, e.target)}
    />
  );
}

function RegionLabel({ r }: { r: KonvaRegion }) {
  const color = regionColor(r.label);
  const badgeSize = 18;
  return (
    <>
      <Rect
        x={r.kx}
        y={r.ky - badgeSize / 2}
        width={badgeSize}
        height={badgeSize}
        fill={color}
        cornerRadius={9}
      />
      <Text
        x={r.kx}
        y={r.ky - badgeSize / 2}
        width={badgeSize}
        height={badgeSize}
        text={String(r.id)}
        fontSize={10}
        fontStyle="bold"
        fill="white"
        align="center"
        verticalAlign="middle"
        listening={false}
      />
    </>
  );
}

// ── sidebar region row ────────────────────────────────────────────────────────

function SidebarRow({
  r,
  isSelected,
  onSelect,
  onDelete,
  onLabelChange,
}: {
  r: Region;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onLabelChange: (label: string) => void;
}) {
  const [showLabels, setShowLabels] = useState(false);
  const color = regionColor(r.label);
  const w = r.x2 - r.x1,
    h = r.y2 - r.y1;

  return (
    <div
      onClick={onSelect}
      className={cn(
        "relative flex items-start gap-2 px-3 py-2 cursor-pointer border-b border-[hsl(var(--border))] last:border-0 text-[11px] transition-colors",
        isSelected
          ? "bg-[hsl(var(--accent2)/.06)]"
          : "hover:bg-[hsl(var(--bg-subtle))]",
      )}
    >
      {/* color dot + id */}
      <div className="mt-0.5 flex items-center gap-1.5 shrink-0">
        <div
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: color }}
        />
        <span className="font-mono text-[hsl(var(--text-muted))] w-5">
          [{r.id}]
        </span>
      </div>

      {/* label + size */}
      <div className="flex-1 min-w-0">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setShowLabels((v) => !v);
          }}
          className="flex items-center gap-1 text-[hsl(var(--text))] hover:text-[hsl(var(--accent2))] transition-colors"
        >
          <span>{r.label}</span>
          <ChevronDown size={9} />
        </button>
        <span className="text-[hsl(var(--text-muted)/.6)]">
          {w}×{h}px
        </span>
        {r.isNew && (
          <span className="ml-1 text-[9px] text-[hsl(var(--accent2))]">
            new
          </span>
        )}
        {r.score < 1 && !r.isNew && (
          <span className="ml-1 text-[hsl(var(--text-muted)/.5)]">
            {(r.score * 100).toFixed(0)}%
          </span>
        )}

        {/* label dropdown */}
        {showLabels && (
          <div className="mt-1 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg))] shadow-lg z-10 overflow-hidden">
            {LABELS.map((l) => (
              <button
                key={l}
                onClick={(e) => {
                  e.stopPropagation();
                  onLabelChange(l);
                  setShowLabels(false);
                }}
                className={cn(
                  "block w-full px-2 py-1 text-left text-[10px] hover:bg-[hsl(var(--bg-subtle))] transition-colors",
                  l === r.label && "text-[hsl(var(--accent2))]",
                )}
              >
                {l}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* delete */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="mt-0.5 shrink-0 text-[hsl(var(--text-muted)/.5)] hover:text-[hsl(var(--danger))] transition-colors"
      >
        <Trash2 size={11} />
      </button>
    </div>
  );
}

// ── main editor ───────────────────────────────────────────────────────────────

interface DetectionEditorProps {
  runId: string;
  pageNum: number;
  filename: string;
  initialRegions: Region[];
  originalW: number;
  originalH: number;
  onClose: () => void;
  onSaved: () => void;
}

export function DetectionEditor({
  runId,
  pageNum,
  filename,
  initialRegions,
  originalW,
  originalH,
  onClose,
  onSaved,
}: DetectionEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const trRef = useRef<Konva.Transformer>(null);

  const imgUrl = pageImageUrl(runId, filename);
  const [bgImage] = useImage(imgUrl, "anonymous");

  // display scale: fit image into container width
  const [containerW, setContainerW] = useState(600);
  useEffect(() => {
    if (!containerRef.current) return;
    const ob = new ResizeObserver((entries) => {
      setContainerW(entries[0].contentRect.width);
    });
    ob.observe(containerRef.current);
    return () => ob.disconnect();
  }, []);

  // Constrain to 80vh max height so image fits without scroll
  const maxDispH =
    typeof window !== "undefined" ? window.innerHeight * 0.8 : 600;
  const scaleW = containerW / (originalW || 1);
  const scaleH = maxDispH / (originalH || 600);
  const scale = Math.min(scaleW, scaleH, 1);
  const dispW = (originalW || 600) * scale;
  const dispH = (originalH || 600) * scale;

  // region state (in original image coords)
  const [regions, setRegions] = useState<Region[]>(initialRegions);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // drawing new region
  const [drawing, setDrawing] = useState<{ x: number; y: number } | null>(null);
  const [drawRect, setDrawRect] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);

  // convert to konva (display) coords
  const toKonva = (r: Region): KonvaRegion => ({
    ...r,
    kx: r.x1 * scale,
    ky: r.y1 * scale,
    kw: (r.x2 - r.x1) * scale,
    kh: (r.y2 - r.y1) * scale,
  });

  const kRegions = regions.map(toKonva);

  // Deselect when scale changes (prevents Transformer from showing stale bounds)
  useEffect(() => {
    setSelectedId(null);
  }, [scale]);

  // update transformer when selection changes
  useEffect(() => {
    if (!trRef.current || !stageRef.current) return;
    if (selectedId === null) {
      trRef.current.nodes([]);
      return;
    }
    const node = stageRef.current.findOne(`#${selectedId}`);
    if (node) trRef.current.nodes([node]);
    else trRef.current.nodes([]);
  }, [selectedId, regions]);

  // keyboard delete
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        (e.key === "Delete" || e.key === "Backspace") &&
        selectedId !== null
      ) {
        setRegions((rs) => rs.filter((r) => r.id !== selectedId));
        setSelectedId(null);
        setIsDirty(true);
      }
      if (e.key === "Escape") {
        setSelectedId(null);
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedId]);

  // ── drag to create new region ─────────────────────────────────────────────

  const onStageMouseDown = useCallback(
    (e: Konva.KonvaEventObject<MouseEvent>) => {
      if (e.target !== stageRef.current && e.target.id() !== "bg") {
        // clicked on existing shape — handled by shape click
        return;
      }
      setSelectedId(null);
      const pos = stageRef.current!.getPointerPosition()!;
      setDrawing({ x: pos.x, y: pos.y });
      setDrawRect({ x: pos.x, y: pos.y, w: 0, h: 0 });
    },
    [],
  );

  const onStageMouseMove = useCallback(
    (e: Konva.KonvaEventObject<MouseEvent>) => {
      if (!drawing) return;
      const pos = stageRef.current!.getPointerPosition()!;
      setDrawRect({
        x: Math.min(drawing.x, pos.x),
        y: Math.min(drawing.y, pos.y),
        w: Math.abs(pos.x - drawing.x),
        h: Math.abs(pos.y - drawing.y),
      });
    },
    [drawing],
  );

  const onStageMouseUp = useCallback(() => {
    if (!drawRect || drawRect.w < 10 || drawRect.h < 10) {
      setDrawing(null);
      setDrawRect(null);
      return;
    }
    const newId = ++_nextId;
    const newRegion: Region = {
      id: newId,
      x1: Math.round(drawRect.x / scale),
      y1: Math.round(drawRect.y / scale),
      x2: Math.round((drawRect.x + drawRect.w) / scale),
      y2: Math.round((drawRect.y + drawRect.h) / scale),
      label: "bubble",
      score: 1.0,
      isNew: true,
    };
    setRegions((rs) => [...rs, newRegion]);
    setSelectedId(newId);
    setIsDirty(true);
    setDrawing(null);
    setDrawRect(null);
  }, [drawRect, scale]);

  // ── region mutations ──────────────────────────────────────────────────────

  const onDragEnd = useCallback(
    (id: number, kx: number, ky: number) => {
      setRegions((rs) =>
        rs.map((r) => {
          if (r.id !== id) return r;
          const w = r.x2 - r.x1,
            h = r.y2 - r.y1;
          const nx1 = Math.round(kx / scale),
            ny1 = Math.round(ky / scale);
          return { ...r, x1: nx1, y1: ny1, x2: nx1 + w, y2: ny1 + h };
        }),
      );
      setIsDirty(true);
    },
    [scale],
  );

  const onTransformEnd = useCallback(
    (id: number, node: Konva.Node) => {
      const sx = node.scaleX(),
        sy = node.scaleY();
      node.scaleX(1);
      node.scaleY(1);
      setRegions((rs) =>
        rs.map((r) => {
          if (r.id !== id) return r;
          const nx1 = Math.round(node.x() / scale);
          const ny1 = Math.round(node.y() / scale);
          const nw = Math.round((node.width() * sx) / scale);
          const nh = Math.round((node.height() * sy) / scale);
          return { ...r, x1: nx1, y1: ny1, x2: nx1 + nw, y2: ny1 + nh };
        }),
      );
      setIsDirty(true);
    },
    [scale],
  );

  const deleteRegion = (id: number) => {
    setRegions((rs) => rs.filter((r) => r.id !== id));
    if (selectedId === id) setSelectedId(null);
    setIsDirty(true);
  };

  const changeLabel = (id: number, label: string) => {
    setRegions((rs) => rs.map((r) => (r.id === id ? { ...r, label } : r)));
    setIsDirty(true);
  };

  // ── save / revert ─────────────────────────────────────────────────────────

  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await savePageDetections(runId, pageNum, {
        regions: regions.map(({ id, x1, y1, x2, y2, label, score }) => ({
          id,
          x1,
          y1,
          x2,
          y2,
          label,
          score,
        })),
        original_w: originalW,
        original_h: originalH,
      });
      setIsDirty(false);
      onSaved();
    } catch (e: unknown) {
      setSaveError(String(e));
    } finally {
      setIsSaving(false);
    }
  };

  const handleRevert = async () => {
    await revertPageDetections(runId, pageNum);
    setRegions(initialRegions);
    setSelectedId(null);
    setIsDirty(false);
    onSaved(); // invalidate cache, but DON'T close editor
  };

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full min-h-0 gap-0 overflow-hidden rounded-lg border border-[hsl(var(--border))]">
      {/* canvas area */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
          <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
            p{pageNum} — {filename}
          </span>
          <span className="text-[10px] text-[hsl(var(--text-muted)/.5)]">
            drag to add · click to select · del to remove
          </span>
          <div className="ml-auto flex items-center gap-2">
            {saveError && (
              <span className="text-xs text-[hsl(var(--danger))]">
                {saveError}
              </span>
            )}
            <button
              onClick={handleRevert}
              className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-xs text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))] transition-colors"
            >
              <RotateCcw size={10} /> revert
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className="flex items-center gap-1 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-xs text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            >
              <Save size={10} /> {isSaving ? "saving…" : "save refined"}
            </button>
            <button
              onClick={onClose}
              className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* canvas */}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto bg-[hsl(var(--bg))] p-2"
        >
          <Stage
            ref={stageRef}
            width={dispW}
            height={dispH}
            onMouseDown={onStageMouseDown}
            onMouseMove={onStageMouseMove}
            onMouseUp={onStageMouseUp}
            style={{ cursor: drawing ? "crosshair" : "default" }}
          >
            {/* background image */}
            <Layer>
              {bgImage && (
                <KonvaImage
                  id="bg"
                  image={bgImage}
                  width={dispW}
                  height={dispH}
                  listening={false}
                />
              )}
            </Layer>

            {/* regions layer — key on scale so Konva re-renders shapes on resize */}
            <Layer key={scale}>
              {kRegions.map((r) => (
                <RegionShape
                  key={r.id}
                  r={r}
                  isSelected={r.id === selectedId}
                  scale={scale}
                  onClick={() => setSelectedId(r.id)}
                  onDragEnd={onDragEnd}
                  onTransformEnd={onTransformEnd}
                />
              ))}
              {/* labels on top */}
              {kRegions.map((r) => (
                <RegionLabel key={`lbl-${r.id}`} r={r} />
              ))}
              {/* transformer for selected */}
              <Transformer
                ref={trRef}
                boundBoxFunc={(old, _new) => ({
                  ..._new,
                  width: Math.max(10, _new.width),
                  height: Math.max(10, _new.height),
                })}
                rotateEnabled={false}
                keepRatio={false}
              />
              {/* drawing preview */}
              {drawRect && drawRect.w > 2 && (
                <Rect
                  x={drawRect.x}
                  y={drawRect.y}
                  width={drawRect.w}
                  height={drawRect.h}
                  stroke="#1e8cff"
                  strokeWidth={1.5}
                  dash={[4, 3]}
                  fill="rgba(30,140,255,0.08)"
                  listening={false}
                />
              )}
            </Layer>
          </Stage>
        </div>
      </div>

      {/* sidebar */}
      <div className="w-52 shrink-0 border-l border-[hsl(var(--border))] flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              regions ({regions.length})
            </span>
            {isDirty && (
              <span className="text-[9px] text-[hsl(var(--accent2))]">
                unsaved
              </span>
            )}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {regions.length === 0 ? (
            <div className="px-3 py-6 text-center text-[11px] text-[hsl(var(--text-muted))]">
              no regions · drag on canvas to add
            </div>
          ) : (
            regions.map((r) => (
              <SidebarRow
                key={r.id}
                r={r}
                isSelected={r.id === selectedId}
                onSelect={() => setSelectedId(r.id)}
                onDelete={() => deleteRegion(r.id)}
                onLabelChange={(label) => changeLabel(r.id, label)}
              />
            ))
          )}
        </div>
        <div className="border-t border-[hsl(var(--border))] p-2">
          <p className="text-[9px] text-[hsl(var(--text-muted)/.5)] leading-relaxed">
            Click region to select.{"\n"}
            Drag handles to resize.{"\n"}
            Drag on empty space to add.{"\n"}
            Del key removes selected.
          </p>
        </div>
      </div>
    </div>
  );
}
