"""Generic worker heartbeat publisher.

Each worker process periodically writes one Redis key per
(pipeline_name, worker_id) carrying its current best-known wall-time
estimate for that pipeline. Core's estimation reads these keys to
compute ETAs irrespective of which pool a pipeline belongs to.

Compute and dispatch each have a thin wrapper module that binds this
helper to their own `pipeline_templates` dict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Mapping

from .client import get_redis_client

HEARTBEAT_KEY_PREFIX = "worker:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 10
HEARTBEAT_TTL_SECONDS = 30

log = logging.getLogger(__name__)


# Each tick the wrapper module returns the current
# {pipeline_name: estimated_time_ms} snapshot. Returning a callable (not
# a static dict) lets workers mutate their estimates in-place after each
# successful run and have the next tick pick the new value up.
SnapshotProvider = Callable[[], Mapping[str, int]]


def _key(pipeline_name: str, worker_id: str) -> str:
    return f"{HEARTBEAT_KEY_PREFIX}{pipeline_name}:{worker_id}"


async def publish_once(worker_id: str, snapshot: Mapping[str, int]) -> None:
    client = await get_redis_client()
    now = time.time()

    async def write(pipeline_name: str, estimated_time_ms: int) -> None:
        payload = {
            "pipeline_name": pipeline_name,
            "worker_id": worker_id,
            "estimated_time_ms": estimated_time_ms,
            "ts": now,
        }
        await client.set(
            _key(pipeline_name, worker_id),
            json.dumps(payload),
            ex=HEARTBEAT_TTL_SECONDS,
        )

    await asyncio.gather(*(write(name, ms) for name, ms in snapshot.items()))


async def run_loop(
    worker_id: str,
    snapshot_provider: SnapshotProvider,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await publish_once(worker_id, snapshot_provider())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Failed to publish worker heartbeat: {e}")

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            continue
