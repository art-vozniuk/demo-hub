import { useEffect, useState } from "react";
import { Loader2, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PipelineStatusItem } from "@/api";

export type PipelineStage = {
  key: string;
  label: string;
};

const DEFAULT_STAGES: PipelineStage[] = [
  { key: "queued", label: "Starting GPU worker" },
  { key: "running", label: "Loading model" },
  { key: "generating", label: "Generating" },
  { key: "uploading", label: "Uploading result" },
  { key: "done", label: "Done" },
];

interface PipelineProgressProps {
  status: PipelineStatusItem | null;
  // ISO 8601 timestamp captured once at queue time from /pipelines/{id}/estimate.
  // Null when the estimate has not arrived yet — the UI then shows just the
  // current status without a countdown.
  estimatedFinishAt?: string | null;
  workersMissing?: boolean;
  stages?: PipelineStage[];
  className?: string;
}

function progressFraction(
  remaining: number | null,
  total: number | null
): number {
  if (remaining == null || total == null || total <= 0) return 0;
  const fraction = 1 - remaining / total;
  if (!isFinite(fraction)) return 0;
  return Math.max(0, Math.min(1, fraction));
}

function activeStageIndex(
  status: PipelineStatusItem | null,
  remaining: number | null
): number {
  if (!status) return 0;
  if (status.status === "PENDING") return 0;
  if (status.status === "RUNNING") {
    if (remaining == null) return 1;
    if (remaining > 8) return 1;
    if (remaining > 2) return 2;
    return 3;
  }
  // Past every stage so all entries (including "Done") render as completed
  // — not as the active spinner. Comparison-friendly sentinel.
  if (status.status === "COMPLETED") return Number.POSITIVE_INFINITY;
  if (status.status === "FAILED") return -1;
  return 0;
}

const PipelineProgress = ({
  status,
  estimatedFinishAt,
  workersMissing,
  stages = DEFAULT_STAGES,
  className,
}: PipelineProgressProps) => {
  const [now, setNow] = useState(() => Date.now());

  // 250ms ticker drives the countdown. Stops once the pipeline reaches a
  // terminal state.
  useEffect(() => {
    if (!estimatedFinishAt) return;
    if (
      status?.status === "COMPLETED" ||
      status?.status === "FAILED"
    )
      return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [estimatedFinishAt, status?.status]);

  const target = estimatedFinishAt
    ? new Date(estimatedFinishAt).getTime()
    : null;
  const remainingSeconds =
    target != null && !Number.isNaN(target)
      ? Math.max(0, (target - now) / 1000)
      : null;

  const failed = status?.status === "FAILED";
  const completed = status?.status === "COMPLETED";
  const active = activeStageIndex(status, remainingSeconds);

  return (
    <div className={cn("space-y-3", className)}>
      <ol className="space-y-2">
        {stages.map((stage, idx) => {
          const isDone = !failed && idx < active;
          const isActive = !failed && idx === active;
          const isPending = !failed && idx > active;
          return (
            <li
              key={stage.key}
              className={cn(
                "flex items-center gap-3 text-sm",
                isPending && "text-muted-foreground/60",
                isActive && "text-foreground",
                isDone && "text-muted-foreground"
              )}
            >
              <span
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                  isDone &&
                    "border-primary bg-primary text-primary-foreground",
                  isActive && "border-primary text-primary",
                  isPending && "border-border",
                  failed && idx === 0 && "border-destructive text-destructive"
                )}
              >
                {failed && idx === 0 ? (
                  <X className="h-3 w-3" />
                ) : isDone ? (
                  <Check className="h-3 w-3" />
                ) : isActive ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : null}
              </span>
              <span className="flex-1">{stage.label}</span>
            </li>
          );
        })}
      </ol>

      {workersMissing && !failed && (
        <p className="text-xs text-muted-foreground">
          GPU worker is warming up — first request may take longer than the estimate.
        </p>
      )}

      {failed && status?.message && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {status.message}
        </div>
      )}

      {/* Overall progress bar — proxy via the elapsed/total ratio when an
          estimate is present, otherwise a slim indeterminate shimmer.
          Snaps to 100% on completion so a wrong-low estimate doesn't
          leave the bar stuck partway after the result is already in. */}
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        {completed ? (
          <div className="h-full w-full bg-primary" />
        ) : remainingSeconds != null && target != null ? (
          <div
            className="h-full bg-primary transition-[width] duration-300 ease-out"
            style={{
              width: `${
                progressFraction(
                  remainingSeconds,
                  Math.max(
                    0.1,
                    (target - (now - remainingSeconds * 1000)) / 1000
                  )
                ) * 100
              }%`,
            }}
          />
        ) : !failed ? (
          <div className="h-full w-1/3 bg-primary/60 animate-pulse" />
        ) : null}
      </div>
    </div>
  );
};

export default PipelineProgress;
