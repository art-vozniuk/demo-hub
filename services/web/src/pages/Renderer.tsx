import { useState, useEffect } from "react";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;

const Renderer = () => {
  const [isReady, setIsReady] = useState(false);
  const [progress, setProgress] = useState(0);

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
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  return (
    <main className="container mx-auto px-6 py-16 space-y-8 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-4 text-center animate-fade-in">
        <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
          <span className="text-gradient">OpenGL Renderer</span>
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          Real-time 3D renderer built with a custom C++ engine. Features Phong
          lighting, normal mapping, cubemap reflections, and post-processing
          effects — compiled to WebAssembly via Emscripten and running in your
          browser using WebGL 2.
        </p>
      </section>

      <div className="max-w-5xl mx-auto">
        {!RENDERER_URL ? (
          <div className="flex items-center justify-center rounded-lg border border-border text-muted-foreground h-96">
            Renderer is not configured.
          </div>
        ) : (
          <>
            <div
              className="relative w-full rounded-lg overflow-hidden border border-border"
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
                src={RENDERER_URL}
                className="w-full h-full border-0"
                allow="fullscreen"
                title="OpenGL Renderer"
              />
            </div>

            {isReady && (
              <p className="mt-3 text-xs text-muted-foreground text-center">
                Hold{" "}
                <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">
                  RMB
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
