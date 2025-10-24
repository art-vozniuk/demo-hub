import logging
import asyncio
from typing import Optional
from aio_pika import connect_robust, Channel, ExchangeType
from aio_pika.abc import AbstractRobustConnection

from .config import RabbitMQConfig

log = logging.getLogger(__name__)


class RabbitMQConnection:
    def __init__(self, config: RabbitMQConfig):
        self.config = config
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[Channel] = None

    async def connect(self) -> None:
        while True:
            try:
                log.info(f"Connecting to RabbitMQ at {self.config.url}")
                self.connection = await connect_robust(
                    self.config.url,
                    reconnect_interval=1.0,
                    fail_fast=False,
                )
                self.channel = await self.connection.channel()
                await self.channel.set_qos(prefetch_count=self.config.prefetch)
                log.info("RabbitMQ connection established")
                break
            except Exception as e:
                log.warning(
                    f"Failed to connect to RabbitMQ: {e}. Retrying in 1 second..."
                )
                await asyncio.sleep(1)

    async def declare_topology(self) -> None:
        while True:
            try:
                if not self.channel:
                    raise RuntimeError("Channel not initialized")

                log.info("Declaring RabbitMQ topology")

                dlx = await self.channel.declare_exchange(
                    self.config.dlx,
                    ExchangeType.DIRECT,
                    durable=True,
                )

                exchange = await self.channel.declare_exchange(
                    self.config.exchange,
                    ExchangeType.DIRECT,
                    durable=True,
                )

                queue_main_dlq = await self.channel.declare_queue(
                    self.config.queue_main_dlq,
                    durable=True,
                )
                await queue_main_dlq.bind(dlx, routing_key=self.config.routing_submit)

                queue_update_dlq = await self.channel.declare_queue(
                    self.config.queue_update_dlq,
                    durable=True,
                )
                await queue_update_dlq.bind(dlx, routing_key=self.config.routing_update)

                queue_main = await self.channel.declare_queue(
                    self.config.queue_main,
                    durable=True,
                    arguments={
                        "x-dead-letter-exchange": self.config.dlx,
                        "x-dead-letter-routing-key": self.config.routing_submit,
                    },
                )
                await queue_main.bind(exchange, routing_key=self.config.routing_submit)

                queue_update = await self.channel.declare_queue(
                    self.config.queue_update,
                    durable=True,
                    arguments={
                        "x-dead-letter-exchange": self.config.dlx,
                        "x-dead-letter-routing-key": self.config.routing_update,
                    },
                )
                await queue_update.bind(
                    exchange, routing_key=self.config.routing_update
                )

                log.info("RabbitMQ topology declared successfully")
                break
            except Exception as e:
                log.warning(
                    f"Failed to declare RabbitMQ topology: {e}. Retrying in 1 second..."
                )
                await asyncio.sleep(1)

    async def get_queue_length(self, queue_name: str) -> int:
        if not self.channel:
            raise RuntimeError("Channel not initialized")

        queue = await self.channel.declare_queue(queue_name, passive=True)
        return queue.declaration_result.message_count

    async def close(self) -> None:
        log.info("Closing RabbitMQ connection")
        if self.channel:
            await self.channel.close()
        if self.connection:
            await self.connection.close()
        log.info("RabbitMQ connection closed")
