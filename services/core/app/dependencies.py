import logging
from typing import Optional

from services.common.rabbitmq import (
    RabbitMQConnection,
    RabbitMQPublisher,
    RabbitMQConsumer,
)
from services.common.rabbitmq.config import rabbitmq_config
from services.common.auth import (
    create_get_current_user,
    create_get_current_user_optional,
)
from services.common.redis import get_redis_client, close_redis_client

from services.core.app.config import config

log = logging.getLogger(__name__)

_rabbitmq_connection: Optional[RabbitMQConnection] = None
_rabbitmq_publisher: Optional[RabbitMQPublisher] = None
_rabbitmq_consumer: Optional[RabbitMQConsumer] = None

get_current_user = create_get_current_user(config.SUPABASE_URL)
get_current_user_optional = create_get_current_user_optional(config.SUPABASE_URL)


async def init_rabbitmq() -> None:
    global _rabbitmq_connection, _rabbitmq_publisher, _rabbitmq_consumer

    log.info("Initializing RabbitMQ connection")
    _rabbitmq_connection = RabbitMQConnection(rabbitmq_config)
    await _rabbitmq_connection.connect()
    await _rabbitmq_connection.declare_topology()

    _rabbitmq_publisher = RabbitMQPublisher(_rabbitmq_connection, rabbitmq_config)
    _rabbitmq_consumer = RabbitMQConsumer(
        _rabbitmq_connection, rabbitmq_config, max_concurrent_tasks=10
    )

    log.info("RabbitMQ initialized successfully")


async def init_redis() -> None:
    log.info("Initializing Redis connection")
    await get_redis_client()
    log.info("Redis initialized successfully")


async def get_rabbitmq_connection() -> RabbitMQConnection:
    if _rabbitmq_connection is None:
        raise RuntimeError("RabbitMQ connection not initialized")
    return _rabbitmq_connection


async def get_rabbitmq_publisher() -> RabbitMQPublisher:
    if _rabbitmq_publisher is None:
        raise RuntimeError("RabbitMQ publisher not initialized")
    return _rabbitmq_publisher


async def get_rabbitmq_consumer() -> RabbitMQConsumer:
    if _rabbitmq_consumer is None:
        raise RuntimeError("RabbitMQ consumer not initialized")
    return _rabbitmq_consumer


async def shutdown_rabbitmq() -> None:
    global _rabbitmq_connection, _rabbitmq_publisher, _rabbitmq_consumer

    log.info("Shutting down RabbitMQ")

    if _rabbitmq_consumer:
        await _rabbitmq_consumer.stop()

    if _rabbitmq_connection:
        await _rabbitmq_connection.close()

    _rabbitmq_connection = None
    _rabbitmq_publisher = None
    _rabbitmq_consumer = None

    log.info("RabbitMQ shutdown complete")


async def shutdown_redis() -> None:
    log.info("Shutting down Redis")
    await close_redis_client()
    log.info("Redis shutdown complete")
