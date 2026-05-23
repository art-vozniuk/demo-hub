import type { UserPipelineItem } from "@/api";
import { getPublicImageUrl } from "@/lib/s3";
import PipelinePreviewImage from "../PipelinePreviewImage";

interface Props {
  pipeline: UserPipelineItem;
}

const FluxDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as { result_url?: string };
  const prompt = typeof input.prompt === "string" ? input.prompt : null;
  const presetSlug =
    typeof input.preset_slug === "string" ? input.preset_slug : null;
  const sourceUrl = getPublicImageUrl(
    typeof input.image_bucket === "string" ? input.image_bucket : null,
    typeof input.image_key === "string" ? input.image_key : null,
  );

  return (
    <div className="space-y-4">
      {(presetSlug || prompt) && (
        <div className="space-y-2 text-sm">
          {presetSlug && (
            <div>
              <span className="text-muted-foreground">Preset: </span>
              <span className="font-medium">{presetSlug}</span>
            </div>
          )}
          {prompt && (
            <div>
              <div className="text-muted-foreground mb-1">Prompt</div>
              <p className="whitespace-pre-wrap rounded-md bg-muted/40 px-3 py-2 text-sm">
                {prompt}
              </p>
            </div>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-4">
        {sourceUrl && <PipelinePreviewImage url={sourceUrl} label="Source" />}
        {result.result_url && (
          <PipelinePreviewImage url={result.result_url} label="Result" />
        )}
      </div>
    </div>
  );
};

export default FluxDetails;
