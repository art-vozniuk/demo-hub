"""Canonical metric definitions for the inference + bench stack.

Each metric is grouped by the framework it serves (RED / USE / cost /
cold-start / bench). All names share the `demo_hub_` prefix. Labels are
deliberately low-cardinality so cardinality explosion in Prometheus is
impossible just by adding more variants.

The dispatch worker uses these directly. Modal containers re-declare
the same metric names on a push-only registry — same shape so Grafana
panels work uniformly across both sources.
"""

from __future__ import annotations

from . import (
    COLD_START_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    INFERENCE_BUCKETS,
    HTTP_BUCKETS,
)


# --- RED (service-level, dispatch-side) ---------------------------------

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


# --- Bench-run-level ----------------------------------------------------

bench_run_images_total = Counter(
    "demo_hub_bench_run_images_total",
    "Images successfully generated, tagged by run_id and config.",
    ["run_id", "config", "tier"],
)

bench_run_failures_total = Counter(
    "demo_hub_bench_run_failures_total",
    "Failed inference requests inside a bench run.",
    ["run_id", "config", "tier", "error_type"],
)

bench_run_cost_usd_total = Counter(
    "demo_hub_bench_run_cost_usd_total",
    "Estimated cost charged against a bench run, in USD.",
    ["run_id", "config", "tier"],
)

bench_run_active = Gauge(
    "demo_hub_bench_run_active",
    "1 while a bench run is in flight, 0 otherwise.",
    ["run_id", "config", "tier"],
)


# --- Inference-phase breakdown (pushed from Modal) ----------------------
#
# These are duplicated on the Modal-container side (push_registry, same
# names) so Grafana panels can union across dispatch-scraped and
# pushgateway-stored series transparently.

flux_io_duration_seconds = Histogram(
    "demo_hub_flux_io_duration_seconds",
    "I/O phase wall-time inside a Modal generate() call.",
    ["config", "phase"],
    buckets=HTTP_BUCKETS,
)

flux_pipe_duration_seconds = Histogram(
    "demo_hub_flux_pipe_duration_seconds",
    "GPU pipe(...) wall-time per batched call.",
    ["config"],
    buckets=INFERENCE_BUCKETS,
)

flux_batch_size = Histogram(
    "demo_hub_flux_batch_size",
    "Effective batch size at GPU dispatch time.",
    ["config"],
    buckets=(1, 2, 4, 8, 12, 16, 24, 32),
)

flux_cold_start_duration_seconds = Histogram(
    "demo_hub_flux_cold_start_duration_seconds",
    "Container lifecycle hook wall-time, by phase.",
    ["config", "phase"],
    buckets=COLD_START_BUCKETS,
)

flux_container_uptime_seconds_total = Counter(
    "demo_hub_flux_container_uptime_seconds_total",
    "Sum of container uptime seconds — the basis for cost computation.",
    ["config", "gpu"],
)
