import asyncio
import json
import logging
import time

from services.common.redis import get_redis_client
from services.compute.app.pipelines.service import pipeline_templates

HEARTBEAT_KEY_PREFIX = "worker:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 10
HEARTBEAT_TTL_SECONDS = 30

log = logging.getLogger(__name__)


def _key(pipeline_name: str, worker_id: str) -> str:
    return f"{HEARTBEAT_KEY_PREFIX}{pipeline_name}:{worker_id}"


async def publish_once(worker_id: str) -> None:
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

    await asyncio.gather(
        *(
            write(name, template.estimated_time_ms)
            for name, template in pipeline_templates.items()
        )
    )


async def run_loop(worker_id: str, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await publish_once(worker_id)
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


def record_success(pipeline_name: str, duration_ms: float) -> None:
    template = pipeline_templates.get(pipeline_name)
    if template is None:
        return
    template.estimated_time_ms = max(int(round(duration_ms)), 1)
