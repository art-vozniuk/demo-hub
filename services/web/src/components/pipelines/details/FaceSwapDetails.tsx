import type { UserPipelineItem } from "@/api";
import { getPublicImageUrl } from "@/lib/s3";
import PipelinePreviewImage from "../PipelinePreviewImage";

interface Props {
  pipeline: UserPipelineItem;
}

const FaceSwapDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as { result_url?: string };
  const sourceUrl = getPublicImageUrl(
    typeof input.source_image_bucket === "string"
      ? input.source_image_bucket
      : null,
    typeof input.source_image_key === "string" ? input.source_image_key : null,
  );
  const templateUrl = getPublicImageUrl(
    typeof input.template_image_bucket === "string"
      ? input.template_image_bucket
      : null,
    typeof input.template_image_key === "string"
      ? input.template_image_key
      : null,
  );

  return (
    <div className="flex flex-wrap gap-4">
      {sourceUrl && <PipelinePreviewImage url={sourceUrl} label="Source" />}
      {templateUrl && (
        <PipelinePreviewImage url={templateUrl} label="Template" />
      )}
      {result.result_url && (
        <PipelinePreviewImage url={result.result_url} label="Result" />
      )}
    </div>
  );
};

export default FaceSwapDetails;
