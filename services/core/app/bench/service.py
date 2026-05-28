"""Bench coordinator.

Owns three responsibilities, all simple but consequential:

  1. Daily hard cap. Refuses to start a REAL-tier run if today's
     rolling cost + this run's budget would push past the configured
     ceiling. Tracked in Redis under a date-keyed counter so a coding
     mistake in the coordinator can't make the cap-breaching path
     reachable through anything fancier than `redis.del`.

  2. Cost-ceiling sequencing. A run with budget=$0.10 fans out one
     batch of `concurrency` requests, then waits, then estimates spend
     against the running clock and decides whether the next batch
     fits. When projected spend would exceed budget, no more requests
     get sent — final tally is whatever finished by then.

  3. Bookkeeping for /bench/runs/:id and /bench/runs (list). Runs are
     held in process memory; this is fine for one core replica running
     bench loads measured in single digits per hour. When that stops
     being true, swap the in-memory dict for a `bench_runs` table —
     the schema is already laid out in services/core/app/bench/schemas.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date, datetime
from typing import Any

from services.common.observability.metrics import (
    bench_run_active,
    bench_run_cost_usd_total,
    bench_run_failures_total,
    bench_run_images_total,
)
from services.common.redis import get_redis_client
from services.core.app.bench.schemas import (
    BenchConfig,
    BenchEstimateRequest,
    BenchEstimateResponse,
    BenchRunCreate,
    BenchRunStatus,
    BenchRunSummary,
    BenchTier,
)
from services.core.app.config import config

log = logging.getLogger(__name__)


# Per-GPU cost-per-second by config. Pulled from config.gpu_cost_table at
# resolution time so updating the env var requires no code change.
_CONFIG_GPU = {
    BenchConfig.FLUX_OPT_A10G: "A10G",
    BenchConfig.FLUX_OPT_H100: "H100",
    BenchConfig.FLUX_MODAL_MOCK: "CPU",
    BenchConfig.FLUX_LOCAL_MOCK: "CPU",
}


# Rough per-image steady-state seconds, used for cost estimation
# pre-flight. These are intentionally generous on the high side so
# the estimator doesn't lull the user into overshooting.
_STEADY_STATE_SECONDS = {
    BenchConfig.FLUX_OPT_A10G: (2.5, 4.0),
    BenchConfig.FLUX_OPT_H100: (0.4, 1.0),
    BenchConfig.FLUX_MODAL_MOCK: (0.8, 1.5),
    BenchConfig.FLUX_LOCAL_MOCK: (0.5, 2.0),
}

# Cold-start adders (seconds) by config — billed at the GPU rate while
# the container warms.
_COLD_START_SECONDS = {
    BenchConfig.FLUX_OPT_A10G: 30.0,
    BenchConfig.FLUX_OPT_H100: 45.0,
    BenchConfig.FLUX_MODAL_MOCK: 5.0,
    BenchConfig.FLUX_LOCAL_MOCK: 0.0,
}


def _daily_key(d: date | None = None) -> str:
    d = d or date.today()
    return f"bench:spent:{d.isoformat()}"


async def get_todays_spend_usd() -> float:
    client = await get_redis_client()
    raw = await client.get(_daily_key())
    return float(raw or 0.0)


async def _add_spend(usd: float) -> None:
    client = await get_redis_client()
    # incrbyfloat returns the new total; we don't use it, just persist.
    await client.incrbyfloat(_daily_key(), usd)


def _cost_per_sec(c: BenchConfig) -> float:
    table = config.gpu_cost_table
    gpu = _CONFIG_GPU[c]
    rate = table.get(gpu)
    if rate is None:
        # Defensive default: fall back to A10G rate. A miss here means
        # GPU_COST_USD_PER_SEC is out of sync with new bench configs.
        log.warning(f"no GPU cost configured for {gpu}; defaulting to A10G")
        return table.get("A10G", 0.0003)
    return rate


def _is_real(tier: BenchTier) -> bool:
    return tier == BenchTier.REAL


async def estimate(req: BenchEstimateRequest) -> BenchEstimateResponse:
    """Pre-flight estimate. Pure read; never charges anything."""

    low_s, high_s = _STEADY_STATE_SECONDS[req.config]
    cold_s = _COLD_START_SECONDS[req.config]
    rate = _cost_per_sec(req.config)

    # Conservative warm-only floor: budget / per-image steady-state cost.
    warm_low = max(int(req.budget_usd / (high_s * rate)), 0)
    warm_high = max(int(req.budget_usd / (low_s * rate)), 0)

    # Cold-start eats budget up front; subtract before dividing.
    cold_budget = max(req.budget_usd - cold_s * rate, 0.0)
    cold_low = max(int(cold_budget / (high_s * rate)), 0)
    cold_high = max(int(cold_budget / (low_s * rate)), 0)

    today = await get_todays_spend_usd()
    proceedable = True
    reason: str | None = None
    if _is_real(req.tier):
        if today + req.budget_usd > config.BENCH_MAX_DAILY_SPEND_USD:
            proceedable = False
            reason = (
                f"daily cap ${config.BENCH_MAX_DAILY_SPEND_USD:.2f} would be "
                f"exceeded (today=${today:.4f}, budget=${req.budget_usd:.4f})"
            )

    return BenchEstimateResponse(
        expected_images_low=cold_low,
        expected_images_high=warm_high,
        expected_time_seconds_low=cold_s + low_s,
        expected_time_seconds_high=cold_s + high_s * warm_high,
        # Rough heuristic: brand-new app first hit has very high
        # cold-start probability; warm caching brings it down. Real
        # value would come from `flux_warm_ratio` metric — wire when
        # there's enough history.
        cold_start_risk_pct=70 if _is_real(req.tier) else 10,
        todays_spend_usd=today,
        daily_cap_usd=config.BENCH_MAX_DAILY_SPEND_USD,
        proceedable=proceedable,
        reason=reason,
    )


# In-memory bench-run registry. Single core replica → fine. See module
# docstring for the migration path.
class _Run:
    __slots__ = (
        "id", "config", "tier", "status", "budget_usd", "concurrency",
        "images_generated", "failures", "cost_usd",
        "started_at", "finished_at", "_lock",
    )

    def __init__(self, payload: BenchRunCreate, run_id: uuid.UUID) -> None:
        self.id = run_id
        self.config = payload.config
        self.tier = payload.tier
        self.status = BenchRunStatus.PENDING
        self.budget_usd = payload.budget_usd
        self.concurrency = payload.concurrency
        self.images_generated = 0
        self.failures = 0
        self.cost_usd = 0.0
        self.started_at = datetime.utcnow()
        self.finished_at: datetime | None = None
        self._lock = asyncio.Lock()

    def to_summary(self) -> BenchRunSummary:
        elapsed = (
            (self.finished_at or datetime.utcnow()) - self.started_at
        ).total_seconds()
        return BenchRunSummary(
            run_id=self.id,
            config=self.config,
            tier=self.tier,
            status=self.status,
            budget_usd=self.budget_usd,
            concurrency=self.concurrency,
            images_generated=self.images_generated,
            failures=self.failures,
            cost_usd=self.cost_usd,
            elapsed_seconds=elapsed,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


_RUNS: dict[uuid.UUID, _Run] = {}
_ACTIVE_LOCK = asyncio.Lock()
_ACTIVE_RUN_ID: uuid.UUID | None = None


async def list_runs(limit: int = 50) -> list[BenchRunSummary]:
    items = sorted(_RUNS.values(), key=lambda r: r.started_at, reverse=True)
    return [r.to_summary() for r in items[:limit]]


async def get_run(run_id: uuid.UUID) -> BenchRunSummary | None:
    run = _RUNS.get(run_id)
    return run.to_summary() if run else None


async def start_run(payload: BenchRunCreate) -> uuid.UUID:
    """Start a bench run. Refuses if daily cap exhausted (REAL only) or
    another run is already active (we keep it simple — sequential)."""

    # Daily cap precheck — independent of any frontend logic.
    if _is_real(payload.tier):
        today = await get_todays_spend_usd()
        if today + payload.budget_usd > config.BENCH_MAX_DAILY_SPEND_USD:
            raise ValueError(
                f"daily bench cap ${config.BENCH_MAX_DAILY_SPEND_USD:.2f} would "
                f"be exceeded (today=${today:.4f}, budget=${payload.budget_usd:.4f})"
            )

    global _ACTIVE_RUN_ID
    async with _ACTIVE_LOCK:
        if _ACTIVE_RUN_ID is not None and _RUNS[_ACTIVE_RUN_ID].status in (
            BenchRunStatus.PENDING, BenchRunStatus.RUNNING,
        ):
            raise ValueError(
                f"another bench run is already active: {_ACTIVE_RUN_ID}"
            )

        run_id = uuid.uuid4()
        _RUNS[run_id] = _Run(payload, run_id)
        _ACTIVE_RUN_ID = run_id

    # Coordinator runs in a background task tied to the FastAPI app
    # lifecycle. Reference held in the Run object via the asyncio task
    # group on the app — see services/core/app/bench/router.py for the
    # task-creation wiring.
    return run_id


async def coordinator(run_id: uuid.UUID, sample_input: dict[str, Any]) -> None:
    """The actual fan-out loop. Run as a background task; cancellation
    aborts the run gracefully (status → ABORTED)."""

    run = _RUNS[run_id]
    run.status = BenchRunStatus.RUNNING
    bench_run_active.labels(
        run_id=str(run_id), config=run.config.value, tier=run.tier.value,
    ).set(1)

    rate = _cost_per_sec(run.config)
    cold = _COLD_START_SECONDS[run.config]
    avg_s = sum(_STEADY_STATE_SECONDS[run.config]) / 2.0

    try:
        # Apply cold-start cost up front (heuristic — real cost comes
        # from container_uptime metric pushed by Modal; we reconcile
        # later in services/core/app/bench/reconcile.py if/when added).
        cold_cost = cold * rate
        run.cost_usd += cold_cost
        bench_run_cost_usd_total.labels(
            run_id=str(run_id), config=run.config.value, tier=run.tier.value,
        ).inc(cold_cost)
        if _is_real(run.tier):
            await _add_spend(cold_cost)

        while True:
            # Project spend if we fire one more batch.
            batch_cost = run.concurrency * avg_s * rate
            if run.cost_usd + batch_cost > run.budget_usd:
                log.info(
                    f"[{run_id}] budget tipped (cost={run.cost_usd:.4f} + "
                    f"projected={batch_cost:.4f} > budget={run.budget_usd:.4f}); "
                    "stopping"
                )
                break

            # Fire one batch. Each request is its own dispatch enqueue,
            # tagged with run_id so metrics aggregate cleanly. The
            # gather collects success/failure; partial failures are
            # logged but don't abort the run.
            results = await asyncio.gather(
                *(
                    _fire_one(run_id, run.config, run.tier, sample_input)
                    for _ in range(run.concurrency)
                ),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, BaseException):
                    run.failures += 1
                    bench_run_failures_total.labels(
                        run_id=str(run_id),
                        config=run.config.value,
                        tier=run.tier.value,
                        error_type=type(r).__name__,
                    ).inc()
                else:
                    run.images_generated += 1
                    bench_run_images_total.labels(
                        run_id=str(run_id),
                        config=run.config.value,
                        tier=run.tier.value,
                    ).inc()

            # Charge the batch.
            actual_batch_cost = run.concurrency * avg_s * rate
            run.cost_usd += actual_batch_cost
            bench_run_cost_usd_total.labels(
                run_id=str(run_id), config=run.config.value, tier=run.tier.value,
            ).inc(actual_batch_cost)
            if _is_real(run.tier):
                await _add_spend(actual_batch_cost)

        run.status = BenchRunStatus.COMPLETED

    except asyncio.CancelledError:
        run.status = BenchRunStatus.ABORTED
        raise
    except Exception as e:
        log.exception(f"[{run_id}] coordinator failed: {e}")
        run.status = BenchRunStatus.FAILED
    finally:
        run.finished_at = datetime.utcnow()
        bench_run_active.labels(
            run_id=str(run_id), config=run.config.value, tier=run.tier.value,
        ).set(0)
        global _ACTIVE_RUN_ID
        async with _ACTIVE_LOCK:
            if _ACTIVE_RUN_ID == run_id:
                _ACTIVE_RUN_ID = None
        log.info(
            f"[{run_id}] run finished: status={run.status.value} "
            f"images={run.images_generated} cost=${run.cost_usd:.4f} "
            f"failures={run.failures}"
        )


async def _fire_one(
    run_id: uuid.UUID,
    config_: BenchConfig,
    tier: BenchTier,
    sample_input: dict[str, Any],
) -> dict[str, Any]:
    """Enqueue one inference message into the dispatch queue, return
    the (eventual) result. For MOCK_LOCAL tier, short-circuits with a
    local stub — never touches Modal or RabbitMQ.
    """

    # Stub: in this PR the bench enqueue path goes through the same
    # RabbitMQ publish + status-poll loop as a normal pipeline. For
    # MVP we just simulate a per-image cost so dashboards light up.
    # The full enqueue/poll wiring lands in a follow-up so we can
    # iterate on the coordinator behavior first.
    if tier == BenchTier.MOCK_LOCAL or config_ == BenchConfig.FLUX_LOCAL_MOCK:
        import random
        await asyncio.sleep(random.uniform(0.5, 2.0))
        return {"result_url": "stub://mock-local"}

    # For MOCK_MODAL and REAL, the real wiring would publish onto the
    # dispatch queue with a special bench routing/payload. Marked as
    # follow-up: see TODO in services/core/app/bench/router.py.
    avg_s = sum(_STEADY_STATE_SECONDS[config_]) / 2.0
    await asyncio.sleep(avg_s)
    return {"result_url": "stub://bench-stub"}
