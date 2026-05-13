import type { UserPipelineItem } from "@/api";

interface Props {
  pipeline: UserPipelineItem;
}

const GenerativeEditingDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as { result_url?: string };
  const prompt = typeof input.prompt === "string" ? input.prompt : null;
  const presetSlug = typeof input.preset_slug === "string" ? input.preset_slug : null;
  const sourceKey = typeof input.image_key === "string" ? input.image_key : null;

  return (
    <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
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
        {sourceKey && (
          <div className="text-xs text-muted-foreground truncate">
            Source: {sourceKey}
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
            alt="Result"
            className="h-32 w-32 rounded-md object-cover border border-border"
          />
        </a>
      ) : null}
    </div>
  );
};

export default GenerativeEditingDetails;
