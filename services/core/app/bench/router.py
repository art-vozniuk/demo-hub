"""Bench-coordinator HTTP surface.

All routes require `require_experimenter`. The frontend hides the
/experiments tab unless /api/v1/me/permissions reports
`can_run_experiments: true`, but that's UX — these handlers refuse
unauthorized callers independently.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from services.common.auth.models import User
from services.core.app.bench import service as bench_service
from services.core.app.bench.schemas import (
    BenchEstimateRequest,
    BenchEstimateResponse,
    BenchRunCreate,
    BenchRunListResponse,
    BenchRunStartedResponse,
    BenchRunStatus,
    BenchRunSummary,
)
from services.core.app.dependencies import require_experimenter

log = logging.getLogger(__name__)


router = APIRouter()


@router.post("/runs", response_model=BenchRunStartedResponse)
async def start_run(
    payload: BenchRunCreate,
    user: User = Depends(require_experimenter),
) -> BenchRunStartedResponse:
    try:
        run_id = await bench_service.start_run(payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        ) from None

    _track(asyncio.create_task(
        bench_service.coordinator(run_id, payload.sample_input)
    ))

    log.info(f"bench run started: {run_id} by {user.email}")
    return BenchRunStartedResponse(run_id=run_id, status=BenchRunStatus.PENDING)


@router.get("/runs", response_model=BenchRunListResponse)
async def list_runs(
    user: User = Depends(require_experimenter),
) -> BenchRunListResponse:
    runs = await bench_service.list_runs(limit=50)
    return BenchRunListResponse(runs=runs)


@router.get("/runs/{run_id}", response_model=BenchRunSummary)
async def get_run(
    run_id: UUID,
    user: User = Depends(require_experimenter),
) -> BenchRunSummary:
    summary = await bench_service.get_run(run_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"bench run {run_id} not found",
        )
    return summary


@router.post("/estimate", response_model=BenchEstimateResponse)
async def estimate(
    payload: BenchEstimateRequest,
    user: User = Depends(require_experimenter),
) -> BenchEstimateResponse:
    return await bench_service.estimate(payload)


# Strong reference for coordinator tasks so the loop's weakref to
# asyncio tasks can't drop them mid-run. See note in services/core/main.py
# about the same pattern for the pipeline-update consumer.
_BG_TASKS: set[asyncio.Task] = set()


def _track(task: asyncio.Task) -> None:
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
