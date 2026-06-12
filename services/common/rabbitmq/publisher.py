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
    ) -> None:
        from services.common.observability.metrics import rabbitmq_publish_total

        if not self.connection.channel:
            raise RuntimeError("Channel not initialized")

        exchange = await self.connection.channel.get_exchange(self.config.exchange)

        body = json.dumps(message).encode()

        log.info(f"Publishing message to {routing_key}")

        try:
            await exchange.publish(
                Message(
                    body=body,
                    delivery_mode=DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=routing_key,
                timeout=self.config.publish_confirm_timeout,
            )
        except Exception:
            rabbitmq_publish_total.labels(routing_key=routing_key, status="error").inc()
            raise

        rabbitmq_publish_total.labels(routing_key=routing_key, status="ok").inc()
        log.info(f"Message published to {routing_key}")
