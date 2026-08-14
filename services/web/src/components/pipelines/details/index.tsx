import type { UserPipelineItem } from "@/api";
import FluxDetails from "./FluxDetails";
import FaceSwapDetails from "./FaceSwapDetails";
import FaceRecognitionDetails from "./FaceRecognitionDetails";
import GenerativeT2iDetails from "./GenerativeT2iDetails";
import SharpDetails from "./SharpDetails";
import TranscriberDetails from "./TranscriberDetails";
import TrellisDetails from "./TrellisDetails";
import UnknownPipelineDetails from "./UnknownPipelineDetails";

interface Props {
  pipeline: UserPipelineItem;
}

const PipelineDetails = ({ pipeline }: Props) => {
  switch (pipeline.pipeline_name) {
    case "generative_editing":
    case "generative_editing_custom":
      // Same shape (prompt + source + result); the details view doesn't
      // care whether the prompt came from a preset slug or free-form.
      return <FluxDetails pipeline={pipeline} />;
    case "face_swap":
      return <FaceSwapDetails pipeline={pipeline} />;
    case "face_recognition":
      return <FaceRecognitionDetails pipeline={pipeline} />;
    case "sharp":
      return <SharpDetails pipeline={pipeline} />;
    case "trellis":
      return <TrellisDetails pipeline={pipeline} />;
    case "transcriber":
      return <TranscriberDetails pipeline={pipeline} />;
    case "generative_t2i":
      return <GenerativeT2iDetails pipeline={pipeline} />;
    default:
      return <UnknownPipelineDetails pipeline={pipeline} />;
  }
};

export default PipelineDetails;

export const PIPELINE_DISPLAY_NAME: Record<string, string> = {
  generative_editing: "Flux",
  generative_editing_custom: "Flux (custom)",
  face_swap: "Face Swap",
  face_recognition: "Face Recognition",
  sharp: "SHARP",
  trellis: "TRELLIS",
  transcriber: "Transcriber",
  generative_t2i: "Generative T2I",
};

export const getPipelineDisplayName = (name: string): string => {
  if (PIPELINE_DISPLAY_NAME[name]) return PIPELINE_DISPLAY_NAME[name];
  return name
    .split("_")
    .map((s) => (s.length === 0 ? s : s[0].toUpperCase() + s.slice(1)))
    .join(" ");
};
