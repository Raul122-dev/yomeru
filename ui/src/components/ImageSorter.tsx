import { useState, useCallback, useEffect, useRef } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  rectSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { X, GripVertical, Plus, ZoomIn } from "lucide-react";
import { cn } from "../lib/utils";

export interface SortableFile {
  id: string;
  file: File;
  preview: string;
}

// ── image preview modal ───────────────────────────────────────────────────────
function PreviewModal({
  item,
  onClose,
}: {
  item: SortableFile;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] max-w-[90vw]"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={item.preview}
          alt={item.file.name}
          className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
        />
        <button
          onClick={onClose}
          className="absolute -right-2 -top-2 flex h-8 w-8 items-center justify-center rounded-full bg-black/80 text-white hover:bg-red-500 transition-colors"
        >
          <X size={14} />
        </button>
        <div className="absolute bottom-3 left-3 rounded bg-black/70 px-2 py-1 text-xs text-white">
          {item.file.name}
        </div>
      </div>
    </div>
  );
}

// ── single thumbnail ──────────────────────────────────────────────────────────
function Thumbnail({
  item,
  index,
  onRemove,
  onPreview,
  overlay = false,
}: {
  item: SortableFile;
  index: number;
  onRemove?: (id: string) => void;
  onPreview?: (item: SortableFile) => void;
  overlay?: boolean;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id, disabled: overlay });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group relative aspect-[3/4] overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]",
        isDragging && "opacity-40 ring-2 ring-[hsl(var(--accent2))]",
        overlay &&
          "shadow-xl ring-2 ring-[hsl(var(--accent2))] rotate-1 cursor-grabbing",
      )}
    >
      <img
        src={item.preview}
        alt={item.file.name}
        className="h-full w-full object-cover"
        draggable={false}
      />

      {/* page number badge */}
      <div className="absolute left-1.5 top-1.5 flex h-5 min-w-5 items-center justify-center rounded bg-black/70 px-1.5 text-[10px] font-mono text-white">
        {String(index + 1).padStart(2, "0")}
      </div>

      {/* overlay controls */}
      {!overlay && (
        <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/0 opacity-0 transition-all group-hover:bg-black/30 group-hover:opacity-100">
          {/* preview */}
          {onPreview && (
            <button
              onClick={() => onPreview(item)}
              className="flex h-7 w-7 items-center justify-center rounded-full bg-black/70 text-white hover:bg-[hsl(var(--accent2))] transition-colors"
            >
              <ZoomIn size={13} />
            </button>
          )}
          {/* drag handle */}
          <div
            {...attributes}
            {...listeners}
            className="flex h-7 w-7 cursor-grab items-center justify-center rounded-full bg-black/70 text-white hover:bg-white/30 active:cursor-grabbing transition-colors"
          >
            <GripVertical size={13} />
          </div>
          {/* remove */}
          {onRemove && (
            <button
              onClick={() => onRemove(item.id)}
              className="flex h-7 w-7 items-center justify-center rounded-full bg-black/70 text-white hover:bg-red-500 transition-colors"
            >
              <X size={13} />
            </button>
          )}
        </div>
      )}

      {/* filename */}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-1.5 py-1.5 pt-4 opacity-0 group-hover:opacity-100 transition-opacity">
        <p className="text-[9px] text-white truncate">{item.file.name}</p>
      </div>
    </div>
  );
}

// ── add more card ─────────────────────────────────────────────────────────────
function AddMoreCard({ onFiles }: { onFiles: (files: File[]) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <button
      onClick={() => inputRef.current?.click()}
      className="flex aspect-[3/4] flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-[hsl(var(--border-strong))] bg-[hsl(var(--bg-subtle))] transition-colors hover:border-[hsl(var(--accent2))] hover:bg-[hsl(var(--accent2)/.05)]"
    >
      <Plus size={20} className="text-[hsl(var(--text-muted))]" />
      <span className="text-[10px] text-[hsl(var(--text-muted))]">
        add pages
      </span>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files) onFiles(Array.from(e.target.files));
          e.target.value = "";
        }}
      />
    </button>
  );
}

// ── main component ────────────────────────────────────────────────────────────
interface ImageSorterProps {
  onChange: (files: File[]) => void;
}

let _idCounter = 0;
function makeId() {
  return `img-${++_idCounter}`;
}

export function ImageSorter({ onChange }: ImageSorterProps) {
  const [items, setItems] = useState<SortableFile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [preview, setPreview] = useState<SortableFile | null>(null);
  const [draggingOver, setDraggingOver] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      items.forEach((i) => URL.revokeObjectURL(i.preview));
    };
  }, []);

  const addFiles = useCallback(
    (files: File[]) => {
      const imageFiles = files.filter((f) => f.type.startsWith("image/"));
      if (!imageFiles.length) return;
      const newItems: SortableFile[] = imageFiles.map((file) => ({
        id: makeId(),
        file,
        preview: URL.createObjectURL(file),
      }));
      setItems((prev) => {
        const next = [...prev, ...newItems];
        onChange(next.map((i) => i.file));
        return next;
      });
    },
    [onChange],
  );

  const removeItem = useCallback(
    (id: string) => {
      setItems((prev) => {
        const item = prev.find((i) => i.id === id);
        if (item) URL.revokeObjectURL(item.preview);
        const next = prev.filter((i) => i.id !== id);
        onChange(next.map((i) => i.file));
        return next;
      });
    },
    [onChange],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const handleDragStart = (e: DragStartEvent) =>
    setActiveId(e.active.id as string);

  const handleDragEnd = (e: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setItems((prev) => {
      const oldIdx = prev.findIndex((i) => i.id === active.id);
      const newIdx = prev.findIndex((i) => i.id === over.id);
      const next = arrayMove(prev, oldIdx, newIdx);
      onChange(next.map((i) => i.file));
      return next;
    });
  };

  const activeItem = items.find((i) => i.id === activeId);

  // Container-level drop handling (works when images are already shown)
  const handleContainerDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDraggingOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) =>
      f.type.startsWith("image/"),
    );
    if (files.length) addFiles(files);
  };

  // Empty state — large drop zone
  if (items.length === 0) {
    return (
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDraggingOver(true);
        }}
        onDragLeave={() => setDraggingOver(false)}
        onDrop={handleContainerDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-12 transition-colors",
          draggingOver
            ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.06)]"
            : "border-[hsl(var(--border-strong))] hover:border-[hsl(var(--accent2))] hover:bg-[hsl(var(--bg-subtle))]",
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--bg-subtle))]">
          <Plus size={22} className="text-[hsl(var(--text-muted))]" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-[hsl(var(--text))]">
            Select or drop manga pages
          </p>
          <p className="mt-1 text-xs text-[hsl(var(--text-muted))]">
            JPG, PNG, WebP · drag to reorder after adding
          </p>
        </div>
        <input
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(Array.from(e.target.files));
          }}
        />
      </label>
    );
  }

  return (
    <div
      ref={containerRef}
      onDragOver={(e) => {
        e.preventDefault();
        setDraggingOver(true);
      }}
      onDragLeave={(e) => {
        if (containerRef.current && !containerRef.current.contains(e.relatedTarget as Node)) {
          setDraggingOver(false);
        }
      }}
      onDrop={handleContainerDrop}
      className={cn(
        "rounded-lg border-2 border-dashed p-3 transition-colors",
        draggingOver
          ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.04)]"
          : "border-transparent",
      )}
    >
      {/* header */}
      <div className="mb-2 flex items-center justify-between text-xs text-[hsl(var(--text-muted))]">
        <span>
          {items.length} page{items.length !== 1 ? "s" : ""} · drag to reorder
        </span>
        <button
          onClick={() => {
            items.forEach((i) => URL.revokeObjectURL(i.preview));
            setItems([]);
            onChange([]);
          }}
          className="hover:text-[hsl(var(--danger))] transition-colors"
        >
          clear all
        </button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={items.map((i) => i.id)}
          strategy={rectSortingStrategy}
        >
          <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2.5">
            {items.map((item, idx) => (
              <Thumbnail
                key={item.id}
                item={item}
                index={idx}
                onRemove={removeItem}
                onPreview={setPreview}
              />
            ))}
            <AddMoreCard onFiles={addFiles} />
          </div>
        </SortableContext>

        <DragOverlay adjustScale={false}>
          {activeItem && (
            <Thumbnail
              item={activeItem}
              index={items.findIndex((i) => i.id === activeId)}
              overlay
            />
          )}
        </DragOverlay>
      </DndContext>

      {/* preview modal */}
      {preview && (
        <PreviewModal item={preview} onClose={() => setPreview(null)} />
      )}
    </div>
  );
}
