import { useCallback, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  type Node,
  type Edge,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { cn } from "../../lib/utils";
import { pageImageUrl } from "../../lib/api";

// ── types ─────────────────────────────────────────────────────────────────────
export type PageStatus = "pending" | "processing" | "done" | "error";

export interface PageNodeData extends Record<string, unknown> {
  runId: string;
  pageNumber: number;
  filename: string;
  status: PageStatus;
  mood?: string;
  dialogues?: number;
  characters?: number;
  summary?: string;
  error?: string;
  tokenBuffer?: string;
  onSelect: (page: number, filename: string) => void;
}

// ── node component ────────────────────────────────────────────────────────────
function PageNode({ data }: { data: PageNodeData }) {
  const {
    runId,
    pageNumber,
    filename,
    status,
    mood,
    dialogues,
    characters,
    summary,
    error,
    tokenBuffer,
    onSelect,
  } = data;

  return (
    <div
      onClick={() => {
        if (status === "done" || status === "error")
          onSelect(pageNumber, filename);
      }}
      className={cn(
        "w-48 rounded-lg border overflow-hidden transition-all duration-300 select-none",
        status === "pending" &&
          "border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] opacity-40",
        status === "processing" &&
          "border-[hsl(var(--accent2))] bg-[hsl(var(--bg-surface))] shadow-[0_0_16px_hsl(var(--accent2)/.4)]",
        status === "done" &&
          "border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] cursor-pointer hover:border-[hsl(var(--accent2))] hover:shadow-sm",
        status === "error" &&
          "border-[hsl(var(--danger))] bg-[hsl(var(--bg-surface))] cursor-pointer",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{
          background: "hsl(var(--border))",
          border: "none",
          width: 8,
          height: 8,
        }}
      />

      {/* thumbnail */}
      <div className="relative h-28 w-full bg-[hsl(var(--bg-subtle))]">
        {(status === "done" || status === "processing" || status === "error") &&
          filename && (
            <img
              src={pageImageUrl(runId, filename)}
              alt={`page ${pageNumber}`}
              className={cn(
                "h-full w-full object-cover",
                status !== "done" && "opacity-60",
              )}
              draggable={false}
            />
          )}
        {status === "pending" && (
          <div className="flex h-full items-center justify-center text-xs text-[hsl(var(--text-muted))]">
            {filename || `page ${pageNumber}`}
          </div>
        )}

        {/* page badge */}
        <div className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">
          {String(pageNumber).padStart(2, "0")}
        </div>

        {/* processing spinner */}
        {status === "processing" && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-[hsl(var(--accent2))] border-t-transparent" />
          </div>
        )}

        {/* error overlay */}
        {status === "error" && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40">
            <span className="text-xl">✗</span>
          </div>
        )}
      </div>

      {/* info */}
      <div className="p-2">
        {status === "processing" && (
          <div className="font-mono text-[9px] leading-relaxed text-[hsl(var(--accent2))]">
            {tokenBuffer ? (
              <>
                <span className="opacity-70">{tokenBuffer.slice(-120)}</span>
                <span className="animate-pulse">▊</span>
              </>
            ) : (
              <span className="animate-pulse">analyzing…</span>
            )}
          </div>
        )}
        {status === "done" && (
          <div className="space-y-0.5">
            {mood && (
              <p className="text-[10px] font-medium text-[hsl(var(--accent2))]">
                {mood}
              </p>
            )}
            {summary && (
              <p className="line-clamp-2 text-[9px] leading-relaxed text-[hsl(var(--text-muted))]">
                {summary}
              </p>
            )}
            <div className="flex gap-2 pt-0.5 text-[9px] text-[hsl(var(--text-muted))]">
              {dialogues !== undefined && <span>{dialogues} dialogues</span>}
              {characters !== undefined && <span>· {characters} chars</span>}
            </div>
          </div>
        )}
        {status === "error" && (
          <p className="text-[9px] text-[hsl(var(--danger))] line-clamp-2">
            {error || "failed"}
          </p>
        )}
        {status === "pending" && (
          <p className="text-[9px] text-[hsl(var(--text-muted))]">waiting…</p>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{
          background: "hsl(var(--border))",
          border: "none",
          width: 8,
          height: 8,
        }}
      />
    </div>
  );
}

const NODE_TYPES = { page: PageNode };

// ── layout ────────────────────────────────────────────────────────────────────
const W = 192,
  H = 172,
  GAP_X = 56,
  GAP_Y = 48,
  COLS = 4;

function makeNodes(
  pages: { page: number; filename: string }[],
  runId: string,
  onSelect: (p: number, f: string) => void,
  analysesMap: Map<number, Record<string, unknown>>,
): Node[] {
  return pages.map(({ page, filename }) => {
    const col = (page - 1) % COLS;
    const row = Math.floor((page - 1) / COLS);
    const analysis = analysesMap.get(page);
    const hasData = !!analysis;

    return {
      id: `p${page}`,
      type: "page",
      position: { x: col * (W + GAP_X), y: row * (H + GAP_Y) },
      data: {
        runId,
        pageNumber: page,
        filename,
        status: hasData ? "done" : "pending",
        mood: hasData
          ? String(
              (analysis?.scene &&
                (analysis.scene as Record<string, unknown>).mood) ||
                "",
            )
          : undefined,
        dialogues: hasData
          ? ((analysis?.dialogues as unknown[])?.length ?? 0)
          : undefined,
        characters: hasData
          ? ((analysis?.characters_seen as unknown[])?.length ?? 0)
          : undefined,
        summary: hasData ? String(analysis?.page_summary || "") : undefined,
        onSelect,
      } as PageNodeData,
    };
  });
}

function makeEdges(pages: { page: number }[], activePage?: number): Edge[] {
  return pages.slice(0, -1).map(({ page }) => ({
    id: `e${page}`,
    source: `p${page}`,
    target: `p${page + 1}`,
    animated: page === activePage,
    style: {
      stroke:
        page < (activePage ?? 0)
          ? "hsl(var(--accent2))"
          : "hsl(var(--border-strong))",
      strokeWidth: 1.5,
    },
  }));
}

// ── main component ────────────────────────────────────────────────────────────
export interface FlowDiagramProps {
  runId: string;
  pages: { page: number; filename: string }[]; // from GET /runs/:id/pages
  analyses: Record<string, unknown>[]; // from GET /runs/:id/analyses (may be partial)
  events: Record<string, unknown>[]; // live WebSocket events
  onPageSelect: (page: number, filename: string) => void;
}

export function FlowDiagram({
  runId,
  pages,
  analyses,
  events,
  onPageSelect,
}: FlowDiagramProps) {
  const analysesMap = useMemo(
    () =>
      new Map(
        analyses.map((a) => [(a as { page_number: number }).page_number, a]),
      ),
    [analyses],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // initialize / reinitialize when pages or analyses change
  useEffect(() => {
    if (pages.length === 0) return;
    setNodes(makeNodes(pages, runId, onPageSelect, analysesMap));
    setEdges(makeEdges(pages));
  }, [pages, analysesMap]);

  // apply live events
  useEffect(() => {
    if (events.length === 0) return;
    const ev = events[events.length - 1];
    const type = ev.type as string;
    const page = ev.page as number | undefined;
    if (!page) return;

    setNodes((prev) =>
      prev.map((n) => {
        if (n.id !== `p${page}`) return n;
        const d = n.data as PageNodeData;
        if (type === "page_start") {
          return {
            ...n,
            data: { ...d, status: "processing" as PageStatus, tokenBuffer: "" },
          };
        }
        if (type === "token") {
          const buf = ((d.tokenBuffer ?? "") + (ev.token as string)).slice(
            -300,
          );
          return { ...n, data: { ...d, tokenBuffer: buf } };
        }
        if (type === "page_done") {
          return {
            ...n,
            data: {
              ...d,
              status: "done" as PageStatus,
              tokenBuffer: "",
              mood: ev.mood as string,
              dialogues: ev.dialogues as number,
              characters: ev.characters as number,
              summary: ev.summary as string,
            },
          };
        }
        if (type === "page_error") {
          return {
            ...n,
            data: {
              ...d,
              status: "error" as PageStatus,
              tokenBuffer: "",
              error: ev.error as string,
            },
          };
        }
        return n;
      }),
    );

    // animate edge after page completes
    if (type === "page_done") {
      setEdges((prev) =>
        prev.map((e) =>
          e.id === `e${page}`
            ? {
                ...e,
                animated: false,
                style: { stroke: "hsl(var(--accent2))", strokeWidth: 1.5 },
              }
            : e.id === `e${page + 1}`
              ? { ...e, animated: true }
              : e,
        ),
      );
    }
  }, [events]);

  if (pages.length === 0)
    return (
      <div className="flex h-64 items-center justify-center text-sm text-[hsl(var(--text-muted))]">
        loading pages…
      </div>
    );

  return (
    <div className="h-[500px] w-full rounded-lg border border-[hsl(var(--border))] overflow-hidden bg-[hsl(var(--bg))]">
      <style>{`
        .react-flow__node { padding: 0 !important; }
        .react-flow__controls button { background: hsl(var(--bg-surface)); border-color: hsl(var(--border)); color: hsl(var(--text)); }
        .react-flow__minimap { background: hsl(var(--bg-surface)); }
      `}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          color="hsl(var(--border))"
        />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const s = (n.data as PageNodeData).status;
            if (s === "done") return "hsl(var(--success))";
            if (s === "error") return "hsl(var(--danger))";
            if (s === "processing") return "hsl(var(--accent2))";
            return "hsl(var(--border))";
          }}
          maskColor="hsl(var(--bg) / 0.6)"
        />
      </ReactFlow>
    </div>
  );
}
