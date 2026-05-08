"""Shared Prometheus metric definitions used by core and compute.

All metric instances live here as module-level singletons so any caller
that imports a metric gets the same object — `prometheus_client` keys
metrics by (name, labels) inside a default registry, and re-creating a
metric with the same name from two import paths raises.
"""

from prometheus_client import Counter, Gauge, Histogram

# ── HTTP / API ────────────────────────────────────────────────────────
# Most HTTP request metrics come from prometheus-fastapi-instrumentator
# automatically. We add our own only for app-specific counts that aren't
# tied to a request (e.g. background work).

# ── S3 ────────────────────────────────────────────────────────────────
# Both core (uploads) and compute (downloads + uploads) hit Supabase
# storage. Tracking retries here pays for itself: we already saw a
# transient ContentLengthError class, and the retry counter surfaces
# upstream flakiness as it happens.
s3_operations_total = Counter(
    "s3_operations_total",
    "S3 operations grouped by operation and outcome",
    ["op", "status"],  # op: upload|download ; status: success|failure|retry
)

# ── Pipelines (product) ───────────────────────────────────────────────
pipeline_started_total = Counter(
    "pipeline_started_total",
    "Pipelines accepted by the queue endpoint",
    ["pipeline_name"],
)

pipeline_completed_total = Counter(
    "pipeline_completed_total",
    "Pipelines that reached a terminal state",
    ["pipeline_name", "status", "error_kind"],
    # status: completed|failed
    # error_kind: empty for success; short token for failure (e.g. "no_face",
    # "model_load", "s3_download", "unknown") — keep cardinality low
)

pipeline_duration_seconds = Histogram(
    "pipeline_duration_seconds",
    "Wall-clock time from compute consumer pickup to terminal status",
    ["pipeline_name", "status"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

pipeline_queue_wait_seconds = Histogram(
    "pipeline_queue_wait_seconds",
    "Time from core enqueue to compute pickup (RabbitMQ + worker readiness)",
    ["pipeline_name"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 300),
)

pipeline_in_flight = Gauge(
    "pipeline_in_flight",
    "Pipelines currently executing in the compute worker",
    ["pipeline_name"],
)

# ── Face detection (product insight) ──────────────────────────────────
face_detected_count = Histogram(
    "face_detected_count",
    "How many faces the detector found per image",
    ["image_role"],  # source|target
    buckets=(0, 1, 2, 3, 5, 10),
)
