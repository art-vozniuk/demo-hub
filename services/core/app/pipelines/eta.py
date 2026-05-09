"""ETA calculator — single source of truth for `eta_seconds` returned by
/pipelines/status. Reads heartbeats and rolling duration history that
both the compute and dispatch workers publish into Redis."""

from __future__ import annotations

import logging
import time

from services.common.redis import (
    count_active_workers,
    get_avg_duration_ms,
    get_running_started_at_ms,
)
from services.common.domain.enums import PipelineStatus

from .routing import get_route

log = logging.getLogger(__name__)


async def estimate_seconds(
    pipeline_id: str,
    pipeline_name: str,
    status: PipelineStatus,
    queue_position: int,
) -> float | None:
    """Return remaining-time estimate in seconds, or None if not estimable.

    `queue_position` is the 0-based index of this pipeline among PENDING
    siblings in the same pool. Position 0 means "next to be picked up".
    """

    if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED):
        return 0.0

    try:
        route = get_route(pipeline_name)
    except ValueError:
        return None

    avg_ms = await get_avg_duration_ms(pipeline_name, route.fallback_duration_ms)

    if status == PipelineStatus.RUNNING:
        started_ms = await get_running_started_at_ms(pipeline_id)
        if started_ms is None:
            return avg_ms / 1000.0
        elapsed_ms = max(0.0, time.time() * 1000 - started_ms)
        return max(0.0, (avg_ms - elapsed_ms) / 1000.0)

    workers = max(1, await count_active_workers(route.pool))
    wait_ms = (queue_position // workers) * avg_ms
    return (wait_ms + avg_ms) / 1000.0
