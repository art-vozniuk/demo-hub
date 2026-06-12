"""Prometheus instrumentation shared across services: every long-lived
service exposes /metrics for scraping (no push path anywhere). Metric
definitions live in metrics.py, buckets in services/common/constants.py.
"""

from __future__ import annotations

import logging
from typing import Iterable

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
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
    "collect_text",
    "generate_latest",
    "start_metrics_server",
]

log = logging.getLogger(__name__)


def start_metrics_server(port: int) -> None:
    """Spin up the prometheus_client built-in HTTP server (background
    thread). Use this in non-FastAPI processes — e.g. the dispatch
    worker, which has no HTTP surface of its own."""

    from prometheus_client import start_http_server

    start_http_server(port)
    log.info(f"prometheus /metrics server started on :{port}")


def collect_text(registries: Iterable[CollectorRegistry] | None = None) -> bytes:
    """Render all metrics as Prometheus text exposition format. Pass
    `registries=None` to emit the default REGISTRY."""

    if registries is None:
        return generate_latest()
    out = bytearray()
    for reg in registries:
        out.extend(generate_latest(reg))
    return bytes(out)
