import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from services.common.rabbitmq import RabbitMQConsumer
from services.common.rabbitmq.config import rabbitmq_config
from services.common.domain.enums import PipelineStatus
from services.common.database.core import async_session_maker
from . import service
from ..wallet import service as wallet_service

from services.common.logging.config import context_pipeline_id

log = logging.getLogger(__name__)

_TERMINAL = {PipelineStatus.COMPLETED, PipelineStatus.FAILED}


def _observe_e2e(pipeline, status: PipelineStatus) -> None:
    """User-perceived latency: row creation (queue POST) → terminal status."""

    from services.common.observability.metrics import pipeline_e2e_seconds

    created_at = getattr(pipeline, "created_at", None)
    if created_at is None:
        return
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
    pipeline_e2e_seconds.labels(
        pipeline_name=pipeline.pipeline_name, status=status.value
    ).observe(max(elapsed, 0.0))


async def handle_pipeline_update(message: Dict[str, Any]) -> None:
    pipeline_id = UUID(message["pipeline_id"])
    status = PipelineStatus(message["status"])
    result = message.get("result")
    error_message = message.get("message")

    context_pipeline_id.set(str(pipeline_id))

    log.info(f"Received pipeline update: status={status}")
    async with async_session_maker() as db:
        pipeline = await service.update_pipeline_status(
            db=db,
            pipeline_id=pipeline_id,
            status=status,
            result=result,
            message=error_message,
        )

        if pipeline is not None and status in _TERMINAL:
            _observe_e2e(pipeline, status)

        # Refund on terminal failure; idempotent if message redelivers.
        if status == PipelineStatus.FAILED:
            await wallet_service.refund(db, pipeline_id)
            await db.commit()


async def start_pipeline_update_consumer(consumer: RabbitMQConsumer) -> None:
    log.info("Starting pipeline update consumer")
    await consumer.consume(
        queue_name=rabbitmq_config.queue_update,
        callback=handle_pipeline_update,
    )
