import { useState, useEffect, useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Github } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAnalytics } from "@/hooks/useAnalytics";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;

const Renderer = () => {
  const [isReady, setIsReady] = useState(false);
  const [progress, setProgress] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { track } = useAnalytics();

  const checkIfAlreadyReady = useCallback(() => {
    try {
      const iWin = iframeRef.current?.contentWindow as any;
      if (iWin?.Module?.setStatus && iWin?.document?.title === "Engine") {
        setIsReady(true);
      }
    } catch {
      // cross-origin — ignore
    }
  }, []);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      if (e.data?.type === "renderer-ready") {
        setIsReady(true);
      } else if (e.data?.type === "renderer-progress") {
        const pct = Math.round((e.data.loaded / e.data.total) * 100);
        setProgress(Math.min(pct, 100));
      }
    };
    window.addEventListener("message", handleMessage);

    // If the iframe loaded before this listener was set up (race condition
    // with fast local builds), poll briefly to detect it.
    const poll = setInterval(checkIfAlreadyReady, 500);
    const timeout = setTimeout(() => clearInterval(poll), 60_000);

    return () => {
      window.removeEventListener("message", handleMessage);
      clearInterval(poll);
      clearTimeout(timeout);
    };
  }, [checkIfAlreadyReady]);

  return (
    <main className="container mx-auto px-6 py-16 space-y-8 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            <span className="text-gradient">3D Renderer</span>
          </h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Real-time 3D renderer running entirely in your browser.
            Built from scratch in C++ with a custom rendering engine,
            compiled to WebAssembly via Emscripten and powered by WebGL 2.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  className="rounded-full animate-pulse-glow"
                  asChild
                >
                  <a
                    href="https://github.com/art-vozniuk/OpenGL-Renderer"
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="GitHub Repository"
                    onClick={() => track({ name: 'renderer_github_repo_clicked', params: {} })}
                  >
                    <Github className="h-5 w-5" />
                  </a>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>Visit the repository</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </section>

      <div className="max-w-5xl mx-auto">
        {!RENDERER_URL ? (
          <div className="flex items-center justify-center rounded-lg border border-border text-muted-foreground h-96">
            Renderer is not configured.
          </div>
        ) : (
          <>
            <div
              className="relative w-full rounded-lg overflow-hidden"
              style={{ height: "75vh" }}
            >
              {!isReady && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-background z-10 gap-4">
                  <p className="text-sm text-muted-foreground">
                    Loading renderer and assets...
                  </p>
                  <div className="w-64 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-300 ease-out"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground/60">
                    {progress > 0 ? `${progress}%` : "Connecting..."}
                  </p>
                </div>
              )}
              <iframe
                ref={iframeRef}
                src={RENDERER_URL}
                className="w-full h-full border-0 outline-none"
                allow="fullscreen"
                title="OpenGL Renderer"
              />
            </div>

            {isReady && (
              <p className="mt-3 text-xs text-muted-foreground text-center">
                Hold{" "}
                <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">
                  LMB
                </kbd>{" "}
                and use{" "}
                <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">
                  W A S D
                </kbd>{" "}
                to move the camera
              </p>
            )}
          </>
        )}
      </div>
    </main>
  );
};

export default Renderer;
