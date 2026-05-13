import type { UserPipelineItem } from "@/api";

interface Props {
  pipeline: UserPipelineItem;
}

const UnknownPipelineDetails = ({ pipeline }: Props) => {
  return (
    <div className="grid gap-3 text-xs sm:grid-cols-2">
      {pipeline.input ? (
        <div>
          <div className="text-muted-foreground mb-1">Input</div>
          <pre className="overflow-x-auto rounded-md bg-muted/40 px-2 py-1.5 text-[11px]">
            {JSON.stringify(pipeline.input, null, 2)}
          </pre>
        </div>
      ) : null}
      {pipeline.result ? (
        <div>
          <div className="text-muted-foreground mb-1">Result</div>
          <pre className="overflow-x-auto rounded-md bg-muted/40 px-2 py-1.5 text-[11px]">
            {JSON.stringify(pipeline.result, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
};

export default UnknownPipelineDetails;
