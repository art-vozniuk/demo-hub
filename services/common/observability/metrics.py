"""Canonical metric definitions for the production inference stack.

Three groups:

  - RED (service-level): the four golden signals on the dispatch
    pipeline + the Modal HTTP edge — RPS, error rate, latency
    percentiles, retry counts.
  - Inference internals: I/O phase breakdown, GPU pipe wall-time,
    realized batch size. Pushed from inside Modal containers since
    they're ephemeral and can't be scraped directly.
  - Cold start: per-phase cold-start duration + total container
    uptime (the basis for cost accounting against published Modal
    GPU rates).

All names share the `demo_hub_` prefix. Labels are kept low-cardinality
on purpose — every new dimension here costs Prometheus series.

The dispatch worker uses these directly (the import registers them on
prometheus_client's default REGISTRY, picked up by /metrics). Modal
containers re-declare the same names on a CollectorRegistry they push
to the Pushgateway — same metric shape across both sources so Grafana
panels union seamlessly.
"""

from __future__ import annotations

from . import (
    COLD_START_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    HTTP_BUCKETS,
    INFERENCE_BUCKETS,
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


# --- Inference internals (pushed from Modal) ----------------------------
#
# These get re-declared on Modal-side CollectorRegistry objects with the
# same names — push_to_gateway then ingests them into Prometheus through
# the Pushgateway. The Grafana panels query them identically regardless
# of whether the series came from a scrape or a push.

flux_io_duration_seconds = Histogram(
    "demo_hub_flux_io_duration_seconds",
    "I/O phase wall-time inside a Modal generate() call.",
    ["config", "phase"],
    buckets=HTTP_BUCKETS,
)

flux_pipe_duration_seconds = Histogram(
    "demo_hub_flux_pipe_duration_seconds",
    "GPU pipe(...) wall-time per (batched) call.",
    ["config"],
    buckets=INFERENCE_BUCKETS,
)

flux_batch_size = Histogram(
    "demo_hub_flux_batch_size",
    "Effective batch size at GPU dispatch time.",
    ["config"],
    buckets=(1, 2, 4, 8, 12, 16, 24, 32),
)


# --- Cold start / container lifecycle -----------------------------------

flux_cold_start_duration_seconds = Histogram(
    "demo_hub_flux_cold_start_duration_seconds",
    "Container lifecycle hook wall-time, by phase.",
    ["config", "phase"],
    buckets=COLD_START_BUCKETS,
)

flux_container_uptime_seconds_total = Counter(
    "demo_hub_flux_container_uptime_seconds_total",
    "Sum of container uptime seconds. Multiplied by the published Modal "
    "GPU rate at dashboard time to get billed cost.",
    ["config", "gpu"],
)
