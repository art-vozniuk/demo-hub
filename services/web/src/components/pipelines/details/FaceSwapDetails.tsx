import type { UserPipelineItem } from "@/api";

interface Props {
  pipeline: UserPipelineItem;
}

const FaceSwapDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as { result_url?: string };
  const sourceKey =
    typeof input.source_image_key === "string" ? input.source_image_key : null;
  const templateKey =
    typeof input.template_image_key === "string" ? input.template_image_key : null;

  return (
    <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
      <div className="space-y-1 text-sm">
        {sourceKey && (
          <div className="text-xs text-muted-foreground truncate">
            Source face: {sourceKey}
          </div>
        )}
        {templateKey && (
          <div className="text-xs text-muted-foreground truncate">
            Template: {templateKey}
          </div>
        )}
      </div>
      {result.result_url ? (
        <a
          href={result.result_url}
          target="_blank"
          rel="noreferrer"
          className="block"
        >
          <img
            src={result.result_url}
            alt="Face swap result"
            className="h-32 w-32 rounded-md object-cover border border-border"
          />
        </a>
      ) : null}
    </div>
  );
};

export default FaceSwapDetails;
