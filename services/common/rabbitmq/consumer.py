import logging
import json
import asyncio
from typing import Callable, Awaitable, Any, Dict, Set
from aio_pika.abc import AbstractIncomingMessage

from .connection import RabbitMQConnection
from .config import RabbitMQConfig

log = logging.getLogger(__name__)


class RabbitMQConsumer:
    def __init__(
        self,
        connection: RabbitMQConnection,
        config: RabbitMQConfig,
        max_concurrent_tasks: int = 50,
    ):
        self.connection = connection
        self.config = config
        self._consumer_task: asyncio.Task | None = None
        self._background_tasks: Set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def consume(
        self,
        queue_name: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        if not self.connection.channel:
            raise RuntimeError("Channel not initialized")

        log.info(f"Starting consumer for queue: {queue_name}")

        queue = await self.connection.channel.get_queue(queue_name)

        async def process_message(message: AbstractIncomingMessage) -> None:
            try:
                body = json.loads(message.body.decode())
                trace_id = body.get("trace_id", "unknown")
                pipeline_id = body.get("pipeline_id")
                pipeline_str = f", pipeline_id={pipeline_id}" if pipeline_id else ""
            except Exception as e:
                log.error(f"Failed to parse message from {queue_name}: {e}")
                await message.reject(requeue=False)
                return

            log.info(
                f"[trace_id={trace_id}{pipeline_str}] Received message from {queue_name}"
            )

            async def background_process():
                # limit concurrent processing (helps with Core db connections)
                async with self._semaphore:
                    try:
                        await callback(body)
                        await message.ack()
                        log.info(
                            f"[trace_id={trace_id}{pipeline_str}] Message processed successfully from {queue_name}"
                        )
                    except Exception as e:
                        await message.nack(requeue=True)
                        log.error(
                            f"[trace_id={trace_id}{pipeline_str}] Error processing message from {queue_name}: {e}",
                            exc_info=True,
                        )

            task = asyncio.create_task(background_process())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        self._consumer_task = asyncio.create_task(queue.consume(process_message))
        log.info(f"Consumer started for queue: {queue_name}")

    async def stop(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        if self._background_tasks:
            log.info(
                f"Waiting for {len(self._background_tasks)} background tasks to complete..."
            )
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        log.info("Consumer stopped")
