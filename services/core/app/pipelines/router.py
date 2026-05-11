import logging
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status

from services.common.auth.models import User
from services.common.database import DbSession
from services.common.rabbitmq import RabbitMQPublisher, RabbitMQConnection
from services.common.rabbitmq.config import rabbitmq_config
from services.common.redis.rate_limit import rate_limit
from services.core.app.config import config

from .schemas import (
    QueuePipelinesRequest,
    QueuePipelinesResponse,
    PipelineStatusRequest,
    PipelineStatusResponse,
    PipelineStatusItem,
    PipelineEstimateResponse, PipelineJobInput,
)
from . import service
from .estimation import estimate_pipeline
from .input_resolution import resolve_pipeline_input
from .routing import (
    get_routing_key,
    is_parallel_pipeline,
    known_pipeline_names,
    names_in_same_pool,
)
from ..wallet import service as wallet_service

log = logging.getLogger(__name__)

router = APIRouter()


async def get_connection() -> RabbitMQConnection:
    from services.core.app.dependencies import get_rabbitmq_connection

    return await get_rabbitmq_connection()


async def get_publisher() -> pipeline:
    from services.core.app.dependencies import get_rabbitmq_publisher

    return await get_rabbitmq_publisher()


def _get_user_dep():
    from ..dependencies import get_current_user

    return get_current_user

async def _process_pipeline(
        pipeline: PipelineJobInput,
        publisher: RabbitMQPublisher,
        db: DbSession,
        user_uuid: UUID,
        trace_id: UUID
) -> UUID:
    from services.common.logging.config import context_pipeline_id

    pipeline_id = pipeline.pipeline_id
    pipeline_name = pipeline.pipeline_name
    routing_key = get_routing_key(pipeline_name)

    context_pipeline_id.set(str(pipeline_id))

    ptype = await wallet_service.get_pipeline_type(db, pipeline_name)
    if ptype is None:
        # Missing seed row = config drift, not a user error.
        log.error(f"pipeline_types missing seed row for {pipeline_name!r}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pipeline pricing not configured",
        )

    try:
        await wallet_service.charge(
            db,
            pipeline_id=pipeline_id,
            pipeline_type_id=ptype.id,
            cost=ptype.base_cost,
            user_id=user_uuid,
        )
    except wallet_service.InsufficientFunds:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Out of tokens. Contact the site author.",
        )

    log.info(f"Creating pipeline: {pipeline_name} -> {routing_key}")

    await service.create_pipeline(
        db=db,
        pipeline_id=pipeline_id,
        trace_id=trace_id,
        pipeline_name=pipeline_name,
    )

    resolved_input = await resolve_pipeline_input(db, pipeline_name, pipeline.input)

    message = {
        "trace_id": str(trace_id),
        "pipeline_id": str(pipeline_id),
        "pipeline_name": pipeline_name,
        "input": resolved_input,
        "enqueued_at": datetime.utcnow().isoformat(),
    }

    await publisher.publish(
        routing_key=routing_key,
        message=message,
        trace_id=str(trace_id),
        pipeline_id=str(pipeline_id),
    )

    return pipeline_id


@router.post(
    "/queue",
    response_model=QueuePipelinesResponse,
    dependencies=[Depends(rate_limit("queue", config.RATE_LIMIT_QUEUE_PER_MINUTE, 60))],
)
async def queue_pipelines(
    request: QueuePipelinesRequest,
    db: DbSession,
    user: User = Depends(_get_user_dep()),
) -> QueuePipelinesResponse:
    from services.common.logging.config import context_trace_id

    trace_id = request.trace_id
    context_trace_id.set(str(trace_id))

    log.info(f"Received queue request with {len(request.jobs)} jobs")

    if (
        not request.jobs
        or len(request.jobs) == 0
        or len(request.jobs) > config.MAX_PIPELINES_PER_REQUEST
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid number of jobs in request: {len(request.jobs)}. "
            f"Must be between 1 and {config.MAX_PIPELINES_PER_REQUEST}.",
        )

    for job in request.jobs:
        if job.pipeline_name not in known_pipeline_names():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown pipeline_name: {job.pipeline_name!r}",
            )

    user_uuid: UUID = UUID(user.id)
    await wallet_service.grant_signup_if_needed(db, user_uuid)

    publisher = await get_publisher()
    pipeline_ids = [await _process_pipeline(job, publisher, db, user_uuid, trace_id) for job in request.jobs]

    log.info(
        f"Successfully queued {len(pipeline_ids)} pipelines."
    )

    return QueuePipelinesResponse(
        trace_id=trace_id,
        pipeline_ids=pipeline_ids,
        queue_length=0, # not used
    )


@router.post(
    "/status",
    response_model=PipelineStatusResponse,
    dependencies=[
        Depends(rate_limit("status", config.RATE_LIMIT_STATUS_PER_MINUTE, 60))
    ],
)
async def get_pipeline_status(
    request: PipelineStatusRequest,
    db: DbSession,
) -> PipelineStatusResponse:
    pipelines = await service.get_pipelines_by_ids(db, request.pipeline_ids)

    return PipelineStatusResponse(
        pipelines=[PipelineStatusItem.model_validate(p) for p in pipelines]
    )


@router.get(
    "/{pipeline_id}/estimate",
    response_model=PipelineEstimateResponse,
    dependencies=[
        Depends(rate_limit("estimate", config.RATE_LIMIT_STATUS_PER_MINUTE, 60))
    ],
)
async def get_pipeline_estimate(
    pipeline_id: UUID,
    db: DbSession,
) -> PipelineEstimateResponse:
    pipeline = await service.get_pipeline_by_id(db, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )

    pending_by_type = await service.count_pending_ahead_by_type(db, pipeline)
    estimate = await estimate_pipeline(
        pending_by_type,
        target_pipeline_name=pipeline.pipeline_name,
        parallel=is_parallel_pipeline(pipeline.pipeline_name),
        same_pool_names=names_in_same_pool(pipeline.pipeline_name),
    )

    return PipelineEstimateResponse(
        pipeline_id=pipeline_id,
        estimated_seconds=estimate.estimated_seconds,
        queue_position=estimate.queue_position,
        worker_count=estimate.worker_count,
        workers_missing=estimate.workers_missing,
    )
