from uuid import UUID
from pydantic import BaseModel

from services.common.domain.enums import PipelineStatus


class PipelineJobInput(BaseModel):
    pipeline_id: UUID
    pipeline_name: str
    input: dict


class QueuePipelinesRequest(BaseModel):
    trace_id: UUID
    jobs: list[PipelineJobInput]


class QueuePipelinesResponse(BaseModel):
    trace_id: UUID
    pipeline_ids: list[UUID]
    queue_length: int


class PipelineStatusRequest(BaseModel):
    pipeline_ids: list[UUID]


class PipelineStatusItem(BaseModel):
    id: UUID
    status: PipelineStatus
    result_url: str | None = None
    message: str | None = None

    model_config = {"from_attributes": True}


class PipelineStatusResponse(BaseModel):
    pipelines: list[PipelineStatusItem]
