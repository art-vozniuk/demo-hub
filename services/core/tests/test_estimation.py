import json

import pytest

from services.core.app.pipelines import estimation
from services.core.app.pipelines.estimation import (
    HEARTBEAT_KEY_PREFIX,
    estimate_pipeline,
)


COMPUTE_NAMES = {"face_swap", "face_recognition"}
DISPATCH_NAMES = {"generative_editing"}


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def scan(self, cursor: int, match: str, count: int):
        prefix = match.rstrip("*")
        keys = [k for k in self._store if k.startswith(prefix)]
        return 0, keys

    async def mget(self, keys):
        return [self._store.get(k) for k in keys]


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace the cached redis client used by estimation._read_heartbeats
    with an in-memory fake. Returns the dict so each test can populate
    heartbeat keys directly."""

    store: dict[str, str] = {}
    fake = _FakeRedis(store)

    async def _get():
        return fake

    monkeypatch.setattr(estimation, "get_redis_client", _get)
    return store


def _set_heartbeat(store, pipeline_name, worker_id, ms):
    key = f"{HEARTBEAT_KEY_PREFIX}{pipeline_name}:{worker_id}"
    store[key] = json.dumps({"estimated_time_ms": ms})


@pytest.mark.asyncio
async def test_parallel_pool_ignores_queue_depth(fake_redis):
    # 5 generative_editing jobs in flight, but Modal scales out — the
    # estimate should be just one inference duration, not 5×.
    _set_heartbeat(fake_redis, "generative_editing", "modal-1", 8000)

    est = await estimate_pipeline(
        {"generative_editing": 5},
        target_pipeline_name="generative_editing",
        parallel=True,
        same_pool_names=DISPATCH_NAMES,
    )
    assert est.estimated_seconds == pytest.approx(8.0)
    assert est.queue_position == 5
    assert est.worker_count == 1
    assert est.workers_missing is False


@pytest.mark.asyncio
async def test_parallel_pool_no_workers(fake_redis):
    # No heartbeats at all — workers_missing should be reported.
    est = await estimate_pipeline(
        {"generative_editing": 1},
        target_pipeline_name="generative_editing",
        parallel=True,
        same_pool_names=DISPATCH_NAMES,
    )
    assert est.workers_missing is True
    assert est.worker_count == 0


@pytest.mark.asyncio
async def test_sequential_pool_sums_queue_depth(fake_redis):
    # Two face_swap and one face_recognition ahead, single GPU compute
    # worker handling both. ETA = (2 × 6000 + 1 × 1500) / 1000 = 13.5s.
    _set_heartbeat(fake_redis, "face_swap", "compute-1", 6000)
    _set_heartbeat(fake_redis, "face_recognition", "compute-1", 1500)

    est = await estimate_pipeline(
        {"face_swap": 2, "face_recognition": 1},
        target_pipeline_name="face_swap",
        parallel=False,
        same_pool_names=COMPUTE_NAMES,
    )
    assert est.estimated_seconds == pytest.approx(13.5)
    assert est.queue_position == 3
    assert est.worker_count == 1


@pytest.mark.asyncio
async def test_sequential_pool_excludes_other_pool_pending(fake_redis):
    # generative_editing in flight should NOT bloat a face_swap estimate
    # — different pools, different workers.
    _set_heartbeat(fake_redis, "face_swap", "compute-1", 6000)
    _set_heartbeat(fake_redis, "generative_editing", "modal-1", 30000)

    est = await estimate_pipeline(
        {"face_swap": 1, "generative_editing": 4},
        target_pipeline_name="face_swap",
        parallel=False,
        same_pool_names=COMPUTE_NAMES,
    )
    # Only the one face_swap counts.
    assert est.estimated_seconds == pytest.approx(6.0)
    assert est.queue_position == 1


@pytest.mark.asyncio
async def test_parallel_pool_excludes_other_pool_pending(fake_redis):
    # In-flight face_swap shouldn't show up in dispatch estimate either.
    _set_heartbeat(fake_redis, "generative_editing", "modal-1", 8000)
    _set_heartbeat(fake_redis, "face_swap", "compute-1", 6000)

    est = await estimate_pipeline(
        {"face_swap": 3, "generative_editing": 1},
        target_pipeline_name="generative_editing",
        parallel=True,
        same_pool_names=DISPATCH_NAMES,
    )
    assert est.estimated_seconds == pytest.approx(8.0)
    assert est.queue_position == 1
