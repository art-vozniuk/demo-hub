import type { UserPipelineItem, FaceRecognitionResult } from "@/api";

interface Props {
  pipeline: UserPipelineItem;
}

const FaceRecognitionDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? null) as FaceRecognitionResult | null;
  const sourceKey = typeof input.image_key === "string" ? input.image_key : null;

  return (
    <div className="space-y-2 text-sm">
      {sourceKey && (
        <div className="text-xs text-muted-foreground truncate">
          Image: {sourceKey}
        </div>
      )}
      {result ? (
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <div>
            <span className="text-muted-foreground">Faces detected: </span>
            <span className="font-medium">{result.faces?.length ?? 0}</span>
          </div>
          {result.image_width && result.image_height && (
            <div>
              <span className="text-muted-foreground">Dimensions: </span>
              <span className="font-medium">
                {result.image_width}×{result.image_height}
              </span>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
};

export default FaceRecognitionDetails;
