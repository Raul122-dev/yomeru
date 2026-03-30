import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { getRun, getTypesetStatus, type Run } from "../lib/api";
import { PhaseBar, type Phase } from "../components/PhaseBar";
import { DetectionPhase } from "../components/DetectionPhase";
import { AnalysisSection } from "../components/AnalysisSection";
import { TypesetSection } from "../components/TypesetSection";
import { StageView } from "../components/StageView";

const getPages = (id: string): Promise<{ page: number; filename: string }[]> =>
  fetch(`/api/runs/${id}/pages`).then((r) => r.json());

type PhaseStatus = "pending" | "running" | "done" | "failed";

function defaultPhase(run: Run): Phase {
  // Legacy runs without sub-statuses
  if (!run.detection_status && run.status === "done") return "analysis";
  if (run.analysis_status === "done" || run.analysis_status === "running")
    return "analysis";
  if (run.detection_status === "done") return "analysis";
  if (run.detection_status === "running") return "detection";
  return "detection";
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const runId = id as string;
  const qc = useQueryClient();

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    refetchInterval: (q: { state: { data?: Run } }) => {
      const r = q.state.data;
      if (!r) return 2000;
      const active =
        ["running"].includes(r.status) ||
        ["running"].includes(r.detection_status ?? "") ||
        ["running"].includes(r.analysis_status ?? "");
      return active ? 2000 : false;
    },
  });

  const { data: typesetStatus } = useQuery({
    queryKey: ["typeset-status", runId],
    queryFn: () => getTypesetStatus(runId),
    refetchInterval: 5000,
    retry: false,
  });

  const { data: pages = [] } = useQuery({
    queryKey: ["pages", runId],
    queryFn: () => getPages(runId),
    enabled: !!run,
  });

  const [activePhase, setActivePhase] = useState<Phase>("detection");

  useEffect(() => {
    if (run) setActivePhase(defaultPhase(run));
  }, [run?.detection_status, run?.analysis_status, run?.status]);

  if (!run)
    return (
      <div className="text-sm text-[hsl(var(--text-muted))]">loading…</div>
    );

  // Typeset output actually exists
  const typesetOutputExists =
    typesetStatus?.status === "done" && (typesetStatus?.pages?.length ?? 0) > 0;

  // Legacy runs (pre-phase-tracking) — count as analysis done
  const legacyDone = !run.detection_status && run.status === "done";
  const anaDone = run.analysis_status === "done" || legacyDone;

  // Per-typeset-stage statuses (pulled from run meta when available)
  const tsStatuses = {
    matching: ((run as any).typeset_matching_status ??
      (typesetOutputExists ? "done" : "pending")) as PhaseStatus,
    inpainting: ((run as any).typeset_inpainting_status ??
      (typesetOutputExists ? "done" : "pending")) as PhaseStatus,
    rendering: ((run as any).typeset_rendering_status ??
      (typesetOutputExists ? "done" : "pending")) as PhaseStatus,
  };

  const handlePhaseClick = (phase: Phase) => {
    if (phase === "detection") {
      setActivePhase("detection");
      return;
    }
    if (
      phase === "analysis" &&
      (run.detection_status === "done" || legacyDone)
    ) {
      setActivePhase("analysis");
      return;
    }
    if (
      ["typeset_matching", "typeset_inpainting", "typeset_rendering"].includes(
        phase,
      ) &&
      anaDone
    ) {
      setActivePhase(phase);
      return;
    }
  };

  // Typeset phases — show TypesetSection for all three, it handles which stage to highlight
  const isTypesetPhase = [
    "typeset_matching",
    "typeset_inpainting",
    "typeset_rendering",
  ].includes(activePhase);

  return (
    <div className="space-y-4">
      {/* nav */}
      <div className="flex items-center gap-3">
        <Link
          to="/"
          className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))] transition-colors"
        >
          <ArrowLeft size={16} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold leading-tight">{run.name}</h1>
          <p className="text-[11px] text-[hsl(var(--text-muted))]">
            {run.model} · {run.comic_format} · {run.total_pages} pages
          </p>
        </div>
      </div>

      {/* grouped phase bar */}
      <PhaseBar
        run={run}
        typesetStageStatuses={tsStatuses}
        typesetOutputExists={typesetOutputExists}
        activePhase={activePhase}
        onPhaseClick={handlePhaseClick}
      />

      {/* phase content */}
      {activePhase === "detection" && (
        <DetectionPhase
          runId={runId}
          pages={pages}
          onDetectionDone={() => {
            qc.invalidateQueries({ queryKey: ["run", runId] });
            setActivePhase("analysis");
          }}
        />
      )}

      {activePhase === "analysis" && (
        <AnalysisSection
          runId={runId}
          pages={pages}
          showRunButton={
            run.detection_status === "done" && run.analysis_status !== "running"
          }
          onAnalysisDone={() =>
            qc.invalidateQueries({ queryKey: ["run", runId] })
          }
        />
      )}

      {/* S3 and S4: focused StageView */}
      {(activePhase === "typeset_matching" ||
        activePhase === "typeset_inpainting") && (
        <StageView
          runId={runId}
          pages={pages}
          stage={activePhase}
          onStageStatusChange={(stage, status) => {
            qc.invalidateQueries({ queryKey: ["run", runId] });
            qc.invalidateQueries({ queryKey: ["typeset-status", runId] });
          }}
        />
      )}

      {/* S5 rendering and full typeset: TypesetSection with full result view */}
      {activePhase === "typeset_rendering" && (
        <TypesetSection
          runId={runId}
          pages={pages}
          runStatus={run.status}
          activeStage="typeset_rendering"
          onStageStatusChange={(stage, status) => {
            qc.invalidateQueries({ queryKey: ["run", runId] });
            qc.invalidateQueries({ queryKey: ["typeset-status", runId] });
          }}
        />
      )}
    </div>
  );
}
