from typing import Any, List, Optional

from pydantic import BaseModel


class PipelineInput(BaseModel):
    pass


class FaceRecognitionPipelineInput(PipelineInput):
    image_bucket: str
    image_key: str


class FaceSwapPipelineInput(PipelineInput):
    source_image_bucket: str
    source_image_key: str
    template_image_bucket: str
    template_image_key: str
    # Optional pre-selected face bounding boxes [x1, y1, x2, y2] in the
    # original image's pixel space. When omitted (e.g. standard templates),
    # the pipeline falls back to the largest detected face.
    source_face_bbox: Optional[List[float]] = None
    target_face_bbox: Optional[List[float]] = None


class Request(BaseModel):
    pipeline_name: str
    input: dict[str, Any]
