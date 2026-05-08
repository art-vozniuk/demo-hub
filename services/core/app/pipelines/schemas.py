from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, field_validator

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
    estimated_finish_at: datetime | None = None
    # Structured pipeline output (e.g. face_recognition's detected face
    # bboxes). None when the pipeline didn't produce one or hasn't completed.
    payload: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @field_validator("payload", mode="before")
    @classmethod
    def _unwrap_payload(cls, v: Any) -> Any:
        # SQLAlchemy hands the relationship object; pull its `.payload` JSON
        # column out so the wire format is just the dict.
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return getattr(v, "payload", None)


class PipelineStatusResponse(BaseModel):
    pipelines: list[PipelineStatusItem]
