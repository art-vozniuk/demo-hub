import logging
from uuid import UUID

from sqlalchemy import select, and_
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

    log.info(f"Pipeline created with status {PipelineStatus.PENDING}")

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
    result: dict | None = None,
    message: str | None = None,
) -> Pipeline | None:
    db_result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = db_result.scalar_one_or_none()

    if not pipeline:
        return None

    pipeline.status = status

    if result is not None:
        pipeline.result = result

    if message is not None:
        pipeline.message = message

    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    log.info(f"Pipeline status updated to {status}")

    return pipeline


async def queue_position_for_pipeline(
    db: AsyncSession,
    pipeline: Pipeline,
    pipeline_names: list[str],
) -> int:
    """Count PENDING pipelines in the same pool that were enqueued earlier.

    Pool membership is approximated via the list of pipeline_names that
    share the route (caller resolves it). Position is 0-based: the
    pipeline at the head of the queue gets 0.
    """

    if pipeline.status != PipelineStatus.PENDING:
        return 0

    stmt = select(Pipeline).where(
        and_(
            Pipeline.status == PipelineStatus.PENDING,
            Pipeline.pipeline_name.in_(pipeline_names),
            Pipeline.created_at < pipeline.created_at,
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return len(rows)
