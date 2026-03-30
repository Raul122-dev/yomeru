import { useState, useCallback, useEffect } from "react";
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
import { X, GripVertical, Upload, ImageIcon } from "lucide-react";
import { cn } from "../lib/utils";

export interface SortableFile {
  id: string; // stable unique id
  file: File;
  preview: string; // object URL
}

// ── single thumbnail ──────────────────────────────────────────────────────────
function Thumbnail({
  item,
  index,
  onRemove,
  overlay = false,
}: {
  item: SortableFile;
  index: number;
  onRemove?: (id: string) => void;
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
        "group relative aspect-[3/4] overflow-hidden rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg-subtle))]",
        isDragging && "opacity-40 ring-2 ring-[hsl(var(--accent2))]",
        overlay &&
          "shadow-xl ring-2 ring-[hsl(var(--accent2))] rotate-1 cursor-grabbing",
      )}
    >
      {/* image */}
      <img
        src={item.preview}
        alt={item.file.name}
        className="h-full w-full object-cover"
        draggable={false}
      />

      {/* page number badge */}
      <div className="absolute left-1.5 top-1.5 flex h-5 min-w-5 items-center justify-center rounded bg-black/60 px-1 text-[10px] font-mono text-white">
        {String(index + 1).padStart(2, "0")}
      </div>

      {/* drag handle */}
      {!overlay && (
        <div
          {...attributes}
          {...listeners}
          className="absolute right-1.5 top-1.5 flex h-6 w-6 cursor-grab items-center justify-center rounded bg-black/60 text-white opacity-0 transition-opacity group-hover:opacity-100 active:cursor-grabbing"
        >
          <GripVertical size={12} />
        </div>
      )}

      {/* remove button */}
      {!overlay && onRemove && (
        <button
          onClick={() => onRemove(item.id)}
          className="absolute bottom-1.5 right-1.5 flex h-6 w-6 items-center justify-center rounded bg-black/60 text-white opacity-0 transition-opacity hover:bg-red-500/80 group-hover:opacity-100"
        >
          <X size={11} />
        </button>
      )}

      {/* filename tooltip on hover */}
      <div className="absolute inset-x-0 bottom-0 translate-y-full bg-black/80 px-1.5 py-1 text-[9px] text-white transition-transform group-hover:translate-y-0 truncate">
        {item.file.name}
      </div>
    </div>
  );
}

// ── drop zone ─────────────────────────────────────────────────────────────────
function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const [draggingOver, setDraggingOver] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDraggingOver(false);
    const files = Array.from(e.dataTransfer.files).filter((f) =>
      f.type.startsWith("image/"),
    );
    if (files.length) onFiles(files);
  };

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setDraggingOver(true);
      }}
      onDragLeave={() => setDraggingOver(false)}
      onDrop={handleDrop}
      className={cn(
        "flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed px-6 py-8 transition-colors",
        draggingOver
          ? "border-[hsl(var(--accent2))] bg-[hsl(var(--accent2)/.06)]"
          : "border-[hsl(var(--border-strong))] hover:border-[hsl(var(--accent2))] hover:bg-[hsl(var(--bg-subtle))]",
      )}
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[hsl(var(--bg-subtle))]">
        {draggingOver ? (
          <ImageIcon size={20} className="text-[hsl(var(--accent2))]" />
        ) : (
          <Upload size={20} className="text-[hsl(var(--text-muted))]" />
        )}
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-[hsl(var(--text))]">
          {draggingOver ? "drop images here" : "select or drop images"}
        </p>
        <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">
          jpg, png, webp · drag to reorder after selecting
        </p>
      </div>
      <input
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files) onFiles(Array.from(e.target.files));
        }}
      />
    </label>
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

  // revoke object URLs on unmount to avoid memory leaks
  useEffect(() => {
    return () => {
      items.forEach((i) => URL.revokeObjectURL(i.preview));
    };
  }, []);

  const addFiles = useCallback(
    (files: File[]) => {
      const newItems: SortableFile[] = files.map((file) => ({
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

  return (
    <div className="flex flex-col gap-3">
      <DropZone onFiles={addFiles} />

      {items.length > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-[hsl(var(--text-muted))]">
            <span>
              {items.length} image{items.length !== 1 ? "s" : ""} · drag to
              reorder
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
              <div className="grid grid-cols-[repeat(auto-fill,minmax(90px,1fr))] gap-2">
                {items.map((item, idx) => (
                  <Thumbnail
                    key={item.id}
                    item={item}
                    index={idx}
                    onRemove={removeItem}
                  />
                ))}
              </div>
            </SortableContext>

            {/* drag overlay — renders the dragged item above everything */}
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
        </>
      )}
    </div>
  );
}
