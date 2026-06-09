"""Prometheus instrumentation shared across services.

Two consumption shapes:

  - Long-lived services (core, dispatch): expose a `/metrics` endpoint
    that Prometheus scrapes. Use `metrics_app()` (FastAPI Mount target)
    or `start_metrics_server(port)` (for the dispatch worker, which is
    not a FastAPI app).

  - Ephemeral Modal containers: push to the Prometheus Pushgateway
    instead, because the container address isn't stable and Prometheus
    has no chance to scrape it before it scales down. See `push_metrics`.

All metric names use the `demo_hub_` prefix so they're easy to filter in
Grafana, and every metric is registered against `REGISTRY` (the default
process registry) so prometheus_client's standard scrape format works
without extra wiring.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    push_to_gateway,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "Counter",
    "Gauge",
    "Histogram",
    "REGISTRY",
    "CollectorRegistry",
    "build_registry",
    "generate_latest",
    "push_metrics",
    "start_metrics_server",
]

log = logging.getLogger(__name__)


# Histogram bucket sets reused across services. Tuned for our expected
# distributions — short-tail HTTP calls, long-tail inference durations.
HTTP_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)
INFERENCE_BUCKETS = (
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
)
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
)


def build_registry() -> CollectorRegistry:
    """Fresh, isolated registry for push-based metric flows.

    Ephemeral pushers want their own registry so unrelated process
    metrics don't get pushed alongside.
    """
    return CollectorRegistry()


def start_metrics_server(port: int) -> None:
    """Spin up the prometheus_client built-in HTTP server (background
    thread). Use this in non-FastAPI processes — e.g. the dispatch
    worker, which has no HTTP surface of its own."""

    from prometheus_client import start_http_server

    start_http_server(port)
    log.info(f"prometheus /metrics server started on :{port}")


def push_metrics(
    job: str,
    registry: CollectorRegistry,
    grouping_key: dict[str, str] | None = None,
    gateway: str | None = None,
    timeout: float = 5.0,
) -> None:
    """Push the given registry to the Prometheus Pushgateway.

    `grouping_key` namespaces this push so concurrent containers don't
    overwrite each other's samples on the gateway (each container ends
    up as a distinct series). `gateway` defaults to the
    PUSHGATEWAY_URL env var.
    """

    url = gateway or os.environ.get("PUSHGATEWAY_URL")
    if not url:
        log.debug("PUSHGATEWAY_URL not set; skipping push")
        return

    auth_token = os.environ.get("PUSHGATEWAY_TOKEN")
    handler = None
    if auth_token:
        import base64

        # prometheus_client takes a handler callable matching the
        # urllib request shape; the simplest path is to bake an auth
        # header into a Request inside _handler.
        encoded = base64.b64encode(f"modal:{auth_token}".encode()).decode()

        def _handler(url, method, timeout, headers, data):  # noqa: ARG001
            from urllib.request import Request, urlopen

            req = Request(url, data=data, method=method)
            for k, v in headers:
                req.add_header(k, v)
            req.add_header("Authorization", f"Basic {encoded}")
            return urlopen(req, timeout=timeout)

        handler = _handler

    try:
        if handler is not None:
            push_to_gateway(
                url,
                job=job,
                registry=registry,
                grouping_key=grouping_key or {},
                handler=handler,
                timeout=timeout,
            )
        else:
            push_to_gateway(
                url,
                job=job,
                registry=registry,
                grouping_key=grouping_key or {},
                timeout=timeout,
            )
    except Exception as e:
        # Metric push failures must NEVER take down the inference call.
        log.warning(f"push_to_gateway failed (job={job}): {e}")


def collect_text(registries: Iterable[CollectorRegistry] | None = None) -> bytes:
    """Render all metrics as Prometheus text exposition format. Pass
    `registries=None` to emit the default REGISTRY."""

    if registries is None:
        return generate_latest()
    out = bytearray()
    for reg in registries:
        out.extend(generate_latest(reg))
    return bytes(out)
