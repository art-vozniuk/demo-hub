"""Single source of truth for cross-service tunables whose values must
agree with each other.

The rule: any number that appears in more than one place (a timeout AND
the histogram that observes it, a poll interval AND the overhead math
that subtracts it) lives here, and everything derives from it. Change
the deadline → the buckets follow automatically.

Modal app entrypoints (services/modal/*/app.py) cannot import this
package — they ship only services/modal/common into their images — so
the few values they need are mirrored in
services/modal/common/constants.py and kept in lockstep by
services/common/tests/test_constants_sync.py.
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

# Short-tail HTTP calls (Modal submit/poll, core endpoints).
HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

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

# Postgres query durations (core).
DB_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

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
