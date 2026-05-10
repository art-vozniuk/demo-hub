import logging
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status

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
    PipelineEstimateResponse,
)
from . import service
from .estimation import estimate_pipeline
from .input_resolution import resolve_pipeline_input
from .routing import get_routing_key, known_pipeline_names

log = logging.getLogger(__name__)

router = APIRouter()


async def get_connection() -> RabbitMQConnection:
    from services.core.app.dependencies import get_rabbitmq_connection

    return await get_rabbitmq_connection()


async def get_publisher() -> RabbitMQPublisher:
    from services.core.app.dependencies import get_rabbitmq_publisher

    return await get_rabbitmq_publisher()


@router.post(
    "/queue",
    response_model=QueuePipelinesResponse,
    dependencies=[Depends(rate_limit("queue", config.RATE_LIMIT_QUEUE_PER_MINUTE, 60))],
)
async def queue_pipelines(
    request: QueuePipelinesRequest,
    db: DbSession,
) -> QueuePipelinesResponse:
    import sentry_sdk
    from services.common.logging.config import (
        context_trace_id,
        context_pipeline_id,
    )

    trace_id = request.trace_id

    context_trace_id.set(str(trace_id))

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("trace_id", str(trace_id))
        scope.set_context(
            "request",
            {
                "trace_id": str(trace_id),
                "jobs_count": len(request.jobs),
            },
        )

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

        connection = await get_connection()
        # Legacy gauge — only counts the compute pool. Per-pipeline ETAs
        # via /pipelines/{id}/estimate are the actual UX signal.
        queue_length = await connection.get_queue_length(rabbitmq_config.queue_main)

        pipeline_ids = []
        publisher = await get_publisher()

        for job in request.jobs:
            pipeline_id = job.pipeline_id
            pipeline_name = job.pipeline_name
            routing_key = get_routing_key(pipeline_name)

            context_pipeline_id.set(str(pipeline_id))

            log.info(f"Creating pipeline: {pipeline_name} -> {routing_key}")

            await service.create_pipeline(
                db=db,
                pipeline_id=pipeline_id,
                trace_id=trace_id,
                pipeline_name=pipeline_name,
            )

            resolved_input = await resolve_pipeline_input(db, pipeline_name, job.input)

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

            pipeline_ids.append(pipeline_id)

        log.info(
            f"Successfully queued {len(pipeline_ids)} pipelines, queue_length={queue_length}"
        )

        return QueuePipelinesResponse(
            trace_id=trace_id,
            pipeline_ids=pipeline_ids,
            queue_length=queue_length,
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
    estimate = await estimate_pipeline(pending_by_type)

    return PipelineEstimateResponse(
        pipeline_id=pipeline_id,
        estimated_seconds=estimate.estimated_seconds,
        queue_position=estimate.queue_position,
        worker_count=estimate.worker_count,
        workers_missing=estimate.workers_missing,
    )
