/**
 * DetectionEditor — interactive editor for S1 detected regions.
 *
 * Features:
 *  - View detected regions as colored boxes over the page image
 *  - Click to select → handles appear for resize/move
 *  - Delete key or trash button to remove a region
 *  - Drag on empty canvas to draw a new region
 *  - Change label of selected region
 *  - Zoom with mouse wheel or +/- buttons
 *  - Undo/Redo (Ctrl+Z / Ctrl+Shift+Z)
 *  - Page navigation bar with thumbnails
 *  - Legend explaining colors, labels, and confidence score
 *  - Centered image in canvas area
 *  - Save refined → PUT /runs/{id}/detections/{page}
 *  - Revert all → DELETE /runs/{id}/detections/{page}/refined
 *
 * Coordinate system:
 *   All Konva coords are in *display* space (scaled to fit container).
 *   Original image coords = display_coords / scale.
 *   Saved regions always use original image coordinates.
 *
 * Keyboard shortcuts:
 *   Del/Backspace — delete selected region
 *   Ctrl+Z — undo last action
 *   Ctrl+Shift+Z / Ctrl+Y — redo
 *   Escape — deselect or close editor
 *   +/= — zoom in
 *   - — zoom out
 *   0 — reset zoom
 *   ←/→ — previous/next page
 *   N — add new region (enters draw mode)
 */
import { useRef, useState, useEffect, useCallback, useMemo } from "react";
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
import {
  Trash2,
  RotateCcw,
  Save,
  X,
  ChevronDown,
  ZoomIn,
  ZoomOut,
  Maximize2,
  MousePointer2,
  Square,
  Undo2,
  Redo2,
  Info,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
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
  kx: number;
  ky: number;
  kw: number;
  kh: number;
}

interface PageDetection {
  page_number: number;
  original_w: number;
  original_h: number;
  regions: Region[];
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

const LABEL_DESCRIPTIONS: Record<string, string> = {
  bubble: "Speech/thought bubble",
  text_bubble: "Text inside bubble",
  text_free: "Free-floating text",
  sfx: "Sound effect",
  caption: "Narration/caption box",
};

const ZOOM_STEP = 0.15;
const ZOOM_MIN = 0.3;
const ZOOM_MAX = 5.0;

function regionColor(label: string) {
  return LABEL_COLORS[label] ?? DEFAULT_COLOR;
}

function toRgba(color: string, alpha: number) {
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

let _nextId = 10000;

// ── undo/redo history ─────────────────────────────────────────────────────────

interface HistoryState {
  regions: Region[];
}

function useHistory(initial: Region[]) {
  const [past, setPast] = useState<HistoryState[]>([]);
  const [present, setPresent] = useState<HistoryState>({ regions: initial });
  const [future, setFuture] = useState<HistoryState[]>([]);

  const push = useCallback((regions: Region[]) => {
    setPresent((prev) => {
      setPast((p) => [...p.slice(-50), prev]);
      setFuture([]);
      return { regions };
    });
  }, []);

  const undo = useCallback(() => {
    setPast((p) => {
      if (p.length === 0) return p;
      const prev = p[p.length - 1];
      setFuture((f) => [present, ...f]);
      setPresent(prev);
      return p.slice(0, -1);
    });
  }, [present]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (f.length === 0) return f;
      const next = f[0];
      setPast((p) => [...p, present]);
      setPresent(next);
      return f.slice(1);
    });
  }, [present]);

  const reset = useCallback((regions: Region[]) => {
    setPast([]);
    setFuture([]);
    setPresent({ regions });
  }, []);

  return {
    regions: present.regions,
    push,
    undo,
    redo,
    reset,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
  };
}

// ── sub-components ────────────────────────────────────────────────────────────

function RegionShape({
  r,
  isSelected,
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
      fill={toRgba(color, isSelected ? 0.25 : 0.12)}
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
  const badgeH = 16;
  const text = `${r.id}`;
  const textW = text.length * 7 + 8;
  return (
    <>
      <Rect
        x={r.kx}
        y={r.ky - badgeH}
        width={textW}
        height={badgeH}
        fill={color}
        cornerRadius={[4, 4, 0, 0]}
        listening={false}
      />
      <Text
        x={r.kx + 4}
        y={r.ky - badgeH + 2}
        text={text}
        fontSize={10}
        fontStyle="bold"
        fill="white"
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
          ? "bg-[hsl(var(--accent2)/.08)] border-l-2 border-l-[hsl(var(--accent2))]"
          : "hover:bg-[hsl(var(--bg-subtle))]",
      )}
    >
      <div className="mt-0.5 flex items-center gap-1.5 shrink-0">
        <div
          className="h-2.5 w-2.5 rounded-full"
          style={{ background: color }}
        />
        <span className="font-mono text-[hsl(var(--text-muted))] w-5">
          {r.id}
        </span>
      </div>

      <div className="flex-1 min-w-0">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setShowLabels((v) => !v);
          }}
          className="flex items-center gap-1 text-[hsl(var(--text))] hover:text-[hsl(var(--accent2))] transition-colors"
        >
          <span className="capitalize">{r.label.replace(/_/g, " ")}</span>
          <ChevronDown size={9} />
        </button>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className="text-[hsl(var(--text-muted)/.6)] font-mono text-[10px]">
            {w}×{h}
          </span>
          {r.isNew && (
            <span className="text-[9px] px-1 rounded bg-[hsl(var(--accent2)/.1)] text-[hsl(var(--accent2))]">
              new
            </span>
          )}
          {r.score < 1 && !r.isNew && (
            <span className="text-[10px] text-[hsl(var(--text-muted)/.6)] font-mono">
              {(r.score * 100).toFixed(0)}%
            </span>
          )}
        </div>

        {showLabels && (
          <div className="absolute left-8 top-full mt-1 rounded border border-[hsl(var(--border))] bg-[hsl(var(--bg))] shadow-lg z-20 overflow-hidden">
            {LABELS.map((l) => (
              <button
                key={l}
                onClick={(e) => {
                  e.stopPropagation();
                  onLabelChange(l);
                  setShowLabels(false);
                }}
                className={cn(
                  "flex items-center gap-2 w-full px-3 py-1.5 text-left text-[10px] hover:bg-[hsl(var(--bg-subtle))] transition-colors",
                  l === r.label && "text-[hsl(var(--accent2))] font-medium",
                )}
              >
                <div
                  className="h-2 w-2 rounded-full"
                  style={{ background: LABEL_COLORS[l] ?? DEFAULT_COLOR }}
                />
                <span className="capitalize">{l.replace(/_/g, " ")}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="mt-0.5 shrink-0 text-[hsl(var(--text-muted)/.4)] hover:text-[hsl(var(--danger))] transition-colors"
      >
        <Trash2 size={11} />
      </button>
    </div>
  );
}

// ── legend panel ──────────────────────────────────────────────────────────────

function Legend({ show, onClose }: { show: boolean; onClose: () => void }) {
  if (!show) return null;
  return (
    <div className="absolute top-12 left-3 z-30 w-56 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg))] shadow-xl p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">Legend</span>
        <button onClick={onClose} className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]">
          <X size={12} />
        </button>
      </div>
      <div className="space-y-1.5">
        {LABELS.map((l) => (
          <div key={l} className="flex items-center gap-2 text-[11px]">
            <div
              className="h-3 w-3 rounded-sm border"
              style={{
                background: toRgba(LABEL_COLORS[l] ?? DEFAULT_COLOR, 0.2),
                borderColor: LABEL_COLORS[l] ?? DEFAULT_COLOR,
              }}
            />
            <span className="capitalize font-medium">{l.replace(/_/g, " ")}</span>
            <span className="text-[hsl(var(--text-muted)/.6)] text-[10px]">
              — {LABEL_DESCRIPTIONS[l]}
            </span>
          </div>
        ))}
      </div>
      <div className="border-t border-[hsl(var(--border))] pt-2 space-y-1 text-[10px] text-[hsl(var(--text-muted))]">
        <p><strong>Score %</strong> — Model confidence in the detection accuracy</p>
        <p><strong>Dimensions</strong> — Width × Height in original pixels</p>
      </div>
      <div className="border-t border-[hsl(var(--border))] pt-2 space-y-0.5 text-[10px] text-[hsl(var(--text-muted))]">
        <p className="font-medium text-[hsl(var(--text))]">Shortcuts</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">Del</kbd> Delete region</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">Ctrl+Z</kbd> Undo</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">Ctrl+Shift+Z</kbd> Redo</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">+/-</kbd> Zoom in/out</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">0</kbd> Reset zoom</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">←/→</kbd> Prev/Next page</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">N</kbd> Draw new region</p>
        <p><kbd className="px-1 rounded bg-[hsl(var(--bg-subtle))] border border-[hsl(var(--border))]">Esc</kbd> Deselect / Close</p>
      </div>
    </div>
  );
}

// ── page thumbnail for bottom bar ─────────────────────────────────────────────

function PageThumb({
  runId,
  page,
  isCurrent,
  hasDetections,
  onClick,
}: {
  runId: string;
  page: { page: number; filename: string };
  isCurrent: boolean;
  hasDetections: boolean;
  onClick: () => void;
}) {
  const url = pageImageUrl(runId, page.filename);
  return (
    <button
      onClick={onClick}
      className={cn(
        "relative shrink-0 h-16 w-12 rounded border-2 overflow-hidden transition-all hover:border-[hsl(var(--accent2)/.6)]",
        isCurrent
          ? "border-[hsl(var(--accent2))] ring-1 ring-[hsl(var(--accent2)/.3)]"
          : "border-[hsl(var(--border))]",
        !hasDetections && "opacity-40",
      )}
    >
      <img src={url} alt={`Page ${page.page}`} className="h-full w-full object-cover" />
      <span className={cn(
        "absolute bottom-0 inset-x-0 text-center text-[9px] font-mono py-0.5",
        isCurrent ? "bg-[hsl(var(--accent2))] text-white" : "bg-[hsl(var(--bg)/.85)] text-[hsl(var(--text-muted))]",
      )}>
        {page.page}
      </span>
    </button>
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
  allPages?: { page: number; filename: string }[];
  allDetections?: Record<number, PageDetection>;
  onClose: () => void;
  onNavigate?: (page: number) => void;
  onSaved: () => void;
}

export function DetectionEditor({
  runId,
  pageNum,
  filename,
  initialRegions,
  originalW,
  originalH,
  allPages = [],
  allDetections = {},
  onClose,
  onNavigate,
  onSaved,
}: DetectionEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const trRef = useRef<Konva.Transformer>(null);

  const imgUrl = pageImageUrl(runId, filename);
  const [bgImage] = useImage(imgUrl, "anonymous");

  // Dimensions
  const imgW = originalW || bgImage?.naturalWidth || bgImage?.width || 600;
  const imgH = originalH || bgImage?.naturalHeight || bgImage?.height || 600;

  // Container size
  const [containerSize, setContainerSize] = useState({ w: 800, h: 600 });
  useEffect(() => {
    if (!containerRef.current) return;
    const ob = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setContainerSize({ w: width, h: height });
    });
    ob.observe(containerRef.current);
    return () => ob.disconnect();
  }, []);

  // Zoom
  const [zoom, setZoom] = useState(1.0);

  // Base scale to fit image in container
  const baseScale = useMemo(() => {
    const scaleW = (containerSize.w - 32) / imgW;
    const scaleH = (containerSize.h - 32) / imgH;
    return Math.min(scaleW, scaleH, 1);
  }, [containerSize, imgW, imgH]);

  const scale = baseScale * zoom;
  const dispW = imgW * scale;
  const dispH = imgH * scale;

  // Centering offset
  const offsetX = Math.max(0, (containerSize.w - dispW) / 2);
  const offsetY = Math.max(0, (containerSize.h - dispH) / 2);

  // Region state with undo/redo
  const { regions, push, undo, redo, reset, canUndo, canRedo } = useHistory(initialRegions);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showLegend, setShowLegend] = useState(false);

  // Reset state when navigating to a different page
  const prevPageRef = useRef(pageNum);
  useEffect(() => {
    if (prevPageRef.current !== pageNum) {
      prevPageRef.current = pageNum;
      reset(initialRegions);
      setSelectedId(null);
      setZoom(1.0);
      setSaveError(null);
    }
  }, [pageNum, initialRegions, reset]);

  // Tool mode
  const [tool, setTool] = useState<"select" | "draw">("select");

  // Drawing state
  const [drawing, setDrawing] = useState<{ x: number; y: number } | null>(null);
  const [drawRect, setDrawRect] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);

  // Is dirty — compare with initial
  const isDirty = useMemo(() => {
    if (regions.length !== initialRegions.length) return true;
    return regions.some((r, i) => {
      const orig = initialRegions[i];
      return (
        !orig ||
        r.id !== orig.id ||
        r.x1 !== orig.x1 ||
        r.y1 !== orig.y1 ||
        r.x2 !== orig.x2 ||
        r.y2 !== orig.y2 ||
        r.label !== orig.label
      );
    });
  }, [regions, initialRegions]);

  // Convert to konva coords
  const toKonva = useCallback(
    (r: Region): KonvaRegion => ({
      ...r,
      kx: r.x1 * scale,
      ky: r.y1 * scale,
      kw: (r.x2 - r.x1) * scale,
      kh: (r.y2 - r.y1) * scale,
    }),
    [scale],
  );

  const kRegions = useMemo(() => regions.map(toKonva), [regions, toKonva]);

  // Deselect on scale change
  useEffect(() => {
    setSelectedId(null);
  }, [scale]);

  // Transformer update
  useEffect(() => {
    if (!trRef.current || !stageRef.current) return;
    if (selectedId === null) {
      trRef.current.nodes([]);
      return;
    }
    const node = stageRef.current.findOne(`#${selectedId}`);
    if (node) trRef.current.nodes([node]);
    else trRef.current.nodes([]);
  }, [selectedId, regions, scale]);

  // ── Zoom handlers ───────────────────────────────────────────────────────────

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(z + ZOOM_STEP, ZOOM_MAX));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(z - ZOOM_STEP, ZOOM_MIN));
  }, []);

  const zoomReset = useCallback(() => {
    setZoom(1.0);
  }, []);

  // Mouse wheel zoom on canvas
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
      setZoom((z) => Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z + delta)));
    }
  }, []);

  // ── Keyboard shortcuts ──────────────────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      // Delete selected
      if ((e.key === "Delete" || e.key === "Backspace") && selectedId !== null) {
        e.preventDefault();
        const newRegions = regions.filter((r) => r.id !== selectedId);
        push(newRegions);
        setSelectedId(null);
        return;
      }

      // Undo
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
        return;
      }

      // Redo
      if ((e.ctrlKey || e.metaKey) && (e.key === "Z" || e.key === "y")) {
        e.preventDefault();
        redo();
        return;
      }

      // Escape
      if (e.key === "Escape") {
        if (selectedId !== null) {
          setSelectedId(null);
        } else {
          onClose();
        }
        return;
      }

      // Zoom
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        zoomIn();
        return;
      }
      if (e.key === "-") {
        e.preventDefault();
        zoomOut();
        return;
      }
      if (e.key === "0") {
        e.preventDefault();
        zoomReset();
        return;
      }

      // Page nav
      if (e.key === "ArrowLeft" && !e.ctrlKey) {
        e.preventDefault();
        navigatePrev();
        return;
      }
      if (e.key === "ArrowRight" && !e.ctrlKey) {
        e.preventDefault();
        navigateNext();
        return;
      }

      // New region mode
      if (e.key === "n" || e.key === "N") {
        setTool("draw");
        return;
      }

      // Select mode
      if (e.key === "v" || e.key === "V") {
        setTool("select");
        return;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedId, regions, push, undo, redo, onClose, zoomIn, zoomOut, zoomReset]);

  // ── Page navigation ─────────────────────────────────────────────────────────

  const currentPageIndex = allPages.findIndex((p) => p.page === pageNum);

  const navigatePrev = useCallback(() => {
    if (currentPageIndex <= 0 || !onNavigate) return;
    const prev = allPages[currentPageIndex - 1];
    if (prev && allDetections[prev.page]) onNavigate(prev.page);
  }, [currentPageIndex, allPages, allDetections, onNavigate]);

  const navigateNext = useCallback(() => {
    if (currentPageIndex >= allPages.length - 1 || !onNavigate) return;
    const next = allPages[currentPageIndex + 1];
    if (next && allDetections[next.page]) onNavigate(next.page);
  }, [currentPageIndex, allPages, allDetections, onNavigate]);

  // ── Stage mouse handlers ────────────────────────────────────────────────────

  const onStageMouseDown = useCallback(
    (e: Konva.KonvaEventObject<MouseEvent>) => {
      if (e.target !== stageRef.current && e.target.id() !== "bg") {
        return;
      }
      setSelectedId(null);
      if (tool === "draw") {
        const pos = stageRef.current!.getPointerPosition()!;
        setDrawing({ x: pos.x, y: pos.y });
        setDrawRect({ x: pos.x, y: pos.y, w: 0, h: 0 });
      }
    },
    [tool],
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
    push([...regions, newRegion]);
    setSelectedId(newId);
    setDrawing(null);
    setDrawRect(null);
    setTool("select");
  }, [drawRect, scale, regions, push]);

  // ── Region mutations ────────────────────────────────────────────────────────

  const onDragEnd = useCallback(
    (id: number, kx: number, ky: number) => {
      const updated = regions.map((r) => {
        if (r.id !== id) return r;
        const w = r.x2 - r.x1,
          h = r.y2 - r.y1;
        const nx1 = Math.round(kx / scale),
          ny1 = Math.round(ky / scale);
        return { ...r, x1: nx1, y1: ny1, x2: nx1 + w, y2: ny1 + h };
      });
      push(updated);
    },
    [scale, regions, push],
  );

  const onTransformEnd = useCallback(
    (id: number, node: Konva.Node) => {
      const sx = node.scaleX(),
        sy = node.scaleY();
      node.scaleX(1);
      node.scaleY(1);
      const updated = regions.map((r) => {
        if (r.id !== id) return r;
        const nx1 = Math.round(node.x() / scale);
        const ny1 = Math.round(node.y() / scale);
        const nw = Math.round((node.width() * sx) / scale);
        const nh = Math.round((node.height() * sy) / scale);
        return { ...r, x1: nx1, y1: ny1, x2: nx1 + nw, y2: ny1 + nh };
      });
      push(updated);
    },
    [scale, regions, push],
  );

  const deleteRegion = (id: number) => {
    push(regions.filter((r) => r.id !== id));
    if (selectedId === id) setSelectedId(null);
  };

  const changeLabel = (id: number, label: string) => {
    push(regions.map((r) => (r.id === id ? { ...r, label } : r)));
  };

  // ── Save / revert ─────────────────────────────────────────────────────────

  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await savePageDetections(runId, pageNum, {
        regions: regions.map(({ id, x1, y1, x2, y2, label, score }) => ({
          id, x1, y1, x2, y2, label, score,
        })),
        original_w: imgW,
        original_h: imgH,
      });
      onSaved();
    } catch (e: unknown) {
      setSaveError(String(e));
    } finally {
      setIsSaving(false);
    }
  };

  const handleRevert = async () => {
    await revertPageDetections(runId, pageNum);
    reset(initialRegions);
    setSelectedId(null);
    onSaved();
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[hsl(var(--bg))] overflow-hidden">
      {/* Top toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] shrink-0">
        {/* Left: page info */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-[hsl(var(--text-muted))]">
            Page {pageNum}
          </span>
          <span className="text-[11px] text-[hsl(var(--text-muted)/.5)] truncate max-w-[150px]">
            {filename}
          </span>
        </div>

        {/* Center: toolbox */}
        <div className="flex-1 flex items-center justify-center gap-1">
          {/* Tool select/draw */}
          <div className="flex items-center rounded border border-[hsl(var(--border))] overflow-hidden">
            <button
              onClick={() => setTool("select")}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1.5 text-[11px] transition-colors",
                tool === "select"
                  ? "bg-[hsl(var(--accent2)/.1)] text-[hsl(var(--accent2))]"
                  : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))]",
              )}
              title="Select tool (V)"
            >
              <MousePointer2 size={12} /> Select
            </button>
            <button
              onClick={() => setTool("draw")}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1.5 text-[11px] border-l border-[hsl(var(--border))] transition-colors",
                tool === "draw"
                  ? "bg-[hsl(var(--accent2)/.1)] text-[hsl(var(--accent2))]"
                  : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))]",
              )}
              title="Draw new region (N)"
            >
              <Square size={12} /> Draw
            </button>
          </div>

          <div className="w-px h-5 bg-[hsl(var(--border))] mx-1" />

          {/* Undo/Redo */}
          <button
            onClick={undo}
            disabled={!canUndo}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] disabled:opacity-30 transition-colors"
            title="Undo (Ctrl+Z)"
          >
            <Undo2 size={14} />
          </button>
          <button
            onClick={redo}
            disabled={!canRedo}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] disabled:opacity-30 transition-colors"
            title="Redo (Ctrl+Shift+Z)"
          >
            <Redo2 size={14} />
          </button>

          <div className="w-px h-5 bg-[hsl(var(--border))] mx-1" />

          {/* Zoom */}
          <button
            onClick={zoomOut}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] transition-colors"
            title="Zoom out (-)"
          >
            <ZoomOut size={14} />
          </button>
          <span className="text-[11px] font-mono text-[hsl(var(--text-muted))] w-12 text-center">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={zoomIn}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] transition-colors"
            title="Zoom in (+)"
          >
            <ZoomIn size={14} />
          </button>
          <button
            onClick={zoomReset}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))] transition-colors"
            title="Reset zoom (0)"
          >
            <Maximize2 size={13} />
          </button>

          <div className="w-px h-5 bg-[hsl(var(--border))] mx-1" />

          {/* Delete selected */}
          <button
            onClick={() => selectedId !== null && deleteRegion(selectedId)}
            disabled={selectedId === null}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:text-[hsl(var(--danger))] hover:bg-[hsl(var(--danger)/.05)] disabled:opacity-30 transition-colors"
            title="Delete selected (Del)"
          >
            <Trash2 size={14} />
          </button>

          {/* Legend toggle */}
          <button
            onClick={() => setShowLegend((v) => !v)}
            className={cn(
              "p-1.5 rounded transition-colors",
              showLegend
                ? "text-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.08)]"
                : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg-subtle))]",
            )}
            title="Show legend"
          >
            <Info size={14} />
          </button>
        </div>

        {/* Right: save/revert/close */}
        <div className="flex items-center gap-2">
          {saveError && (
            <span className="text-[10px] text-[hsl(var(--danger))] max-w-[120px] truncate">
              {saveError}
            </span>
          )}
          <button
            onClick={handleRevert}
            className="flex items-center gap-1 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--border-strong))] transition-colors"
            title="Revert all changes"
          >
            <RotateCcw size={10} /> Revert
          </button>
          <button
            onClick={handleSave}
            disabled={!isDirty || isSaving}
            className="flex items-center gap-1 rounded border border-[hsl(var(--accent2)/.4)] px-2.5 py-1 text-[11px] text-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.08)] disabled:opacity-40 transition-colors"
            title="Save changes"
          >
            <Save size={10} /> {isSaving ? "Saving…" : "Save"}
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] hover:bg-[hsl(var(--bg-subtle))] transition-colors"
            title="Close editor (Esc)"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Canvas area */}
        <div className="flex-1 min-w-0 relative flex flex-col">
          <Legend show={showLegend} onClose={() => setShowLegend(false)} />

          <div
            ref={containerRef}
            className="flex-1 overflow-auto"
            onWheel={onWheel}
          >
            {/* Center the stage */}
            <div
              className="flex items-center justify-center min-h-full min-w-full"
              style={{
                paddingTop: Math.max(offsetY, 16),
                paddingBottom: Math.max(offsetY, 16),
                paddingLeft: Math.max(offsetX, 16),
                paddingRight: Math.max(offsetX, 16),
              }}
            >
              <Stage
                ref={stageRef}
                width={dispW}
                height={dispH}
                onMouseDown={onStageMouseDown}
                onMouseMove={onStageMouseMove}
                onMouseUp={onStageMouseUp}
                style={{
                  cursor: tool === "draw" ? "crosshair" : drawing ? "crosshair" : "default",
                  borderRadius: "4px",
                  boxShadow: "0 2px 16px rgba(0,0,0,0.2)",
                }}
              >
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

                <Layer key={`${scale}-${regions.length}`}>
                  {kRegions.map((r) => (
                    <RegionShape
                      key={r.id}
                      r={r}
                      isSelected={r.id === selectedId}
                      scale={scale}
                      onClick={() => {
                        setSelectedId(r.id);
                        setTool("select");
                      }}
                      onDragEnd={onDragEnd}
                      onTransformEnd={onTransformEnd}
                    />
                  ))}
                  {kRegions.map((r) => (
                    <RegionLabel key={`lbl-${r.id}`} r={r} />
                  ))}
                  <Transformer
                    ref={trRef}
                    boundBoxFunc={(_, _new) => ({
                      ..._new,
                      width: Math.max(10, _new.width),
                      height: Math.max(10, _new.height),
                    })}
                    rotateEnabled={false}
                    keepRatio={false}
                  />
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
        </div>

        {/* Sidebar */}
        <div className="w-56 shrink-0 border-l border-[hsl(var(--border))] flex flex-col overflow-hidden bg-[hsl(var(--bg))]">
          <div className="px-3 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                Regions ({regions.length})
              </span>
              {isDirty && (
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-[hsl(var(--accent2)/.1)] text-[hsl(var(--accent2))]">
                  unsaved
                </span>
              )}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {regions.length === 0 ? (
              <div className="px-3 py-8 text-center text-[11px] text-[hsl(var(--text-muted))]">
                No regions detected.
                <br />
                <span className="text-[10px]">Use Draw tool (N) to add regions.</span>
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
        </div>
      </div>

      {/* Bottom page navigation bar */}
      {allPages.length > 1 && (
        <div className="shrink-0 border-t border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))] px-4 py-2">
          <div className="flex items-center gap-2">
            <button
              onClick={navigatePrev}
              disabled={currentPageIndex <= 0}
              className="p-1 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg))] disabled:opacity-30 transition-colors"
            >
              <ChevronLeft size={14} />
            </button>
            <div className="flex-1 flex items-center gap-1.5 overflow-x-auto py-1 scrollbar-thin">
              {allPages.map((page) => (
                <PageThumb
                  key={page.page}
                  runId={runId}
                  page={page}
                  isCurrent={page.page === pageNum}
                  hasDetections={!!allDetections[page.page]}
                  onClick={() => {
                    if (page.page !== pageNum && allDetections[page.page] && onNavigate) {
                      onNavigate(page.page);
                    }
                  }}
                />
              ))}
            </div>
            <button
              onClick={navigateNext}
              disabled={currentPageIndex >= allPages.length - 1}
              className="p-1 rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--bg))] disabled:opacity-30 transition-colors"
            >
              <ChevronRight size={14} />
            </button>
            <span className="text-[10px] text-[hsl(var(--text-muted))] ml-2 shrink-0">
              {currentPageIndex + 1} / {allPages.length}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
