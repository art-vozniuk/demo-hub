import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SplatViewer, type SplatViewerScene } from "@/components/SplatViewer";

/** Standalone full-page viewer for a TRELLIS-generated GLB. URL params:
 *    url   - public .glb URL (required)
 *    title - optional display title shown in the header.
 *
 * The renderer's `glb_viewer` scene computes the orbit pose from the
 * mesh AABB, so we don't pass eye/fwd vectors here. */
const TrellisViewer = () => {
  const [params] = useSearchParams();
  const sceneUrl = params.get("url");
  const title = params.get("title") || "TRELLIS result";

  const scene = useMemo<SplatViewerScene | null>(() => {
    if (!sceneUrl) return null;
    return {
      slug: `trellis-${sceneUrl}`,
      title,
      sceneUrl,
      cameraEye: [],
      cameraFwd: [],
      sceneKind: "glb_viewer",
    };
  }, [sceneUrl, title]);

  if (!scene) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Missing <code>?url=</code> parameter — nothing to render.
        </div>
      </main>
    );
  }

  return (
    <main className="container mx-auto px-3 sm:px-6 py-6 space-y-4">
      <div className="flex items-center gap-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2">
          <Link to="/me/pipelines">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back
          </Link>
        </Button>
        <h1 className="text-lg sm:text-xl font-semibold tracking-tight truncate">
          {title}
        </h1>
      </div>
      <SplatViewer scene={scene} height="80vh" />
    </main>
  );
};

export default TrellisViewer;
