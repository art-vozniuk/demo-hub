import logging
import json
from typing import Any, Dict
from aio_pika import Message, DeliveryMode

from .connection import RabbitMQConnection
from .config import RabbitMQConfig

log = logging.getLogger(__name__)


class RabbitMQPublisher:
    def __init__(self, connection: RabbitMQConnection, config: RabbitMQConfig):
        self.connection = connection
        self.config = config

    async def publish(
        self,
        routing_key: str,
        message: Dict[str, Any],
        trace_id: str,
        pipeline_id: str | None = None,
    ) -> None:
        if not self.connection.channel:
            raise RuntimeError("Channel not initialized")

        exchange = await self.connection.channel.get_exchange(self.config.exchange)

        body = json.dumps(message).encode()

        log.info(f"Publishing message to {routing_key}")

        await exchange.publish(
            Message(
                body=body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=routing_key,
            timeout=self.config.publish_confirm_timeout,
        )

        log.info(f"Message published to {routing_key}")
