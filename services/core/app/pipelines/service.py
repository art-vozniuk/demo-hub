import logging
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.common.domain.enums import PipelineStatus
from .models import Pipeline

log = logging.getLogger(__name__)


async def create_pipeline(
    db: AsyncSession,
    pipeline_id: UUID,
    trace_id: UUID,
    pipeline_name: str,
) -> Pipeline:
    pipeline = Pipeline(
        id=pipeline_id,
        trace_id=trace_id,
        pipeline_name=pipeline_name,
        status=PipelineStatus.PENDING,
    )
    db.add(pipeline)
    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    log.info(
        f"[trace_id={trace_id}, pipeline_id={pipeline_id}] "
        f"Pipeline created with status {PipelineStatus.PENDING}"
    )

    return pipeline


async def get_pipelines_by_ids(
    db: AsyncSession,
    pipeline_ids: list[UUID],
) -> list[Pipeline]:
    result = await db.execute(select(Pipeline).where(Pipeline.id.in_(pipeline_ids)))
    return list(result.scalars().all())


async def update_pipeline_status(
    db: AsyncSession,
    pipeline_id: UUID,
    status: PipelineStatus,
    result_url: str | None = None,
    message: str | None = None,
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

    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    log.info(
        f"[trace_id={pipeline.trace_id}, pipeline_id={pipeline_id}] "
        f"Pipeline status updated to {status}"
    )

    return pipeline
