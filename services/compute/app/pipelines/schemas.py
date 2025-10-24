from typing import Any

from pydantic import BaseModel


class PipelineInput(BaseModel):
    pass


class RecastPipelineInput(PipelineInput):
    source_image_bucket: str
    source_image_key: str
    template_image_bucket: str
    template_image_key: str


class Request(BaseModel):
    pipeline_name: str
    input: dict[str, Any]
