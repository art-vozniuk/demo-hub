import { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { useAnalytics } from "@/hooks/useAnalytics";
import { DemoHeader } from "@/components/DemoHeader";
import { SplatViewer, type SplatViewerScene } from "@/components/SplatViewer";
import { splatsApi, SplatSceneRead } from "@/api";

/** Catalog scene → SplatViewer's scene shape. */
function toViewerScene(s: SplatSceneRead): SplatViewerScene {
  return {
    slug: s.slug,
    title: s.title,
    sceneUrl: s.scene_url,
    cameraEye: s.camera_eye,
    cameraFwd: s.camera_fwd,
  };
}

const Renderer = () => {
  const [scenes, setScenes] = useState<SplatSceneRead[]>([]);
  const [scenesError, setScenesError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const sceneSlugFromUrl = searchParams.get("scene");
  const selected = useMemo<SplatSceneRead | null>(
    () =>
      sceneSlugFromUrl
        ? scenes.find((s) => s.slug === sceneSlugFromUrl) ?? null
        : null,
    [scenes, sceneSlugFromUrl],
  );
  const selectScene = useCallback(
    (slug: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (slug) next.set("scene", slug);
          else next.delete("scene");
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );
  const { track } = useAnalytics();

  useEffect(() => {
    let alive = true;
    splatsApi
      .getScenes()
      .then((list) => {
        if (alive) setScenes(list);
      })
      .catch((err) => {
        if (alive) setScenesError(err?.message ?? "Failed to load scenes");
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main className="container mx-auto px-6 py-16 space-y-8 min-h-[calc(100vh-8rem)]">
      <DemoHeader
        title="Gaussian Splatting"
        description="Real-time Gaussian Splatting renderer. Custom C++ engine on WebGPU with per-frame GPU radix sort and EWA splat projection in WGSL. Compiled to WebAssembly via Emscripten."
      />

      <div className="max-w-5xl mx-auto space-y-3">
        {!selected ? (
          <div className="space-y-4">
            {scenesError && (
              <div className="text-sm text-destructive text-center">
                {scenesError}
              </div>
            )}
            {scenes.length === 0 && !scenesError ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="aspect-video rounded-lg bg-muted/40 animate-pulse"
                  />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {scenes.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      track({
                        name: "renderer_scene_opened",
                        params: { scene_slug: s.slug },
                      });
                      selectScene(s.slug);
                    }}
                    className="group text-left rounded-lg overflow-hidden border border-border bg-muted/20 hover:bg-muted/40 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <div className="aspect-video w-full overflow-hidden bg-black">
                      <img
                        src={s.image_url}
                        alt={s.title}
                        loading="lazy"
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                      />
                    </div>
                    <div className="p-3 space-y-1">
                      <h3 className="font-semibold tracking-tight">{s.title}</h3>
                      {s.description && (
                        <p className="text-xs text-muted-foreground line-clamp-2">
                          {s.description}
                        </p>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  track({
                    name: "renderer_scene_back",
                    params: { scene_slug: selected.slug },
                  });
                  selectScene(null);
                }}
                className="gap-1"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to scenes
              </Button>
              <div className="text-sm text-muted-foreground">{selected.title}</div>
            </div>

            <SplatViewer scene={toViewerScene(selected)} height="75vh" />
          </div>
        )}
      </div>
    </main>
  );
};

export default Renderer;
