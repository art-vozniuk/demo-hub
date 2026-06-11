"""Per-container inference metrics pushed to the Pushgateway.

Every model app builds one InferenceMetrics in @modal.enter(snap=False) and
pushes under a stable per-container key (one Pushgateway group per container,
never per request → no group leak). `config` = pipeline key (e.g. "sharp"),
`gpu` = GPU type for cost attribution. Names share the demo_hub_inference_*
prefix so one Grafana dashboard covers every pipeline (filter by `config`).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import contextmanager

log = logging.getLogger("inference.metrics")

_COLD = (0.5, 1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120)
_PHASE = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120)
_BATCH = (1, 2, 4, 8, 12, 16, 24, 32)


def _push(registry, config: str, container_id: str) -> None:
    url = os.environ.get("PUSHGATEWAY_URL")
    if not url:
        return
    from prometheus_client import push_to_gateway

    token = os.environ.get("PUSHGATEWAY_TOKEN")
    handler = None
    if token:
        import base64
        from urllib.request import Request, urlopen

        enc = base64.b64encode(f"modal:{token}".encode()).decode()

        def handler(url, method, timeout, headers, data):  # noqa: ARG001
            req = Request(url, data=data, method=method)
            for k, v in headers:
                req.add_header(k, v)
            req.add_header("Authorization", f"Basic {enc}")
            return urlopen(req, timeout=timeout)

    try:
        kw = {"handler": handler} if handler else {}
        push_to_gateway(
            url,
            job="inference",
            registry=registry,
            grouping_key={"config": config, "container_id": container_id},
            timeout=5.0,
            **kw,
        )
    except Exception:
        # Don't fail inference on a metrics push; surface in logs + Sentry.
        log.error(
            "pushgateway push failed (url=%s config=%s)", url, config, exc_info=True
        )


class InferenceMetrics:
    def __init__(self, config: str, gpu: str) -> None:
        from prometheus_client import CollectorRegistry, Counter, Histogram

        self.config = config
        self.gpu = gpu
        self.container_id = uuid.uuid4().hex[:8]
        self._started = time.monotonic()
        self.reg = CollectorRegistry()
        self._cold = Histogram(
            "demo_hub_inference_cold_start_duration_seconds",
            "Container lifecycle hook wall-time, by phase.",
            ["config", "phase"], buckets=_COLD, registry=self.reg,
        )
        self._phase = Histogram(
            "demo_hub_inference_phase_duration_seconds",
            "Per-phase generate() wall-time (download/decode/gpu/upload).",
            ["config", "phase"], buckets=_PHASE, registry=self.reg,
        )
        self._batch = Histogram(
            "demo_hub_inference_batch_size",
            "Effective batch size at GPU dispatch.",
            ["config"], buckets=_BATCH, registry=self.reg,
        )
        self._uptime = Counter(
            "demo_hub_inference_container_uptime_seconds_total",
            "Container uptime seconds (x published GPU rate = billed cost).",
            ["config", "gpu"], registry=self.reg,
        )

    def cold_start(self, phase: str, seconds: float) -> None:
        self._cold.labels(config=self.config, phase=phase).observe(seconds)

    def observe(self, phase: str, seconds: float) -> None:
        self._phase.labels(config=self.config, phase=phase).observe(seconds)

    @contextmanager
    def phase(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - t0)

    def batch(self, n: int) -> None:
        self._batch.labels(config=self.config).observe(n)

    def push(self) -> None:
        _push(self.reg, self.config, self.container_id)

    def push_uptime(self) -> None:
        self._uptime.labels(config=self.config, gpu=self.gpu).inc(
            time.monotonic() - self._started
        )
        self.push()
