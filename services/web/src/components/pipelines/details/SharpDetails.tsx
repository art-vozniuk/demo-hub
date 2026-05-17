import { Link } from "react-router-dom";
import { Boxes } from "lucide-react";
import type { UserPipelineItem } from "@/api";
import { getPublicImageUrl } from "@/lib/s3";
import PipelinePreviewImage from "../PipelinePreviewImage";

interface Props {
  pipeline: UserPipelineItem;
}

type SharpResult = {
  result_url?: string;
  video_url?: string | null;
  camera_eye?: [number, number, number] | number[];
  camera_fwd?: [number, number, number] | number[];
  gaussian_count?: number;
};

const buildViewerHref = (
  result: SharpResult,
  title: string,
): string | null => {
  if (!result.result_url) return null;
  const params = new URLSearchParams();
  params.set("url", result.result_url);
  params.set("title", title);
  if (Array.isArray(result.camera_eye) && result.camera_eye.length === 3) {
    params.set("eye", result.camera_eye.join(","));
  }
  if (Array.isArray(result.camera_fwd) && result.camera_fwd.length === 3) {
    params.set("fwd", result.camera_fwd.join(","));
  }
  return `/sharp/view?${params.toString()}`;
};

const SharpDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as SharpResult;
  const sourceUrl = getPublicImageUrl(
    typeof input.image_bucket === "string" ? input.image_bucket : null,
    typeof input.image_key === "string" ? input.image_key : null,
  );
  const viewerHref = buildViewerHref(result, "SHARP result");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-4 items-start">
        {sourceUrl && <PipelinePreviewImage url={sourceUrl} label="Source" />}
        {result.video_url && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">
              Wobble preview
            </div>
            <video
              src={result.video_url}
              className="h-32 w-32 sm:h-40 sm:w-40 rounded-md border border-border bg-black object-cover"
              autoPlay
              loop
              muted
              playsInline
              controls={false}
            />
          </div>
        )}
        {viewerHref && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">
              Splat scene
            </div>
            <Link
              to={viewerHref}
              className="group flex h-32 w-32 sm:h-40 sm:w-40 flex-col items-center justify-center gap-2 rounded-md border border-border bg-card hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <Boxes className="h-9 w-9 text-muted-foreground group-hover:text-foreground transition-colors" />
              <span className="text-xs font-medium">Open renderer</span>
              {typeof result.gaussian_count === "number" && (
                <span className="text-[10px] text-muted-foreground tabular-nums">
                  {result.gaussian_count.toLocaleString()} gaussians
                </span>
              )}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
};

export default SharpDetails;
