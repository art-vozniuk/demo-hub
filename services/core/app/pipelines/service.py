import logging
from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.common.domain.enums import PipelineStatus
from .models import Pipeline, PipelinePayload

log = logging.getLogger(__name__)


async def create_pipeline(
    db: AsyncSession,
    pipeline_id: UUID,
    trace_id: UUID,
    pipeline_name: str,
    estimated_finish_at: datetime | None = None,
) -> Pipeline:
    pipeline = Pipeline(
        id=pipeline_id,
        trace_id=trace_id,
        pipeline_name=pipeline_name,
        status=PipelineStatus.PENDING,
        estimated_finish_at=estimated_finish_at,
    )
    db.add(pipeline)
    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    log.info(f"Pipeline created with status {PipelineStatus.PENDING}")

    return pipeline


async def get_pipelines_by_ids(
    db: AsyncSession,
    pipeline_ids: list[UUID],
) -> list[Pipeline]:
    result = await db.execute(
        select(Pipeline)
        .options(selectinload(Pipeline.payload))
        .where(Pipeline.id.in_(pipeline_ids))
    )
    return list(result.scalars().all())


async def get_pipeline_payload(
    db: AsyncSession,
    pipeline_id: UUID,
) -> PipelinePayload | None:
    result = await db.execute(
        select(PipelinePayload).where(PipelinePayload.pipeline_id == pipeline_id)
    )
    return result.scalar_one_or_none()


async def update_pipeline_status(
    db: AsyncSession,
    pipeline_id: UUID,
    status: PipelineStatus,
    result_url: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
) -> Pipeline | None:
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()

    if not pipeline:
        return None

    pipeline.status = status

    if result_url is not None:
        pipeline.result_url = result_url

    if message is not None:
        pipeline.message = message

    if payload is not None:
        # Upsert the per-pipeline payload row. Compute publishes payload only
        # on the terminal COMPLETED update for pipelines that produce one
        # (currently face_recognition); face_swap leaves it untouched.
        existing = await db.execute(
            select(PipelinePayload).where(PipelinePayload.pipeline_id == pipeline_id)
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is None:
            db.add(PipelinePayload(pipeline_id=pipeline_id, payload=payload))
        else:
            existing_row.payload = payload

    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    log.info(f"Pipeline status updated to {status}")

    return pipeline
