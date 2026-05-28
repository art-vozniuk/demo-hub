"""Worker heartbeat publisher.

Writes one Redis key per (pipeline_name, worker_id) carrying the worker's
current wall-time estimate. Core reads these keys to compute ETAs.
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


# Callable (not a static dict) so workers can mutate their estimates
# in place and the next tick picks the new value up.
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

    # return_exceptions: one Redis blip on a single pipeline's heartbeat
    # shouldn't cancel the rest in this snapshot. Failures are surfaced
    # by the next tick (TTL expires) and logged here for visibility.
    results = await asyncio.gather(
        *(write(name, ms) for name, ms in snapshot.items()),
        return_exceptions=True,
    )
    for name, result in zip(snapshot.keys(), results):
        if isinstance(result, Exception):
            log.warning(f"heartbeat write failed for {name}: {result!r}")


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
