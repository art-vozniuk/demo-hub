"""Canonical metric definitions for the platform.

Everything is scraped — there is no push path. Modal containers return
their per-request timings inside the generate() response (`_obs` block,
see services/modal/common/instrument.py) and the dispatch worker turns
them into histogram observations here, where Prometheus scrapes them on
a normal cadence and rate()/increase() behave.

Groups:

  - Pipeline stages (dispatch): queue wait, whole-pipeline wall time,
    failures — the user-visible decomposition.
  - Modal HTTP edge (dispatch): submit/poll call durations, statuses,
    retries.
  - Inference internals (dispatch, from Modal-returned timings): phase
    wall times, cold starts, batch size, estimated GPU cost.
  - Core service health: HTTP per-route, DB query durations, RabbitMQ
    publishes, end-to-end pipeline latency.

All names share the `demo_hub_` prefix. Labels are kept low-cardinality
on purpose — every new dimension costs Prometheus series. Bucket edges
derive from services/common/constants.py so deadlines and histograms
cannot drift apart.
"""

from __future__ import annotations

from services.common.constants import (
    BATCH_SIZE_BUCKETS,
    COLD_START_BUCKETS,
    DB_BUCKETS,
    E2E_BUCKETS,
    HTTP_BUCKETS,
    INFERENCE_BUCKETS,
    QUEUE_WAIT_BUCKETS,
)

from . import Counter, Histogram


# --- Pipeline stages (dispatch worker) -----------------------------------

queue_wait_seconds = Histogram(
    "demo_hub_queue_wait_seconds",
    "Time a job sat in RabbitMQ between publish and worker pickup.",
    ["pipeline_name"],
    buckets=QUEUE_WAIT_BUCKETS,
)

pipeline_duration_seconds = Histogram(
    "demo_hub_pipeline_duration_seconds",
    "Wall-time for one dispatch pipeline (submit + poll loop).",
    ["pipeline_name"],
    buckets=INFERENCE_BUCKETS,
)

pipeline_failures_total = Counter(
    "demo_hub_pipeline_failures_total",
    "Dispatch pipelines that bubbled an exception past _process().",
    ["pipeline_name", "error_type"],
)


# --- Modal HTTP edge (dispatch worker) -----------------------------------

modal_call_requests_total = Counter(
    "demo_hub_modal_call_requests_total",
    "Modal HTTP calls dispatched (submit + each poll counts).",
    ["endpoint", "status"],
)

modal_call_duration_seconds = Histogram(
    "demo_hub_modal_call_duration_seconds",
    "Wall-time for one Modal HTTP call (post-retry).",
    ["endpoint"],
    buckets=HTTP_BUCKETS,
)

modal_call_retries_total = Counter(
    "demo_hub_modal_call_retries_total",
    "Transient-error retries inside _post_to_modal (per-attempt count).",
    ["endpoint", "reason"],
)


# --- Inference internals (recorded by dispatch from Modal timings) -------

inference_requests_total = Counter(
    "demo_hub_inference_requests_total",
    "Modal inference calls that returned, split warm vs cold container.",
    ["config", "cold"],
)

inference_phase_duration_seconds = Histogram(
    "demo_hub_inference_phase_duration_seconds",
    "Per-phase generate() wall-time as reported by the Modal container.",
    ["config", "phase"],
    buckets=INFERENCE_BUCKETS,
)

inference_cold_start_duration_seconds = Histogram(
    "demo_hub_inference_cold_start_duration_seconds",
    "Container lifecycle phase wall-time (snapshot_load / to_cuda / ...).",
    ["config", "phase"],
    buckets=COLD_START_BUCKETS,
)

inference_batch_size = Histogram(
    "demo_hub_inference_batch_size",
    "Effective batch size at GPU dispatch.",
    ["config"],
    buckets=BATCH_SIZE_BUCKETS,
)

modal_overhead_seconds = Histogram(
    "demo_hub_modal_overhead_seconds",
    "Submit→done wall-time minus container-reported work (Modal "
    "scheduling/queueing + poll quantization).",
    ["config"],
    buckets=QUEUE_WAIT_BUCKETS,
)

estimated_gpu_seconds_total = Counter(
    "demo_hub_estimated_gpu_seconds_total",
    "Approximate billable GPU seconds derived from per-request timings "
    "(work + cold start + scaledown tail per container session). The "
    "authoritative source is Modal billing / modal.container.running.",
    ["config", "gpu"],
)

estimated_gpu_cost_usd_total = Counter(
    "demo_hub_estimated_gpu_cost_usd_total",
    "estimated_gpu_seconds × published hourly rate (constants.GPU_HOURLY_USD).",
    ["config", "gpu"],
)


# --- Core service health --------------------------------------------------

http_request_duration_seconds = Histogram(
    "demo_hub_http_request_duration_seconds",
    "Core HTTP request wall-time by route template and status class.",
    ["method", "route", "status"],
    buckets=HTTP_BUCKETS,
)

db_query_duration_seconds = Histogram(
    "demo_hub_db_query_duration_seconds",
    "Postgres statement wall-time by operation (select/insert/...).",
    ["operation"],
    buckets=DB_BUCKETS,
)

db_errors_total = Counter(
    "demo_hub_db_errors_total",
    "Postgres statements that raised.",
    ["operation"],
)

rabbitmq_publish_total = Counter(
    "demo_hub_rabbitmq_publish_total",
    "RabbitMQ publishes by routing key and outcome.",
    ["routing_key", "status"],
)

pipeline_e2e_seconds = Histogram(
    "demo_hub_pipeline_e2e_seconds",
    "User-perceived latency: pipeline created → terminal status in DB.",
    ["pipeline_name", "status"],
    buckets=E2E_BUCKETS,
)
