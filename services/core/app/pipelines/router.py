import logging
from datetime import datetime
from fastapi import APIRouter, Depends

from services.common.database import DbSession
from services.common.rabbitmq import RabbitMQPublisher, RabbitMQConnection
from services.common.rabbitmq.config import rabbitmq_config
from services.common.redis import rate_limit
from services.common.auth import User
from services.core.app.dependencies import get_current_user
from services.core.app.config import config

from .schemas import (
    QueuePipelinesRequest,
    QueuePipelinesResponse,
    PipelineStatusRequest,
    PipelineStatusResponse,
    PipelineStatusItem,
)
from . import service

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
    dependencies=[
        Depends(
            rate_limit(
                "queue",
                config.RATE_LIMIT_QUEUE_PER_MINUTE,
                60,
                get_current_user,
                config.TEST_USER_EMAIL,
            )
        )
    ],
)
async def queue_pipelines(
    request: QueuePipelinesRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> QueuePipelinesResponse:
    trace_id = request.trace_id
    log.info(
        f"[user={current_user.id}] [trace_id={trace_id}] "
        f"Received queue request with {len(request.jobs)} jobs"
    )

    if (
        not request.jobs
        or len(request.jobs) == 0
        or len(request.jobs) > config.MAX_PIPELINES_PER_REQUEST
    ):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid number of jobs in request: {len(request.jobs)}. "
            f"Must be between 1 and {config.MAX_PIPELINES_PER_REQUEST}.",
        )

    connection = await get_connection()
    queue_length = await connection.get_queue_length(rabbitmq_config.queue_main)

    pipeline_ids = []
    publisher = await get_publisher()

    for job in request.jobs:
        pipeline_id = job.pipeline_id
        pipeline_name = job.pipeline_name

        log.info(
            f"[trace_id={trace_id}, pipeline_id={pipeline_id}] "
            f"Creating pipeline: {pipeline_name}"
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
            routing_key=rabbitmq_config.routing_submit,
            message=message,
            trace_id=str(trace_id),
            pipeline_id=str(pipeline_id),
        )

        pipeline_ids.append(pipeline_id)

    log.info(
        f"[trace_id={trace_id}] Successfully queued {len(pipeline_ids)} pipelines, queue_length={queue_length}"
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
        Depends(
            rate_limit(
                "status",
                config.RATE_LIMIT_STATUS_PER_MINUTE,
                60,
                get_current_user,
                config.TEST_USER_EMAIL,
            )
        )
    ],
)
async def get_pipeline_status(
    request: PipelineStatusRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> PipelineStatusResponse:
    pipelines = await service.get_pipelines_by_ids(db, request.pipeline_ids)

    return PipelineStatusResponse(
        pipelines=[PipelineStatusItem.model_validate(p) for p in pipelines]
    )
