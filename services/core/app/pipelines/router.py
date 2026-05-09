import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status

from services.common.database import DbSession
from services.common.rabbitmq import RabbitMQPublisher, RabbitMQConnection
from services.common.rabbitmq.config import rabbitmq_config
from services.common.redis import rate_limit
from services.core.app.config import config

from .schemas import (
    QueuePipelinesRequest,
    QueuePipelinesResponse,
    PipelineStatusRequest,
    PipelineStatusResponse,
    PipelineStatusItem,
)
from . import service
from .routing import get_route, known_pipeline_names
from .eta import estimate_seconds

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
        # `queue_length` here is the legacy compute-queue gauge — kept for
        # backwards compatibility with the existing FaceSwap UI. Per-pipeline
        # ETAs (the actual UX signal) come from /status.
        queue_length = await connection.get_queue_length(rabbitmq_config.queue_main)

        pipeline_ids = []
        publisher = await get_publisher()

        for job in request.jobs:
            pipeline_id = job.pipeline_id
            pipeline_name = job.pipeline_name

            context_pipeline_id.set(str(pipeline_id))
            route = get_route(pipeline_name)

            log.info(
                f"Creating pipeline: {pipeline_name} -> routing_key={route.routing_key}"
            )

            await service.create_pipeline(
                db=db,
                pipeline_id=pipeline_id,
                trace_id=trace_id,
                pipeline_name=pipeline_name,
            )

            message = {
                "trace_id": str(trace_id),
                "pipeline_id": str(pipeline_id),
                "pipeline_name": pipeline_name,
                "input": job.input,
                "enqueued_at": datetime.utcnow().isoformat(),
            }

            await publisher.publish(
                routing_key=route.routing_key,
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


def _peers_for_pool(pipeline_name: str) -> list[str]:
    target = get_route(pipeline_name)
    return [
        name for name in known_pipeline_names() if get_route(name).pool == target.pool
    ]


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

    items: list[PipelineStatusItem] = []
    for p in pipelines:
        try:
            position = await service.queue_position_for_pipeline(
                db, p, _peers_for_pool(p.pipeline_name)
            )
        except ValueError:
            # Pipeline name not in the routing table (legacy row); skip ETA
            # rather than failing the whole status response.
            position = 0

        try:
            eta = await estimate_seconds(
                pipeline_id=str(p.id),
                pipeline_name=p.pipeline_name,
                status=p.status,
                queue_position=position,
            )
        except Exception as e:
            log.warning(f"ETA estimation failed for {p.id}: {e}")
            eta = None

        items.append(
            PipelineStatusItem(
                id=p.id,
                pipeline_name=p.pipeline_name,
                status=p.status,
                message=p.message,
                result=p.result,
                eta_seconds=eta,
            )
        )

    return PipelineStatusResponse(pipelines=items)
