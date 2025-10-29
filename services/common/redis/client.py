import logging
from typing import Optional
import redis.asyncio as redis

from .config import redis_config

log = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None


async def get_redis_client() -> redis.Redis:
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.from_url(
            redis_config.REDIS_URL,
            decode_responses=redis_config.decode_responses,
            socket_timeout=redis_config.socket_timeout,
            socket_connect_timeout=redis_config.socket_connect_timeout,
        )
        log.info(f"Redis client initialized: {redis_config.REDIS_URL}")

    return _redis_client


async def close_redis_client():
    global _redis_client

    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        log.info("Redis client closed")
