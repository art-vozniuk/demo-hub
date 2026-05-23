export const getPipelineShareUrl = (pipelineId: string): string => {
  if (typeof window === "undefined") return `/p/${pipelineId}`;
  return `${window.location.origin}/p/${pipelineId}`;
};

export const canUseWebShare = (): boolean =>
  typeof navigator !== "undefined" && typeof navigator.share === "function";

export const PIPELINE_TRY_HREF: Record<string, string> = {
  face_swap: "/face-fusion",
  generative_editing: "/flux",
  generative_editing_custom: "/flux/custom",
  sharp: "/sharp",
};

export const getTryItHref = (pipelineName: string): string =>
  PIPELINE_TRY_HREF[pipelineName] ?? "/";
