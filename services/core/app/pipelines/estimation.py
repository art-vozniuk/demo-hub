import logging
from datetime import datetime, timedelta, timezone

from services.common.redis import (
    get_alive_workers,
    get_redis_client,
    DEFAULT_PIPELINE_DURATION_SECONDS,
)

log = logging.getLogger(__name__)


async def estimate_finish_at(queue_position: int) -> datetime:
    """
    queue_position: 0-based index of this pipeline within the work to be done
    (queue length already in front of us + offset of this job in the new batch).
    """
    try:
        client = await get_redis_client()
        workers = await get_alive_workers(client)
    except Exception as e:
        log.warning(f"Could not read worker heartbeats from Redis: {e}")
        workers = []

    if not workers:
        # No workers alive — fall back to default duration so frontend still
        # has a reasonable timer rather than nothing.
        seconds_per_job = DEFAULT_PIPELINE_DURATION_SECONDS
        worker_count = 1
    else:
        durations = [
            float(w.get("last_duration_seconds") or DEFAULT_PIPELINE_DURATION_SECONDS)
            for w in workers
        ]
        worker_count = len(workers)
        # Average duration as the per-worker time-per-job. Combined with worker
        # count this gives wall-clock seconds-per-job under steady throughput.
        avg_duration = sum(durations) / worker_count
        seconds_per_job = avg_duration / worker_count

    # queue_position 0 means this job is next — still needs ~one job duration.
    estimated_seconds = (queue_position + 1) * seconds_per_job
    return datetime.now(timezone.utc) + timedelta(seconds=estimated_seconds)
