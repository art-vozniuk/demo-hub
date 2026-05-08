import logging
from datetime import datetime
from typing import Any, Dict

from services.common.metrics import (
    pipeline_completed_total,
    pipeline_duration_seconds,
    pipeline_in_flight,
    pipeline_queue_wait_seconds,
)
from services.common.rabbitmq import (
    RabbitMQConnection,
    RabbitMQPublisher,
    RabbitMQConsumer,
)
from services.common.rabbitmq.config import rabbitmq_config
from services.common.domain.enums import PipelineStatus
from services.common.s3.client import S3Client

from services.compute.app.pipelines.service import create_service, pipeline_templates
from services.common.logging.config import context_trace_id, context_pipeline_id

log = logging.getLogger(__name__)

rabbitmq_connection: RabbitMQConnection | None = None
rabbitmq_publisher: RabbitMQPublisher | None = None
rabbitmq_consumer: RabbitMQConsumer | None = None
s3_client: S3Client | None = None


async def _publish_pipeline_update(
    trace_id: str,
    pipeline_id: str,
    status: PipelineStatus,
    result_url: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
) -> None:
    if not rabbitmq_publisher:
        raise RuntimeError("Publisher not initialized")

    update_message = {
        "trace_id": trace_id,
        "pipeline_id": pipeline_id,
        "status": status.value,
        "result_url": result_url,
        "message": message,
        "payload": payload,
    }

    await rabbitmq_publisher.publish(
        routing_key=rabbitmq_config.routing_update,
        message=update_message,
        trace_id=trace_id,
        pipeline_id=pipeline_id,
    )


def _classify_error(exc: BaseException) -> str:
    # Keep cardinality low — bucket exceptions into a small set of well-known
    # kinds; everything else falls into "unknown".
    name = type(exc).__name__
    msg = str(exc).lower()
    if "no faces detected" in msg or "no face" in msg:
        return "no_face"
    if "modulenotfounderror" == name.lower() or "import" in msg:
        return "import"
    if "model" in msg and ("load" in msg or "download" in msg):
        return "model"
    if "s3" in msg or "contentlength" in msg or "clientpayloaderror" in name.lower():
        return "s3"
    if "rabbit" in msg:
        return "rabbitmq"
    return "unknown"


async def _process_pipeline(message: Dict[str, Any]) -> None:
    import time

    t0 = time.perf_counter()

    trace_id = message["trace_id"]
    pipeline_id = message["pipeline_id"]
    pipeline_name = message["pipeline_name"]
    pipeline_input_dict = message["input"]
    enqueued_at_iso = message.get("enqueued_at")

    context_trace_id.set(str(trace_id))
    context_pipeline_id.set(str(pipeline_id))

    log.info(f"Processing pipeline: {pipeline_name}, trace_id: {trace_id}")

    # Time spent waiting in RabbitMQ (core enqueued → compute picked up).
    # If clocks drift between core and compute the value can land
    # slightly negative — clamp to 0 so the histogram stays sane.
    if enqueued_at_iso:
        try:
            enq = datetime.fromisoformat(enqueued_at_iso)
            wait = max(0.0, (datetime.utcnow() - enq).total_seconds())
            pipeline_queue_wait_seconds.labels(pipeline_name=pipeline_name).observe(
                wait
            )
        except ValueError:
            pass

    pipeline_in_flight.labels(pipeline_name=pipeline_name).inc()
    status_label = "completed"
    error_kind_label = ""

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
        results = await service.run()
        log.info(
            f"_process_pipeline service.run took {(time.perf_counter() - t1) * 1000:.1f}ms"
        )

        result_url = results.get("url")
        payload = results.get("payload")

        await _publish_pipeline_update(
            trace_id=trace_id,
            pipeline_id=pipeline_id,
            status=PipelineStatus.COMPLETED,
            result_url=result_url,
            message="success",
            payload=payload,
        )

        log.info(
            f"_process_pipeline: TOTAL took {(time.perf_counter() - t0) * 1000:.1f}ms"
        )
        log.info(
            f"Pipeline completed successfully: {pipeline_name}, trace_id: {trace_id} pipeline_id: {pipeline_id}"
        )

    except Exception as e:
        status_label = "failed"
        error_kind_label = _classify_error(e)
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

    finally:
        pipeline_in_flight.labels(pipeline_name=pipeline_name).dec()
        duration = time.perf_counter() - t0
        pipeline_duration_seconds.labels(
            pipeline_name=pipeline_name, status=status_label
        ).observe(duration)
        pipeline_completed_total.labels(
            pipeline_name=pipeline_name,
            status=status_label,
            error_kind=error_kind_label,
        ).inc()


async def init() -> None:
    global rabbitmq_connection, rabbitmq_publisher, rabbitmq_consumer, s3_client

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

    log.info("Pipeline router initialized successfully")


async def shutdown() -> None:
    global rabbitmq_connection, rabbitmq_consumer

    log.info("Shutting down pipeline router")

    if rabbitmq_consumer:
        await rabbitmq_consumer.stop()

    if rabbitmq_connection:
        await rabbitmq_connection.close()

    log.info("Pipeline router shutdown complete")
