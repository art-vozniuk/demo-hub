import { AlertTriangle } from "lucide-react";

import type { WebGpuStatus } from "@/lib/webgpu";
import { describeUnsupported } from "@/lib/webgpu";

interface Props {
  status: WebGpuStatus;
}

export const RendererUnsupported = ({ status }: Props) => {
  const { title, body, hint, steps } = describeUnsupported(status);

  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "unknown";

  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-muted/10 px-6 py-12 text-center min-h-[60vh] gap-4">
      <AlertTriangle className="h-10 w-10 text-yellow-500/80" aria-hidden />
      <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
      <p className="max-w-lg text-sm text-muted-foreground">{body}</p>
      <p className="max-w-lg text-xs text-muted-foreground/80">{hint}</p>
      {steps && steps.length > 0 && (
        <ol className="max-w-lg w-full text-left text-xs text-muted-foreground/90 list-decimal list-inside space-y-1 marker:text-muted-foreground/60">
          {steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      )}
      <details className="max-w-lg w-full text-left mt-4">
        <summary className="cursor-pointer text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors">
          Technical details
        </summary>
        <pre className="mt-2 p-3 rounded bg-muted/30 text-[10px] text-muted-foreground whitespace-pre-wrap break-all font-mono">
          {`status: ${status.kind}\nuser-agent: ${ua}`}
        </pre>
      </details>
    </div>
  );
};
