import json
import logging
import time
from typing import Optional

import redis.asyncio as redis

log = logging.getLogger(__name__)


HEARTBEAT_KEY_PREFIX = "worker:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 10
HEARTBEAT_TTL_SECONDS = 30
DEFAULT_PIPELINE_DURATION_SECONDS = 10.0


def _key(worker_id: str) -> str:
    return f"{HEARTBEAT_KEY_PREFIX}{worker_id}"


async def publish_heartbeat(
    client: redis.Redis,
    worker_id: str,
    last_duration_seconds: Optional[float],
) -> None:
    duration = (
        last_duration_seconds
        if last_duration_seconds is not None
        else DEFAULT_PIPELINE_DURATION_SECONDS
    )
    payload = {
        "worker_id": worker_id,
        "last_duration_seconds": duration,
        "timestamp": time.time(),
    }
    await client.set(
        _key(worker_id),
        json.dumps(payload),
        ex=HEARTBEAT_TTL_SECONDS,
    )


async def get_alive_workers(client: redis.Redis) -> list[dict]:
    workers: list[dict] = []
    cursor = 0
    pattern = f"{HEARTBEAT_KEY_PREFIX}*"
    while True:
        cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            values = await client.mget(keys)
            for raw in values:
                if raw is None:
                    continue
                try:
                    workers.append(json.loads(raw))
                except (ValueError, TypeError):
                    continue
        if cursor == 0:
            break
    return workers
