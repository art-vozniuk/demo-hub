import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SplatViewer, type SplatViewerScene } from "@/components/SplatViewer";

const parseVec3 = (s: string | null): [number, number, number] | null => {
  if (!s) return null;
  const parts = s.split(",").map((p) => Number(p.trim()));
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return null;
  return [parts[0], parts[1], parts[2]];
};

/** Standalone full-page viewer for a transient SHARP splat. URL params:
 *    url   - public .splat scene URL (required)
 *    eye   - "x,y,z" camera spawn (default 0,0,3)
 *    fwd   - "x,y,z" forward vector (default 0,0,-1)
 *    title - optional display title shown in the header. */
const SharpViewer = () => {
  const [params] = useSearchParams();
  const sceneUrl = params.get("url");
  const title = params.get("title") || "SHARP result";
  const eye = parseVec3(params.get("eye")) ?? [0, 0, 3];
  const fwd = parseVec3(params.get("fwd")) ?? [0, 0, -1];

  const scene = useMemo<SplatViewerScene | null>(() => {
    if (!sceneUrl) return null;
    return {
      slug: `sharp-${sceneUrl}`,
      title,
      sceneUrl,
      cameraEye: eye,
      cameraFwd: fwd,
    };
    // sceneUrl/title/eye/fwd identity drives a fresh viewer mount via slug.
  }, [sceneUrl, title, eye[0], eye[1], eye[2], fwd[0], fwd[1], fwd[2]]);

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

export default SharpViewer;
