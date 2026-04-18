import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Github } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAnalytics } from "@/hooks/useAnalytics";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;

/**
 * The list of scenes the WASM renderer knows about. The `id` here must
 * match the id passed to SCENE_REGISTER(...) on the C++ side. Adding a
 * new scene server-side means adding a new entry here.
 */
type SceneOption = {
  id: string;
  label: string;
  description: string;
};

const SCENES: SceneOption[] = [
  {
    id: "sponza",
    label: "Sponza",
    description: "Classic Phong-lit scene with normal maps + cubemap.",
  },
  {
    id: "gsplat",
    label: "Gaussian Splat (preview)",
    description: "Placeholder stub — full splat renderer lands later.",
  },
];

const DEFAULT_SCENE_ID = "sponza";

/** Returns a scene id from ?scene= (if valid) or the default. */
function readSceneFromQuery(): string {
  if (typeof window === "undefined") return DEFAULT_SCENE_ID;
  const param = new URLSearchParams(window.location.search).get("scene");
  if (!param) return DEFAULT_SCENE_ID;
  return SCENES.some((s) => s.id === param) ? param : DEFAULT_SCENE_ID;
}

/** Appends / overwrites the ?scene= query on the iframe URL. */
function buildIframeSrc(base: string, sceneId: string): string {
  try {
    const url = new URL(base, window.location.origin);
    url.searchParams.set("scene", sceneId);
    return url.toString();
  } catch {
    // base wasn't absolute — do a naive concat.
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}scene=${encodeURIComponent(sceneId)}`;
  }
}

/** Human-readable byte size, e.g. 1536000 → "1.5 MB". */
function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type Progress = { loaded: number; total: number } | null;

const Renderer = () => {
  const [sceneId, setSceneId] = useState<string>(() => readSceneFromQuery());
  const [isReady, setIsReady] = useState(false);
  const [progress, setProgress] = useState<Progress>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { track } = useAnalytics();

  const iframeSrc = useMemo(
    () => (RENDERER_URL ? buildIframeSrc(RENDERER_URL, sceneId) : undefined),
    [sceneId],
  );

  const activeScene = SCENES.find((s) => s.id === sceneId) ?? SCENES[0];

  /** Fast path: detect "already ready" if the iframe finished loading before
   *  the message listener was installed (common on cached reloads). */
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

  // Reset loading state whenever the selected scene changes, and keep the
  // browser URL in sync so deep-links / refresh land on the same scene.
  useEffect(() => {
    setIsReady(false);
    setProgress(null);

    const url = new URL(window.location.href);
    if (url.searchParams.get("scene") !== sceneId) {
      url.searchParams.set("scene", sceneId);
      window.history.replaceState({}, "", url.toString());
    }
  }, [sceneId]);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      if (e.data?.type === "renderer-ready") {
        setIsReady(true);
      } else if (e.data?.type === "renderer-progress") {
        const loaded = Number(e.data.loaded) || 0;
        const total = Number(e.data.total) || 0;
        if (total > 0) setProgress({ loaded: Math.min(loaded, total), total });
      }
    };
    window.addEventListener("message", handleMessage);

    // Iframe may have loaded before the listener was ready on fast reloads.
    const poll = setInterval(checkIfAlreadyReady, 500);
    const timeout = setTimeout(() => clearInterval(poll), 60_000);

    return () => {
      window.removeEventListener("message", handleMessage);
      clearInterval(poll);
      clearTimeout(timeout);
    };
  }, [checkIfAlreadyReady, sceneId]);

  // Progress bar fill never snaps to 0 mid-load; we use an unbounded-ish
  // fallback during the initial handshake so the user sees movement.
  const progressFraction = progress ? progress.loaded / progress.total : 0;
  const progressPercent = Math.min(100, progressFraction * 100);

  return (
    <main className="container mx-auto px-6 py-16 space-y-8 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            <span className="text-gradient">3D Renderer</span>
          </h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Real-time 3D renderer running entirely in your browser. Built from
            scratch in C++ with a custom rendering engine, compiled to
            WebAssembly via Emscripten and powered by WebGL 2.
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
                    onClick={() =>
                      track({ name: "renderer_github_repo_clicked", params: {} })
                    }
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

      <div className="max-w-5xl mx-auto space-y-3">
        {/* Scene tabs — styled as pills, key by id so the iframe remounts on
         *   change (ensures the WASM module re-reads ?scene=). */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          {SCENES.map((s) => {
            const active = s.id === sceneId;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  if (s.id !== sceneId) {
                    track({
                      name: "renderer_scene_switched",
                      params: { scene_id: s.id },
                    });
                    setSceneId(s.id);
                  }
                }}
                className={[
                  "px-3 py-1.5 rounded-full text-sm border transition-colors",
                  active
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-muted/40 border-border text-muted-foreground hover:bg-muted",
                ].join(" ")}
                aria-pressed={active}
              >
                {s.label}
              </button>
            );
          })}
        </div>

        {!RENDERER_URL ? (
          <div className="flex items-center justify-center rounded-lg border border-border text-muted-foreground h-96">
            Renderer is not configured.
          </div>
        ) : (
          <>
            <div className="relative w-full" style={{ height: "75vh" }}>
              {!isReady && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-background z-10 gap-4 px-6">
                  <p className="text-sm text-muted-foreground">
                    Loading {activeScene.label}...
                  </p>
                  <div className="w-72 h-2 bg-muted rounded-full overflow-hidden">
                    {/* Indeterminate shimmer before the first progress event,
                     *   real fill afterwards. */}
                    {progress ? (
                      <div
                        className="h-full bg-primary rounded-full transition-[width] duration-300 ease-out"
                        style={{ width: `${Math.max(progressPercent, 2)}%` }}
                      />
                    ) : (
                      <div className="h-full w-1/3 bg-primary/60 rounded-full animate-[pulse_1.4s_ease-in-out_infinite]" />
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground/70 tabular-nums">
                    {progress
                      ? `${formatBytes(progress.loaded)} / ${formatBytes(progress.total)}`
                      : "Connecting..."}
                  </p>
                </div>
              )}
              {/* key={sceneId} forces remount on scene switch so the WASM
               *   module restarts cleanly with the new ?scene= param. */}
              <iframe
                key={sceneId}
                ref={iframeRef}
                src={iframeSrc}
                className="w-full h-full border-0 outline-none"
                allow="fullscreen"
                title={`Renderer — ${activeScene.label}`}
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
