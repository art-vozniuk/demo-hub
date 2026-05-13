import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PipelineStatus } from "@/api";

interface PipelineStatusBadgeProps {
  status: PipelineStatus;
  className?: string;
}

const STATUS_LABEL: Record<PipelineStatus, string> = {
  PENDING: "Pending",
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

const PipelineStatusBadge = ({ status, className }: PipelineStatusBadgeProps) => {
  const isInProgress = status === "PENDING" || status === "RUNNING";

  return (
    <div className={cn("inline-flex items-center gap-2 text-xs sm:text-sm", className)}>
      {isInProgress ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
      ) : (
        <span
          className={cn(
            "inline-block h-2 w-2 rounded-full",
            status === "COMPLETED" && "bg-green-500 shadow-[0_0_0_3px_rgba(34,197,94,0.15)]",
            status === "FAILED" && "bg-destructive shadow-[0_0_0_3px_rgba(239,68,68,0.15)]",
          )}
          aria-hidden
        />
      )}
      <span
        className={cn(
          "font-medium",
          status === "COMPLETED" && "text-green-600 dark:text-green-500",
          status === "FAILED" && "text-destructive",
          isInProgress && "text-primary",
        )}
      >
        {STATUS_LABEL[status]}
      </span>
    </div>
  );
};

export default PipelineStatusBadge;
