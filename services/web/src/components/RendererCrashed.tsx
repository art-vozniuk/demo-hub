import { AlertCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface Props {
  reason: "abort" | "window-error" | "stall" | "unknown";
  message?: string;
  engineLogTail?: string[];
  onRetry?: () => void;
}

const HUMAN_REASON: Record<Props["reason"], string> = {
  abort:          "The renderer engine aborted while starting up.",
  "window-error": "The renderer hit an unhandled error.",
  stall:          "The renderer didn't finish loading in time.",
  unknown:        "The renderer ran into an unexpected problem.",
};

export const RendererCrashed = ({ reason, message, engineLogTail, onRetry }: Props) => {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-destructive/40 bg-destructive/5 px-6 py-12 text-center min-h-[60vh] gap-4">
      <AlertCircle className="h-10 w-10 text-destructive" aria-hidden />
      <h2 className="text-2xl font-semibold tracking-tight">Renderer failed to start</h2>
      <p className="max-w-lg text-sm text-muted-foreground">{HUMAN_REASON[reason]}</p>
      <p className="text-xs text-muted-foreground/70">
        We've logged the failure — try again, or open this page on a different device.
      </p>

      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-2 gap-2">
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </Button>
      )}

      {(message || (engineLogTail && engineLogTail.length > 0)) && (
        <details className="max-w-2xl w-full text-left mt-4">
          <summary className="cursor-pointer text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors">
            Technical details
          </summary>
          <pre className="mt-2 p-3 rounded bg-muted/30 text-[10px] text-muted-foreground whitespace-pre-wrap break-all font-mono max-h-64 overflow-y-auto">
            {message ? `error: ${message}\n` : ""}
            {engineLogTail && engineLogTail.length > 0
              ? `\n--- engine log (last ${engineLogTail.length} lines) ---\n${engineLogTail.join("\n")}`
              : ""}
          </pre>
        </details>
      )}
    </div>
  );
};
