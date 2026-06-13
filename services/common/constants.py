"""Cross-service tunables that must agree with each other: any number used
in more than one place (timeout + its histogram, poll interval + overhead
math) lives here and everything derives from it.

Modal app entrypoints can't import this package; their few values are
mirrored in services/modal/common/constants.py (guarded by a sync test).
"""

from __future__ import annotations

# --- Pipeline timing envelope -------------------------------------------

# Hard ceiling on one dispatch pipeline (submit + poll loop). Mirrored as
# the Modal function timeout so a hung GPU call and the dispatch deadline
# give up together rather than racing each other.
MODAL_PIPELINE_DEADLINE_SECONDS = 600

# How often dispatch polls a spawned Modal call. Also the quantization
# noise floor for the "modal overhead" metric.
MODAL_POLL_INTERVAL_SECONDS = 2.0


def _buckets_to(ceiling: float, base: tuple[float, ...]) -> tuple[float, ...]:
    """Base buckets clipped to the ceiling, with the ceiling appended —
    so the top bucket always equals the relevant deadline and nothing
    user-visible can disappear into +Inf."""

    return tuple(b for b in base if b < ceiling) + (float(ceiling),)


# --- Histogram buckets ---------------------------------------------------

# HTTP calls (Modal submit/poll, core endpoints). Dense through the
# 50-500ms operating band so a 100->200->300ms drift is actually visible
# on the latency panel; high tail kept to 30s so a request stuck behind a
# slow/saturated dependency still lands on the chart instead of in +Inf.
HTTP_BUCKETS = (
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.15,
    0.2,
    0.25,
    0.3,
    0.4,
    0.5,
    0.75,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
)

# Whole-pipeline / per-phase inference durations. Top bucket = pipeline
# deadline: a run can be slow, but it cannot be off the chart.
INFERENCE_BUCKETS = _buckets_to(
    MODAL_PIPELINE_DEADLINE_SECONDS,
    (
        0.1,
        0.25,
        0.5,
        1.0,
        2.0,
        3.0,
        5.0,
        8.0,
        12.0,
        20.0,
        30.0,
        60.0,
        120.0,
        240.0,
        480.0,
    ),
)

# Container cold-start phases (snapshot load, weights→GPU).
COLD_START_BUCKETS = (
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    15.0,
    20.0,
    30.0,
    45.0,
    60.0,
    90.0,
    120.0,
    180.0,
)

# Time a job sits in RabbitMQ before a worker picks it up.
QUEUE_WAIT_BUCKETS = _buckets_to(
    MODAL_PIPELINE_DEADLINE_SECONDS,
    (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# User-perceived end-to-end (queue POST → terminal status in DB). Can
# exceed one pipeline deadline when jobs queue behind each other.
E2E_BUCKETS = _buckets_to(
    2 * MODAL_PIPELINE_DEADLINE_SECONDS,
    (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 240.0, 480.0, 600.0, 900.0),
)

# Postgres query durations (core). Dense through 2-100ms (where healthy
# queries live), but the tail reaches 10s on purpose: the DB is a remote
# Supabase pooler, so pool saturation / an incident shows up as the high
# buckets filling — capping at 1s would blind us exactly then.
DB_BUCKETS = (
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.0075,
    0.01,
    0.02,
    0.035,
    0.05,
    0.075,
    0.1,
    0.2,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

# Realized batch size at GPU dispatch.
BATCH_SIZE_BUCKETS = (1, 2, 4, 8, 12, 16, 24, 32)


# --- GPU cost model -------------------------------------------------------

# Published Modal on-demand rates (USD/hour), https://modal.com/pricing.
# Used for the *estimated* cost counters dispatch derives from per-request
# timings. The authoritative numbers are Modal's own billing dashboard and
# (when the OTel integration is enabled) modal.container.running × rate.
GPU_HOURLY_USD: dict[str, float] = {
    "A10G": 1.10,
    "L40S": 1.95,
    "H100": 3.95,
    "L4": 0.80,
    "T4": 0.59,
}
