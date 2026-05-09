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
  stages?: PipelineStage[];
  className?: string;
}

function activeStageIndex(status: PipelineStatusItem | null): number {
  if (!status) return 0;
  if (status.status === "PENDING") return 0;
  if (status.status === "RUNNING") {
    if (status.eta_seconds == null) return 1;
    if (status.eta_seconds > 8) return 1;
    if (status.eta_seconds > 2) return 2;
    return 3;
  }
  if (status.status === "COMPLETED") return 4;
  if (status.status === "FAILED") return -1;
  return 0;
}

function formatEta(seconds: number | null | undefined): string | null {
  if (seconds == null || !isFinite(seconds)) return null;
  if (seconds <= 0) return "almost done";
  if (seconds < 60) return `~${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return s > 0 ? `~${m}m ${s}s` : `~${m}m`;
}

const PipelineProgress = ({
  status,
  stages = DEFAULT_STAGES,
  className,
}: PipelineProgressProps) => {
  const failed = status?.status === "FAILED";
  const active = activeStageIndex(status);
  const eta = formatEta(status?.eta_seconds);

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
                  isActive &&
                    "border-primary text-primary",
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
              {isActive && eta && (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {eta}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {failed && status?.message && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {status.message}
        </div>
      )}
    </div>
  );
};

export default PipelineProgress;
