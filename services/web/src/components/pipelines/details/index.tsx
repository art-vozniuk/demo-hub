import type { UserPipelineItem } from "@/api";
import GenerativeEditingDetails from "./GenerativeEditingDetails";
import FaceSwapDetails from "./FaceSwapDetails";
import FaceRecognitionDetails from "./FaceRecognitionDetails";
import SharpDetails from "./SharpDetails";
import UnknownPipelineDetails from "./UnknownPipelineDetails";

interface Props {
  pipeline: UserPipelineItem;
}

const PipelineDetails = ({ pipeline }: Props) => {
  switch (pipeline.pipeline_name) {
    case "generative_editing":
      return <GenerativeEditingDetails pipeline={pipeline} />;
    case "face_swap":
      return <FaceSwapDetails pipeline={pipeline} />;
    case "face_recognition":
      return <FaceRecognitionDetails pipeline={pipeline} />;
    case "sharp":
      return <SharpDetails pipeline={pipeline} />;
    default:
      return <UnknownPipelineDetails pipeline={pipeline} />;
  }
};

export default PipelineDetails;

export const PIPELINE_DISPLAY_NAME: Record<string, string> = {
  generative_editing: "Generative Editing",
  face_swap: "Face Swap",
  face_recognition: "Face Recognition",
  sharp: "SHARP",
};

export const getPipelineDisplayName = (name: string): string => {
  if (PIPELINE_DISPLAY_NAME[name]) return PIPELINE_DISPLAY_NAME[name];
  return name
    .split("_")
    .map((s) => (s.length === 0 ? s : s[0].toUpperCase() + s.slice(1)))
    .join(" ");
};
