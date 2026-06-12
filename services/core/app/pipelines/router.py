import logging
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status

from services.common.auth.models import User
from services.common.database import DbSession
from services.common.observability.tracing import span, trace_headers
from services.common.rabbitmq import RabbitMQPublisher, RabbitMQConnection
from services.common.redis.rate_limit import rate_limit
from services.core.app.config import config

from .schemas import (
    CostPreviewRequest,
    CostPreviewResponse,
    QueuePipelinesRequest,
    QueuePipelinesResponse,
    PipelineStatusRequest,
    PipelineStatusResponse,
    PipelineStatusItem,
    PipelineEstimateResponse,
    PipelineJobInput,
    PublicPipelineResponse,
    UserPipelineItem,
    UserPipelinesResponse,
)
from . import service
from .cost_resolution import resolve_cost
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


async def get_publisher() -> RabbitMQPublisher:
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
    trace_id: UUID,
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

    final_cost = await resolve_cost(
        db=db,
        pipeline_type_id=ptype.id,
        base_cost=ptype.base_cost,
        pipeline_input=pipeline.input,
    )

    try:
        await wallet_service.charge(
            db,
            pipeline_id=pipeline_id,
            pipeline_type_id=ptype.id,
            cost=final_cost,
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
        input=pipeline.input,
        user_id=user_uuid,
    )

    resolved_input = await resolve_pipeline_input(db, pipeline_name, pipeline.input)

    message = {
        "pipeline_id": str(pipeline_id),
        "pipeline_name": pipeline_name,
        "input": resolved_input,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
        # Sentry trace context — dispatch resumes it.
        **trace_headers(),
    }

    with span("queue.publish", routing_key):
        await publisher.publish(routing_key=routing_key, message=message)

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
    # Client-generated batch id, stored for grouping; Sentry owns tracing.
    trace_id = request.trace_id

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
    pipeline_ids = [
        await _process_pipeline(job, publisher, db, user_uuid, trace_id)
        for job in request.jobs
    ]

    log.info(f"Successfully queued {len(pipeline_ids)} pipelines.")

    return QueuePipelinesResponse(
        trace_id=trace_id,
        pipeline_ids=pipeline_ids,
        queue_length=0,  # not used
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
    _observe_status_delivery(pipelines)

    return PipelineStatusResponse(
        pipelines=[PipelineStatusItem.model_validate(p) for p in pipelines]
    )


def _observe_status_delivery(pipelines) -> None:
    """Terminal status in DB → client fetched it: frontend poll-interval
    sanity check. The window guards against gallery re-reads of old rows."""

    from services.common.observability.metrics import status_delivery_lag_seconds

    now = datetime.now(timezone.utc)
    for p in pipelines:
        status_val = getattr(p.status, "value", p.status)
        if status_val not in ("COMPLETED", "FAILED"):
            continue
        updated_at = getattr(p, "updated_at", None)
        if updated_at is None:
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        lag = (now - updated_at).total_seconds()
        if 0 <= lag < 300:
            status_delivery_lag_seconds.labels(pipeline_name=p.pipeline_name).observe(
                lag
            )
            log.info(
                f"terminal status delivered to client {lag * 1000:.0f}ms "
                f"after completion [pipeline_id={p.id}]"
            )


@router.get(
    "/mine",
    response_model=UserPipelinesResponse,
    dependencies=[Depends(rate_limit("mine", config.RATE_LIMIT_STATUS_PER_MINUTE, 60))],
)
async def list_my_pipelines(
    db: DbSession,
    user: User = Depends(_get_user_dep()),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> UserPipelinesResponse:
    user_uuid: UUID = UUID(user.id)
    pipelines = await service.list_pipelines_for_user(
        db, user_uuid, limit=limit, offset=offset
    )
    total = await service.count_pipelines_for_user(db, user_uuid)
    return UserPipelinesResponse(
        pipelines=[UserPipelineItem.model_validate(p) for p in pipelines],
        total=total,
        limit=limit,
        offset=offset,
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


@router.get(
    "/{pipeline_id}/public",
    response_model=PublicPipelineResponse,
    dependencies=[
        Depends(rate_limit("public", config.RATE_LIMIT_STATUS_PER_MINUTE, 60))
    ],
)
async def get_public_pipeline(
    pipeline_id: UUID,
    db: DbSession,
) -> PublicPipelineResponse:
    """Read-only view of a pipeline for the /p/:id share page.
    Unauthenticated: anyone with the (unguessable) UUID can fetch it.
    Mirrors how the result image URLs themselves are already public."""
    pipeline = await service.get_pipeline_by_id(db, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found",
        )
    return PublicPipelineResponse.model_validate(pipeline)


@router.post(
    "/cost-preview",
    response_model=CostPreviewResponse,
    dependencies=[
        Depends(rate_limit("cost_preview", config.RATE_LIMIT_STATUS_PER_MINUTE, 60))
    ],
)
async def preview_cost(
    request: CostPreviewRequest,
    db: DbSession,
) -> CostPreviewResponse:
    """Resolve the final cost for the given input without queuing. The
    actual queue endpoint re-resolves at charge time, so this is
    advisory only."""

    if request.pipeline_name not in known_pipeline_names():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown pipeline_name: {request.pipeline_name!r}",
        )

    ptype = await wallet_service.get_pipeline_type(db, request.pipeline_name)
    if ptype is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Pipeline pricing not configured",
        )

    cost = await resolve_cost(
        db=db,
        pipeline_type_id=ptype.id,
        base_cost=ptype.base_cost,
        pipeline_input=request.input,
    )
    return CostPreviewResponse(
        pipeline_name=request.pipeline_name,
        base_cost=ptype.base_cost,
        cost=cost,
    )
