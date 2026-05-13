import logging
from datetime import timedelta
from uuid import UUID
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.common.domain.enums import PipelineStatus
from ..wallet.models import PipelineType
from .models import Pipeline

log = logging.getLogger(__name__)

# PENDING rows older than this relative to the requested pipeline are
# treated as orphaned (e.g. left behind by crashed workers) and excluded
# from queue-position counting.
STALE_PENDING_AGE_SECONDS = 300


async def create_pipeline(
    db: AsyncSession,
    pipeline_id: UUID,
    trace_id: UUID,
    pipeline_name: str,
    input: dict | None = None,
    user_id: UUID | None = None,
) -> Pipeline:
    pipeline = Pipeline(
        id=pipeline_id,
        trace_id=trace_id,
        user_id=user_id,
        pipeline_name=pipeline_name,
        status=PipelineStatus.PENDING,
        input=input,
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


def _user_history_stmt(user_id: UUID):
    # Only types flagged as user-facing show up in /pipelines/mine.
    # face_recognition is hidden because it is a building block of other
    # flows rather than something the user thinks of as their own run.
    return (
        select(Pipeline)
        .join(PipelineType, PipelineType.name == Pipeline.pipeline_name)
        .where(Pipeline.user_id == user_id)
        .where(PipelineType.visible_in_user_history.is_(True))
    )


async def list_pipelines_for_user(
    db: AsyncSession,
    user_id: UUID,
    limit: int,
    offset: int,
) -> list[Pipeline]:
    stmt = (
        _user_history_stmt(user_id)
        .order_by(Pipeline.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_pipelines_for_user(db: AsyncSession, user_id: UUID) -> int:
    stmt = (
        select(func.count(Pipeline.id))
        .join(PipelineType, PipelineType.name == Pipeline.pipeline_name)
        .where(Pipeline.user_id == user_id)
        .where(PipelineType.visible_in_user_history.is_(True))
    )
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def get_pipeline_by_id(
    db: AsyncSession,
    pipeline_id: UUID,
) -> Pipeline | None:
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    return result.scalar_one_or_none()


async def count_pending_ahead_by_type(
    db: AsyncSession,
    pipeline: Pipeline,
) -> dict[str, int]:
    # Count in-flight pipelines (PENDING or RUNNING) created at-or-before
    # the given pipeline, grouped by pipeline_name. RUNNING is included
    # because a worker grabs a message and commits PENDING→RUNNING within
    # tens of ms — the frontend's /estimate call routinely arrives after
    # that flip. Restricted to a bounded recent window so orphaned rows
    # from crashed workers don't inflate the queue. The pipeline itself
    # is always included while not in a terminal state.
    cutoff = pipeline.created_at - timedelta(seconds=STALE_PENDING_AGE_SECONDS)
    stmt = (
        select(Pipeline.pipeline_name, func.count(Pipeline.id))
        .where(Pipeline.status.in_([PipelineStatus.PENDING, PipelineStatus.RUNNING]))
        .where(
            or_(
                and_(
                    Pipeline.created_at <= pipeline.created_at,
                    Pipeline.created_at >= cutoff,
                ),
                Pipeline.id == pipeline.id,
            )
        )
        .group_by(Pipeline.pipeline_name)
    )
    result = await db.execute(stmt)
    return {name: int(count) for name, count in result.all()}


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
