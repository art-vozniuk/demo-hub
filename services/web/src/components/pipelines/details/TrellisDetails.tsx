import { Link } from "react-router-dom";
import { Boxes } from "lucide-react";
import type { UserPipelineItem } from "@/api";
import { getPublicImageUrl } from "@/lib/s3";
import PipelinePreviewImage from "../PipelinePreviewImage";

interface Props {
  pipeline: UserPipelineItem;
}

type TrellisResult = {
  result_url?: string;
};

const buildViewerHref = (
  result: TrellisResult,
  title: string,
): string | null => {
  if (!result.result_url) return null;
  const params = new URLSearchParams();
  params.set("url", result.result_url);
  params.set("title", title);
  return `/trellis/view?${params.toString()}`;
};

// Mirrors MESH_QUALITY_OPTIONS in GenerateAssetOverlay — the picker in
// the generation UI is the only place these step counts are user-facing.
const QUALITY_BY_STEPS: Record<number, string> = {
  4: "Low",
  8: "Standard",
  12: "High",
};

const TrellisDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as TrellisResult;
  const sourceUrl = getPublicImageUrl(
    typeof input.image_bucket === "string" ? input.image_bucket : null,
    typeof input.image_key === "string" ? input.image_key : null,
  );
  const steps = typeof input.steps === "number" ? input.steps : null;
  const qualityLabel = steps !== null ? QUALITY_BY_STEPS[steps] ?? null : null;
  const viewerHref = buildViewerHref(result, "TRELLIS result");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-4 items-start">
        {sourceUrl && <PipelinePreviewImage url={sourceUrl} label="Source" />}
        {viewerHref && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">
              3D mesh
            </div>
            <Link
              to={viewerHref}
              className="group flex h-32 w-32 sm:h-40 sm:w-40 flex-col items-center justify-center gap-2 rounded-md border border-border bg-card hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <Boxes className="h-9 w-9 text-muted-foreground group-hover:text-foreground transition-colors" />
              <span className="text-xs font-medium">Open renderer</span>
              {(qualityLabel || steps !== null) && (
                <span className="text-[10px] text-muted-foreground">
                  {qualityLabel
                    ? `${qualityLabel} quality`
                    : `${steps} steps`}
                </span>
              )}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
};

export default TrellisDetails;
