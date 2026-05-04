import { AlertOctagon, RefreshCw } from "lucide-react";

import { Sentry } from "@/lib/sentry";
import { Button } from "@/components/ui/button";

const Fallback = ({ error, resetError }: { error: unknown; resetError: () => void }) => {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-6 py-12 text-center gap-4">
      <AlertOctagon className="h-10 w-10 text-destructive" aria-hidden />
      <h1 className="text-2xl font-semibold tracking-tight">Something went wrong</h1>
      <p className="max-w-lg text-sm text-muted-foreground">
        The page crashed. We've logged the error.
      </p>
      <Button variant="outline" size="sm" onClick={resetError} className="mt-2 gap-2">
        <RefreshCw className="h-3.5 w-3.5" />
        Reload
      </Button>
      <details className="max-w-lg w-full text-left mt-4">
        <summary className="cursor-pointer text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors">
          Technical details
        </summary>
        <pre className="mt-2 p-3 rounded bg-muted/30 text-[10px] text-muted-foreground whitespace-pre-wrap break-all font-mono max-h-64 overflow-y-auto">
          {message}
        </pre>
      </details>
    </div>
  );
};

export const AppErrorBoundary = ({ children }: { children: React.ReactNode }) => (
  <Sentry.ErrorBoundary fallback={({ error, resetError }) => <Fallback error={error} resetError={resetError} />}>
    {children}
  </Sentry.ErrorBoundary>
);
