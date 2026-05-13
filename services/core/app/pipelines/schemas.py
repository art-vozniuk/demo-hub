from datetime import datetime
from typing import Any
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
    pipeline_name: str
    status: PipelineStatus
    message: str | None = None
    result: dict[str, Any] | None = None
    eta_seconds: float | None = None

    model_config = {"from_attributes": True}


class PipelineStatusResponse(BaseModel):
    pipelines: list[PipelineStatusItem]


class PipelineEstimateResponse(BaseModel):
    pipeline_id: UUID
    estimated_seconds: float
    queue_position: int
    worker_count: int
    workers_missing: bool


class UserPipelineItem(BaseModel):
    id: UUID
    pipeline_name: str
    status: PipelineStatus
    message: str | None = None
    input: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserPipelinesResponse(BaseModel):
    pipelines: list[UserPipelineItem]
    total: int
    limit: int
    offset: int
