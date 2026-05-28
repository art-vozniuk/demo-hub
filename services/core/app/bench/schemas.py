"""Bench-coordinator request/response schemas.

Three tiers — see services/core/app/bench/service.py for the
cost-control logic that operates on them:

  - MOCK_LOCAL: dispatch resolves the pipeline locally (sleep + stub
    URL); no Modal call. Cost = $0. Used during UI/coordinator dev.
  - MOCK_MODAL: dispatch calls a Modal CPU-only app that sleeps. Cost
    ~ $0.0001 per request. Validates the full Modal-integration path
    without GPU billing.
  - REAL: dispatch calls the real GPU Modal app. Cost = real. Daily
    cap (BENCH_MAX_DAILY_SPEND_USD) applies only to this tier.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BenchTier(str, Enum):
    MOCK_LOCAL = "MOCK_LOCAL"
    MOCK_MODAL = "MOCK_MODAL"
    REAL = "REAL"


class BenchConfig(str, Enum):
    FLUX_OPT_A10G = "flux_opt_a10g"
    FLUX_OPT_H100 = "flux_opt_h100"
    FLUX_MODAL_MOCK = "flux_modal_mock"
    FLUX_LOCAL_MOCK = "flux_local_mock"


class BenchRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class BenchRunCreate(BaseModel):
    config: BenchConfig
    tier: BenchTier
    budget_usd: float = Field(gt=0, le=5.0)
    concurrency: int = Field(default=8, ge=1, le=256)
    # Sample input to feed to every fan-out request. For flux variants
    # this is {image_bucket, image_key, prompt}; mock tiers accept the
    # same shape and ignore image_key.
    sample_input: dict[str, Any]


class BenchEstimateRequest(BaseModel):
    config: BenchConfig
    tier: BenchTier
    budget_usd: float = Field(gt=0, le=5.0)


class BenchEstimateResponse(BaseModel):
    expected_images_low: int
    expected_images_high: int
    expected_time_seconds_low: float
    expected_time_seconds_high: float
    cold_start_risk_pct: int
    todays_spend_usd: float
    daily_cap_usd: float
    proceedable: bool
    reason: str | None = None


class BenchRunSummary(BaseModel):
    run_id: UUID
    config: BenchConfig
    tier: BenchTier
    status: BenchRunStatus
    budget_usd: float
    concurrency: int
    images_generated: int
    failures: int
    cost_usd: float
    elapsed_seconds: float
    started_at: datetime
    finished_at: datetime | None = None


class BenchRunListResponse(BaseModel):
    runs: list[BenchRunSummary]


class BenchRunStartedResponse(BaseModel):
    run_id: UUID
    status: BenchRunStatus
