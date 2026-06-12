"""Bootstrap and lifecycle for a worker that consumes pipeline jobs off
RabbitMQ, runs them through a pipeline-template registry, and publishes
status updates back to core.

Compute and dispatch share this whole loop — only their queue name,
pool name, template dict, and `create_service` factory differ.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from services.common.domain.enums import PipelineStatus
from services.common.logging.config import context_pipeline_id
from services.common.observability.tracing import continue_trace_from
from services.common.rabbitmq.connection import RabbitMQConnection
from services.common.rabbitmq.consumer import RabbitMQConsumer
from services.common.rabbitmq.publisher import RabbitMQPublisher
from services.common.rabbitmq.config import rabbitmq_config
from services.common.redis import close_redis_client
from services.common.redis import heartbeat as _hb
from services.common.s3.client import S3Client


# Default ceiling on concurrent in-flight tasks per worker. Dispatch
# (pure async I/O, no model in process) can take 256 easily on an 8GB
# VPS; compute (face_swap on local CPU with the GAN loaded) should not.
# Each worker overrides through WORKER_MAX_CONCURRENT_TASKS in its env.
_DEFAULT_MAX_CONCURRENT_TASKS = int(os.getenv("WORKER_MAX_CONCURRENT_TASKS", "50"))


class _ServiceLike(Protocol):
    last_inference_ms: float

    async def run(self) -> dict[str, Any]: ...


class _PipelineTemplateLike(Protocol):
    service_type: Any
    estimated_time_ms: int


CreateService = Callable[[str, str, dict, S3Client], _ServiceLike]


class PipelineWorker:
    def __init__(
        self,
        *,
        pool_name: str,
        queue_name: str,
        pipeline_templates: Mapping[str, _PipelineTemplateLike],
        create_service: CreateService,
        max_concurrent_tasks: int | None = None,
    ) -> None:
        if max_concurrent_tasks is None:
            max_concurrent_tasks = _DEFAULT_MAX_CONCURRENT_TASKS
        self._pool_name = pool_name
        self._queue_name = queue_name
        self._templates = pipeline_templates
        self._create_service = create_service
        self._max_concurrent_tasks = max_concurrent_tasks

        self._worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._log = logging.getLogger(f"pipeline_worker.{pool_name}")

        self._connection: RabbitMQConnection | None = None
        self._publisher: RabbitMQPublisher | None = None
        self._consumer: RabbitMQConsumer | None = None
        self._s3: S3Client | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_stop: asyncio.Event | None = None

    def _snapshot(self) -> Mapping[str, int]:
        return {n: t.estimated_time_ms for n, t in self._templates.items()}

    def _record_success(self, pipeline_name: str, duration_ms: float) -> None:
        template = self._templates.get(pipeline_name)
        if template is None:
            return
        # Mutated in place so the next heartbeat tick picks up the new value.
        template.estimated_time_ms = max(int(round(duration_ms)), 1)

    async def _publish_update(
        self,
        pipeline_id: str,
        status: PipelineStatus,
        result: dict | None = None,
        message: str | None = None,
    ) -> None:
        if self._publisher is None:
            raise RuntimeError("Publisher not initialized")

        await self._publisher.publish(
            routing_key=rabbitmq_config.routing_update,
            message={
                "pipeline_id": pipeline_id,
                "status": status.value,
                "result": result,
                "message": message,
            },
        )

    @staticmethod
    def _queue_wait_seconds(message: Mapping[str, Any]) -> float | None:
        """Time the job sat in RabbitMQ. Core and workers run on the same
        host, so wall-clock comparison is safe."""

        enqueued_at = message.get("enqueued_at")
        if not enqueued_at:
            return None
        try:
            enqueued = datetime.fromisoformat(enqueued_at)
            if enqueued.tzinfo is None:
                enqueued = enqueued.replace(tzinfo=timezone.utc)
            return max((datetime.now(timezone.utc) - enqueued).total_seconds(), 0.0)
        except ValueError:
            return None

    async def _process(self, message: dict[str, Any]) -> None:
        # Imported lazily so the metric registration doesn't happen for
        # processes that don't import this module (e.g. unit tests that
        # only exercise routing).
        from services.common.observability.metrics import (
            pipeline_duration_seconds,
            pipeline_failures_total,
            queue_wait_seconds,
        )

        t0 = time.perf_counter()

        pipeline_id = message["pipeline_id"]
        pipeline_name = message["pipeline_name"]
        pipeline_input = message["input"]

        context_pipeline_id.set(str(pipeline_id))

        wait_s = self._queue_wait_seconds(message)
        if wait_s is not None:
            queue_wait_seconds.labels(pipeline_name=pipeline_name).observe(wait_s)

        self._log.info(
            f"Processing pipeline: {pipeline_name}"
            + (f" (queued {wait_s * 1000:.0f}ms)" if wait_s is not None else "")
        )

        with continue_trace_from(
            message,
            op="queue.task",
            name=f"pipeline.{pipeline_name}",
            tags={"pipeline_id": str(pipeline_id), "pipeline_name": pipeline_name},
        ):
            try:
                await self._publish_update(pipeline_id, PipelineStatus.RUNNING)

                service = self._create_service(
                    pipeline_id, pipeline_name, pipeline_input, self._s3
                )
                result = await service.run()

                await self._publish_update(
                    pipeline_id,
                    PipelineStatus.COMPLETED,
                    result=result,
                    message="success",
                )

                self._record_success(pipeline_name, service.last_inference_ms)
                duration_s = time.perf_counter() - t0
                pipeline_duration_seconds.labels(pipeline_name=pipeline_name).observe(
                    duration_s
                )
                self._log.info(
                    f"Pipeline completed: {pipeline_name} pipeline_id={pipeline_id} "
                    f"total={duration_s * 1000:.1f}ms heartbeat={service.last_inference_ms:.1f}ms"
                )

            except Exception as e:
                error_message = str(e)
                pipeline_failures_total.labels(
                    pipeline_name=pipeline_name, error_type=type(e).__name__
                ).inc()
                self._log.error(
                    f"Pipeline failed: {error_message} pipeline_id={pipeline_id}",
                    exc_info=True,
                )
                await self._publish_update(
                    pipeline_id,
                    PipelineStatus.FAILED,
                    message=error_message,
                )

    async def start(self) -> None:
        self._log.info(
            f"Starting pipeline worker: pool={self._pool_name} queue={self._queue_name}"
        )

        self._connection = RabbitMQConnection(rabbitmq_config)
        await self._connection.connect()
        await self._connection.declare_topology()

        self._publisher = RabbitMQPublisher(self._connection, rabbitmq_config)
        self._consumer = RabbitMQConsumer(
            self._connection,
            rabbitmq_config,
            max_concurrent_tasks=self._max_concurrent_tasks,
        )

        await self._consumer.consume(
            queue_name=self._queue_name,
            callback=self._process,
        )

        self._s3 = S3Client()
        for template in self._templates.values():
            await template.service_type.initialize(self._s3)

        # Publish first heartbeat synchronously so core sees this worker
        # as capable of every configured pipeline before start() returns.
        # Otherwise there is a brief window where /pipelines/{id}/estimate
        # would report workers_missing=true.
        self._log.info(f"Starting heartbeat loop, worker_id={self._worker_id}")
        self._heartbeat_stop = asyncio.Event()
        try:
            await _hb.publish_once(self._worker_id, self._snapshot())
        except Exception as e:
            self._log.warning(f"Initial heartbeat publish failed: {e}")
        self._heartbeat_task = asyncio.create_task(
            _hb.run_loop(self._worker_id, self._snapshot, self._heartbeat_stop)
        )

        self._log.info("Pipeline worker started")

    async def stop(self) -> None:
        self._log.info("Stopping pipeline worker")

        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        if self._heartbeat_task is not None:
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        self._heartbeat_stop = None

        await close_redis_client()

        if self._consumer is not None:
            await self._consumer.stop()

        if self._connection is not None:
            await self._connection.close()

        self._log.info("Pipeline worker stopped")
