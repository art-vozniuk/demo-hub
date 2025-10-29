import logging
from typing import Any, Dict
from uuid import UUID

from services.common.rabbitmq import RabbitMQConsumer
from services.common.rabbitmq.config import rabbitmq_config
from services.common.domain.enums import PipelineStatus
from services.common.database.core import async_session_maker
from . import service

from services.common.logging.config import context_trace_id, context_pipeline_id

log = logging.getLogger(__name__)


async def handle_pipeline_update(message: Dict[str, Any]) -> None:
    trace_id = message.get("trace_id")
    pipeline_id = UUID(message["pipeline_id"])
    status = PipelineStatus(message["status"])
    result_url = message.get("result_url")
    error_message = message.get("message")

    context_trace_id.set(str(trace_id))
    context_pipeline_id.set(str(pipeline_id))

    log.info(f"Received pipeline update: status={status}")
    async with async_session_maker() as db:
        await service.update_pipeline_status(
            db=db,
            pipeline_id=pipeline_id,
            status=status,
            result_url=result_url,
            message=error_message,
        )


async def start_pipeline_update_consumer(consumer: RabbitMQConsumer) -> None:
    log.info("Starting pipeline update consumer")
    await consumer.consume(
        queue_name=rabbitmq_config.queue_update,
        callback=handle_pipeline_update,
    )
