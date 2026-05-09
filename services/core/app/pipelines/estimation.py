import json
import logging
from dataclasses import dataclass

from services.common.redis import get_redis_client


HEARTBEAT_KEY_PREFIX = "worker:heartbeat:"
DEFAULT_DURATIONS_MS: dict[str, float] = {
    "face_recognition": 1000.0,
    "face_swap": 10000.0,
}
FALLBACK_DURATION_MS = 10000.0

log = logging.getLogger(__name__)


@dataclass
class PipelineEstimate:
    estimated_seconds: float
    queue_position: int
    worker_count: int


async def _read_heartbeats() -> dict[str, dict[str, float]]:
    # Returns {pipeline_name: {worker_id: estimated_time_ms}}.
    # Keys live at worker:heartbeat:<pipeline_name>:<worker_id>; missing
    # workers (TTL'd out) are simply absent.
    out: dict[str, dict[str, float]] = {}
    try:
        client = await get_redis_client()
    except Exception as e:
        log.warning(f"Could not get Redis client for heartbeats: {e}")
        return out

    try:
        cursor = 0
        pattern = f"{HEARTBEAT_KEY_PREFIX}*"
        keys: list[str] = []
        while True:
            cursor, batch = await client.scan(cursor=cursor, match=pattern, count=200)
            keys.extend(batch)
            if cursor == 0:
                break
        if not keys:
            return out

        values = await client.mget(keys)
        for key, raw in zip(keys, values):
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                continue
            parts = key.split(":", 3)
            if len(parts) < 4:
                continue
            pipeline_name = parts[2]
            worker_id = parts[3]
            duration = float(
                payload.get("estimated_time_ms")
                or DEFAULT_DURATIONS_MS.get(pipeline_name, FALLBACK_DURATION_MS)
            )
            out.setdefault(pipeline_name, {})[worker_id] = duration
    except Exception as e:
        log.warning(f"Failed to read worker heartbeats: {e}")

    return out


async def estimate_pipeline(pending_by_type: dict[str, int]) -> PipelineEstimate:
    queue_position = sum(pending_by_type.values())

    if queue_position == 0:
        return PipelineEstimate(
            estimated_seconds=0.01,
            queue_position=0,
            worker_count=0,
        )

    heartbeats = await _read_heartbeats()
    all_workers: set[str] = set()
    for workers in heartbeats.values():
        all_workers.update(workers.keys())
    worker_count = len(all_workers)

    # Sum expected execution time for everything ahead+ours, using per-type
    # average across heartbeating workers; fall back to defaults when no
    # worker has reported for that type yet.
    total_work_ms = 0.0
    for pipeline_name, count in pending_by_type.items():
        durations = list(heartbeats.get(pipeline_name, {}).values())
        if durations:
            avg_ms = sum(durations) / len(durations)
        else:
            avg_ms = DEFAULT_DURATIONS_MS.get(pipeline_name, FALLBACK_DURATION_MS)
        total_work_ms += count * avg_ms

    # No live workers — give the optimistic single-stream estimate so the
    # frontend still has a non-zero countdown to render.
    divisor = worker_count if worker_count > 0 else 1
    estimated_seconds = total_work_ms / 1000.0 / divisor

    return PipelineEstimate(
        estimated_seconds=max(estimated_seconds, 0.01),
        queue_position=queue_position,
        worker_count=worker_count,
    )
