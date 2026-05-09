"""Dispatch-side binding of the shared heartbeat helper. Symmetric with
services/compute/app/pipelines/heartbeat.py — only the templates source
differs.
"""

import asyncio
from typing import Mapping

from services.common.redis import heartbeat as _hb
from services.dispatch.app.pipelines.service import pipeline_templates


def _snapshot() -> Mapping[str, int]:
    return {n: t.estimated_time_ms for n, t in pipeline_templates.items()}


async def publish_once(worker_id: str) -> None:
    await _hb.publish_once(worker_id, _snapshot())


async def run_loop(worker_id: str, stop_event: asyncio.Event) -> None:
    await _hb.run_loop(worker_id, _snapshot, stop_event)


def record_success(pipeline_name: str, duration_ms: float) -> None:
    template = pipeline_templates.get(pipeline_name)
    if template is None:
        return
    template.estimated_time_ms = max(int(round(duration_ms)), 1)
