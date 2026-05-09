import asyncio
import logging
import os
import socket
import time
import uuid
from typing import Any, Dict

from services.common.rabbitmq import (
    RabbitMQConnection,
    RabbitMQPublisher,
    RabbitMQConsumer,
)
from services.common.rabbitmq.config import rabbitmq_config
from services.common.domain.enums import PipelineStatus
from services.common.redis import close_redis_client
from services.common.s3.client import S3Client

from services.compute.app.pipelines.service import create_service, pipeline_templates
from services.compute.app.pipelines import heartbeat
from services.common.logging.config import context_trace_id, context_pipeline_id

log = logging.getLogger(__name__)

rabbitmq_connection: RabbitMQConnection | None = None
rabbitmq_publisher: RabbitMQPublisher | None = None
rabbitmq_consumer: RabbitMQConsumer | None = None
s3_client: S3Client | None = None

_worker_id: str = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
_heartbeat_task: asyncio.Task | None = None
_heartbeat_stop: asyncio.Event | None = None


async def _publish_pipeline_update(
    trace_id: str,
    pipeline_id: str,
    status: PipelineStatus,
    result: dict | None = None,
    message: str | None = None,
) -> None:
    if not rabbitmq_publisher:
        raise RuntimeError("Publisher not initialized")

    update_message = {
        "trace_id": trace_id,
        "pipeline_id": pipeline_id,
        "status": status.value,
        "result": result,
        "message": message,
    }

    await rabbitmq_publisher.publish(
        routing_key=rabbitmq_config.routing_update,
        message=update_message,
        trace_id=trace_id,
        pipeline_id=pipeline_id,
    )


async def _process_pipeline(message: Dict[str, Any]) -> None:
    t0 = time.perf_counter()

    trace_id = message["trace_id"]
    pipeline_id = message["pipeline_id"]
    pipeline_name = message["pipeline_name"]
    pipeline_input_dict = message["input"]

    context_trace_id.set(str(trace_id))
    context_pipeline_id.set(str(pipeline_id))

    log.info(f"Processing pipeline: {pipeline_name}, trace_id: {trace_id}")

    try:
        await _publish_pipeline_update(
            trace_id=trace_id,
            pipeline_id=pipeline_id,
            status=PipelineStatus.RUNNING,
        )

        service = create_service(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            pipeline_input=pipeline_input_dict,
            s3_client=s3_client,
        )

        log.info(
            f"Running pipeline: {pipeline_name}, trace_id: {trace_id}, input: {pipeline_input_dict}"
        )
        t1 = time.perf_counter()
        result = await service.run()
        log.info(
            f"_process_pipeline service.run took {(time.perf_counter() - t1) * 1000:.1f}ms"
        )

        await _publish_pipeline_update(
            trace_id=trace_id,
            pipeline_id=pipeline_id,
            status=PipelineStatus.COMPLETED,
            result=result,
            message="success",
        )

        duration_ms = (time.perf_counter() - t0) * 1000.0
        heartbeat.record_success(pipeline_name, duration_ms)
        log.info(f"_process_pipeline: TOTAL took {duration_ms:.1f}ms")
        log.info(
            f"Pipeline completed successfully: {pipeline_name}, trace_id: {trace_id} pipeline_id: {pipeline_id}"
        )

    except Exception as e:
        error_message = str(e)
        log.error(
            f"Pipeline failed: {error_message}, trace_id: {trace_id} pipeline_id: {pipeline_id}",
            exc_info=True,
        )

        await _publish_pipeline_update(
            trace_id=trace_id,
            pipeline_id=pipeline_id,
            status=PipelineStatus.FAILED,
            message=error_message,
        )


async def init() -> None:
    global rabbitmq_connection, rabbitmq_publisher, rabbitmq_consumer, s3_client
    global _heartbeat_task, _heartbeat_stop

    log.info("Initializing pipeline router")

    rabbitmq_connection = RabbitMQConnection(rabbitmq_config)
    await rabbitmq_connection.connect()
    await rabbitmq_connection.declare_topology()

    rabbitmq_publisher = RabbitMQPublisher(rabbitmq_connection, rabbitmq_config)
    rabbitmq_consumer = RabbitMQConsumer(rabbitmq_connection, rabbitmq_config)

    await rabbitmq_consumer.consume(
        queue_name=rabbitmq_config.queue_main,
        callback=_process_pipeline,
    )

    s3_client = S3Client()
    for template in pipeline_templates.values():
        await template.service_type.initialize(s3_client)

    log.info(f"Starting worker heartbeat loop, worker_id={_worker_id}")
    _heartbeat_stop = asyncio.Event()
    _heartbeat_task = asyncio.create_task(heartbeat.run_loop(_worker_id, _heartbeat_stop))

    log.info("Pipeline router initialized successfully")


async def shutdown() -> None:
    global rabbitmq_connection, rabbitmq_consumer, _heartbeat_task, _heartbeat_stop

    log.info("Shutting down pipeline router")

    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
    if _heartbeat_task:
        try:
            await _heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass
        _heartbeat_task = None
    _heartbeat_stop = None

    await close_redis_client()

    if rabbitmq_consumer:
        await rabbitmq_consumer.stop()

    if rabbitmq_connection:
        await rabbitmq_connection.close()

    log.info("Pipeline router shutdown complete")
