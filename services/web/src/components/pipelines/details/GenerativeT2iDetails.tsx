import type { UserPipelineItem } from "@/api";
import PipelinePreviewImage from "../PipelinePreviewImage";

interface Props {
  pipeline: UserPipelineItem;
}

type GenerativeT2iResult = {
  result_url?: string;
};

const GenerativeT2iDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as GenerativeT2iResult;
  const prompt = typeof input.prompt === "string" ? input.prompt : null;
  const seed = typeof input.seed === "number" ? input.seed : null;
  const width = typeof input.width === "number" ? input.width : null;
  const height = typeof input.height === "number" ? input.height : null;

  return (
    <div className="space-y-4">
      {prompt && (
        <div>
          <div className="text-muted-foreground mb-1 text-xs">Prompt</div>
          <p className="whitespace-pre-wrap rounded-md bg-muted/40 px-3 py-2 text-sm">
            {prompt}
          </p>
          {(seed !== null || (width !== null && height !== null)) && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground tabular-nums">
              {width !== null && height !== null && (
                <span>
                  {width}×{height}
                </span>
              )}
              {seed !== null && <span>seed {seed}</span>}
            </div>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-4">
        {result.result_url && (
          <PipelinePreviewImage url={result.result_url} label="Result" />
        )}
      </div>
    </div>
  );
};

export default GenerativeT2iDetails;
