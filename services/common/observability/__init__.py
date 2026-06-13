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
    "register_db_pool_collector",
    "start_metrics_server",
]

log = logging.getLogger(__name__)

_db_pool_collector_registered = False


def register_db_pool_collector(stats_fn) -> None:
    """Register a scrape-time collector for SQLAlchemy pool saturation.

    `stats_fn()` returns {checked_out, idle, capacity} (or None when the
    pool can't be read). Read at scrape so the value is never stale, and
    idempotent so reimporting the DB module is harmless."""

    global _db_pool_collector_registered
    if _db_pool_collector_registered:
        return

    from prometheus_client.core import GaugeMetricFamily

    class _DbPoolCollector:
        def collect(self):
            try:
                s = stats_fn()
            except Exception:
                s = None
            if not s:
                return
            conns = GaugeMetricFamily(
                "demo_hub_db_pool_connections",
                "SQLAlchemy connection-pool connections by state.",
                labels=["state"],
            )
            conns.add_metric(["checked_out"], s["checked_out"])
            conns.add_metric(["idle"], s["idle"])
            yield conns
            cap = GaugeMetricFamily(
                "demo_hub_db_pool_capacity",
                "Max connections the pool can hand out (pool_size + max_overflow).",
            )
            cap.add_metric([], s["capacity"])
            yield cap

    REGISTRY.register(_DbPoolCollector())
    _db_pool_collector_registered = True


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
