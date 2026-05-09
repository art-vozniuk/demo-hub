import logging
from typing import Any, Dict

from services.common.rabbitmq import (
    RabbitMQConnection,
    RabbitMQPublisher,
    RabbitMQConsumer,
)
from services.common.rabbitmq.config import rabbitmq_config
from services.common.domain.enums import PipelineStatus
from services.common.s3.client import S3Client
from services.common.redis import (
    WorkerHeartbeat,
    track_pipeline_run,
)
from services.common.logging.config import context_trace_id, context_pipeline_id

from services.dispatch.app.pipelines.service import (
    create_service,
    pipeline_templates,
)

log = logging.getLogger(__name__)

rabbitmq_connection: RabbitMQConnection | None = None
rabbitmq_publisher: RabbitMQPublisher | None = None
rabbitmq_consumer: RabbitMQConsumer | None = None
s3_client: S3Client | None = None
heartbeat: WorkerHeartbeat | None = None


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
    trace_id = message["trace_id"]
    pipeline_id = message["pipeline_id"]
    pipeline_name = message["pipeline_name"]
    pipeline_input_dict = message["input"]

    context_trace_id.set(str(trace_id))
    context_pipeline_id.set(str(pipeline_id))

    log.info(f"Dispatch processing pipeline: {pipeline_name}")

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

        async with track_pipeline_run(
            pipeline_id=pipeline_id, pipeline_name=pipeline_name
        ):
            result = await service.run()

        await _publish_pipeline_update(
            trace_id=trace_id,
            pipeline_id=pipeline_id,
            status=PipelineStatus.COMPLETED,
            result=result,
            message="success",
        )

        log.info(f"Pipeline completed: {pipeline_name} pipeline_id={pipeline_id}")

    except Exception as e:
        error_message = str(e)
        log.error(
            f"Pipeline failed: {error_message} pipeline_id={pipeline_id}",
            exc_info=True,
        )

        await _publish_pipeline_update(
            trace_id=trace_id,
            pipeline_id=pipeline_id,
            status=PipelineStatus.FAILED,
            message=error_message,
        )


async def init() -> None:
    global rabbitmq_connection, rabbitmq_publisher, rabbitmq_consumer
    global s3_client, heartbeat

    log.info("Initializing dispatch pipeline router")

    rabbitmq_connection = RabbitMQConnection(rabbitmq_config)
    await rabbitmq_connection.connect()
    await rabbitmq_connection.declare_topology()

    rabbitmq_publisher = RabbitMQPublisher(rabbitmq_connection, rabbitmq_config)
    # Dispatch is IO-bound; allow more concurrent in-flight Modal calls than
    # compute does. Modal queues server-side, so there's no benefit in
    # capping client-side beyond a sane upper bound.
    rabbitmq_consumer = RabbitMQConsumer(
        rabbitmq_connection, rabbitmq_config, max_concurrent_tasks=50
    )

    await rabbitmq_consumer.consume(
        queue_name=rabbitmq_config.queue_dispatch,
        callback=_process_pipeline,
    )

    s3_client = S3Client()
    for template in pipeline_templates.values():
        await template.service_type.initialize(s3_client)

    heartbeat = WorkerHeartbeat(pool="dispatch")
    await heartbeat.start()

    log.info("Dispatch pipeline router initialized successfully")


async def shutdown() -> None:
    global rabbitmq_connection, rabbitmq_consumer, heartbeat

    log.info("Shutting down dispatch pipeline router")

    if heartbeat:
        await heartbeat.stop()

    if rabbitmq_consumer:
        await rabbitmq_consumer.stop()

    if rabbitmq_connection:
        await rabbitmq_connection.close()

    log.info("Dispatch pipeline router shutdown complete")
