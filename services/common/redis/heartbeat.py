"""Worker heartbeats and pipeline-duration tracking in Redis.

Single source of truth for ETA calculations across the platform. Both the
local compute worker (face_swap, face_recognition) and the dispatch worker
(generative_editing → Modal) use this so the core service can compute a
unified `eta_seconds` for any pending or running pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from .client import get_redis_client

log = logging.getLogger(__name__)


HEARTBEAT_KEY_PREFIX = "worker:heartbeat"
DURATION_KEY_PREFIX = "pipeline:duration"
RUNNING_KEY_PREFIX = "pipeline:running"

HEARTBEAT_TTL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 10
DURATION_HISTORY_LIMIT = 50
RUNNING_TTL_SECONDS = 600


def _heartbeat_key(pool: str, worker_id: str) -> str:
    return f"{HEARTBEAT_KEY_PREFIX}:{pool}:{worker_id}"


def _duration_key(pipeline_name: str) -> str:
    return f"{DURATION_KEY_PREFIX}:{pipeline_name}"


def _running_key(pipeline_id: str) -> str:
    return f"{RUNNING_KEY_PREFIX}:{pipeline_id}"


class WorkerHeartbeat:
    """Long-running heartbeat task; one per worker process.

    `pool` groups workers that drain the same queue (e.g. "compute",
    "dispatch"). Used by the ETA calculator to know parallelism for that
    queue.
    """

    def __init__(self, pool: str, worker_id: str | None = None) -> None:
        self.pool = pool
        self.worker_id = worker_id or str(uuid.uuid4())
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _tick(self) -> None:
        client = await get_redis_client()
        await client.set(
            _heartbeat_key(self.pool, self.worker_id),
            str(int(time.time())),
            ex=HEARTBEAT_TTL_SECONDS,
        )

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as e:
                log.warning(f"Heartbeat tick failed: {e}")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                continue

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._tick()
        self._task = asyncio.create_task(self._loop())
        log.info(f"Heartbeat started: pool={self.pool} worker={self.worker_id}")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        try:
            client = await get_redis_client()
            await client.delete(_heartbeat_key(self.pool, self.worker_id))
        except Exception as e:
            log.warning(f"Failed to clear heartbeat key on shutdown: {e}")
        self._task = None
        log.info(f"Heartbeat stopped: pool={self.pool} worker={self.worker_id}")


async def record_pipeline_duration(pipeline_name: str, duration_ms: float) -> None:
    """Push a completed pipeline's wall-time into a rolling list."""

    client = await get_redis_client()
    key = _duration_key(pipeline_name)
    pipe = client.pipeline()
    pipe.lpush(key, f"{duration_ms:.0f}")
    pipe.ltrim(key, 0, DURATION_HISTORY_LIMIT - 1)
    await pipe.execute()


async def mark_pipeline_running(pipeline_id: str) -> None:
    """Stamp the moment a pipeline transitioned to RUNNING for elapsed-time math."""

    client = await get_redis_client()
    await client.set(
        _running_key(pipeline_id),
        str(int(time.time() * 1000)),
        ex=RUNNING_TTL_SECONDS,
    )


async def clear_pipeline_running(pipeline_id: str) -> None:
    client = await get_redis_client()
    await client.delete(_running_key(pipeline_id))


@asynccontextmanager
async def track_pipeline_run(
    pipeline_id: str, pipeline_name: str
) -> AsyncIterator[None]:
    """Wraps an inference body — records start, then duration on success."""

    await mark_pipeline_running(pipeline_id)
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            await record_pipeline_duration(pipeline_name, duration_ms)
        except Exception as e:
            log.warning(f"Failed to record duration for {pipeline_name}: {e}")
        try:
            await clear_pipeline_running(pipeline_id)
        except Exception as e:
            log.warning(f"Failed to clear running marker for {pipeline_id}: {e}")


async def get_avg_duration_ms(pipeline_name: str, fallback_ms: float) -> float:
    client = await get_redis_client()
    samples = await client.lrange(_duration_key(pipeline_name), 0, -1)
    if not samples:
        return fallback_ms
    values = [float(s) for s in samples if s]
    if not values:
        return fallback_ms
    return sum(values) / len(values)


async def count_active_workers(pool: str) -> int:
    client = await get_redis_client()
    cursor = 0
    count = 0
    pattern = f"{HEARTBEAT_KEY_PREFIX}:{pool}:*"
    while True:
        cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
        count += len(keys)
        if cursor == 0:
            break
    return count


async def get_running_started_at_ms(pipeline_id: str) -> int | None:
    client = await get_redis_client()
    raw = await client.get(_running_key(pipeline_id))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
