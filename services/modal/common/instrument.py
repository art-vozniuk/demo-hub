"""Per-request instrumentation for Modal inference apps. Nothing is pushed:
each generate() call attaches an `_obs` block (phase timings, cold-start
info on the container's first response, batch size, GPU) to its result and
dispatch turns it into Prometheus observations. Sentry tracing continues
from the payload.

Usage: build one InferenceRunner per container in the snap=False enter
hook, then in generate():

    with self.runner.start(payload) as run:
        with run.phase("download"):
            ...
        return run.finish({"result_url": url})
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

SENTRY_TRACE_KEY = "sentry_trace"
SENTRY_BAGGAGE_KEY = "baggage"


def _start_transaction(payload: Mapping[str, Any], name: str):
    """Resume the pipeline's Sentry trace inside the container. Returns
    the entered transaction, or None when sentry isn't importable/active."""

    try:
        import sentry_sdk
    except ImportError:
        return None
    try:
        transaction = sentry_sdk.start_transaction(
            sentry_sdk.continue_trace(
                {
                    "sentry-trace": payload.get(SENTRY_TRACE_KEY) or "",
                    "baggage": payload.get(SENTRY_BAGGAGE_KEY) or "",
                },
                op="modal.generate",
                name=name,
            )
        )
        transaction.__enter__()
        pipeline_id = payload.get("pipeline_id")
        if pipeline_id:
            sentry_sdk.set_tag("pipeline_id", str(pipeline_id))
        return transaction
    except Exception:
        return None


class InferenceRun:
    """One generate() call: times phases, logs them, mirrors them as
    Sentry spans, and assembles the `_obs` response block."""

    def __init__(self, runner: "InferenceRunner", payload: Mapping[str, Any]) -> None:
        self._runner = runner
        self._log = runner._log
        self.request_id = str(payload.get("pipeline_id") or uuid.uuid4().hex[:8])
        self._t0 = time.perf_counter()
        self._timings: dict[str, float] = {}
        self._batch_size: int | None = None
        self._finished = False
        self._transaction = _start_transaction(payload, runner.config)
        # On the container's first request, stretch the transaction back to
        # the post-restore hook and span the measured GPU weight transfer.
        cold_wall = runner.consume_cold_wall()
        self._stretched = False
        if self._transaction is not None:
            try:
                if cold_wall:
                    start, end = cold_wall
                    self._transaction.start_timestamp = datetime.fromtimestamp(
                        start, timezone.utc
                    )
                    self._stretched = True
                    self.retro_span("cold.to_cuda", start, end, op="cold.to_cuda")
                self._transaction.set_tag("cold", "true" if cold_wall else "false")
            except Exception:
                pass

    def tag(self, key: str, value: Any) -> None:
        """Tag the active Sentry transaction (no-op without one)."""

        if self._transaction is not None:
            try:
                self._transaction.set_tag(key, str(value))
            except Exception:
                pass

    def retro_span(
        self, name: str, start_ts: float, end_ts: float, op: str | None = None
    ) -> None:
        """Span from wall-clock POSIX timestamps measured by hand — Sentry
        only, deliberately NOT added to `_obs` timings (no double count)."""

        if self._transaction is None or end_ts <= start_ts:
            return
        try:
            child = self._transaction.start_child(
                op=op or f"phase.{name}", name=name, start_timestamp=start_ts
            )
            child.finish(end_timestamp=end_ts)
        except Exception:
            pass

    def __enter__(self) -> "InferenceRun":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._transaction is not None:
            # A stretched (cold) transaction needs an explicit wall-clock
            # end: the SDK otherwise derives it from the original monotonic
            # start, pulling the end backwards past its own child spans.
            if self._stretched and exc is None:
                try:
                    self._transaction.finish(end_timestamp=time.time())
                except Exception:
                    pass
            self._transaction.__exit__(exc_type, exc, tb)
        if exc is not None and not self._finished:
            self._log.error(
                f"[{self.request_id}] {self._runner.config} failed after "
                f"{(time.perf_counter() - self._t0) * 1000:.0f}ms: {exc!r}"
            )

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        span = None
        try:
            import sentry_sdk

            span = sentry_sdk.start_span(op=f"phase.{name}", name=name)
            span.__enter__()
        except Exception:
            span = None
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            if span is not None:
                span.__exit__(None, None, None)
            self.observe(name, dt)

    def observe(self, name: str, seconds: float) -> None:
        self._timings[name] = self._timings.get(name, 0.0) + seconds
        self._log.info(f"[{self.request_id}] {name} done in {seconds * 1000:.0f}ms")

    def batch(self, n: int) -> None:
        self._batch_size = n

    def finish(self, result: dict[str, Any]) -> dict[str, Any]:
        """Attach the observability block and return the response."""

        self._finished = True
        total_s = time.perf_counter() - self._t0
        obs: dict[str, Any] = {
            "config": self._runner.config,
            "gpu": self._runner.gpu,
            "container_id": self._runner.container_id,
            "total_s": total_s,
            "timings": dict(self._timings),
            "scaledown_window_s": self._runner.scaledown_window_s,
        }
        if self._batch_size is not None:
            obs["batch_size"] = self._batch_size
        cold = self._runner.consume_cold()
        if cold:
            obs["cold"] = cold
        result["_obs"] = obs
        self._log.info(
            f"[{self.request_id}] {self._runner.config} done in "
            f"{total_s * 1000:.0f}ms "
            + " ".join(f"{k}={v * 1000:.0f}ms" for k, v in self._timings.items())
            + (f" cold={cold}" if cold else "")
        )
        return result


class InferenceRunner:
    """Container-scoped state: identity, GPU type, cold-start timings
    (reported exactly once, on the container's first response)."""

    def __init__(
        self,
        config: str,
        gpu: str,
        scaledown_window_s: float,
        log: logging.Logger | None = None,
        cold: Mapping[str, float] | None = None,
        cold_wall: tuple[float, float] | None = None,
    ) -> None:
        self.config = config
        self.gpu = gpu
        self.scaledown_window_s = scaledown_window_s
        self.container_id = uuid.uuid4().hex[:8]
        self._log = log or logging.getLogger(f"inference.{config}")
        self._cold: dict[str, float] | None = (
            {k: float(v) for k, v in cold.items() if v} if cold else None
        )
        # Wall-clock (start, end) of the measured cold-start work in the
        # @enter hook; consumed by the first run's Sentry transaction.
        self._cold_wall = cold_wall

    def consume_cold(self) -> dict[str, float] | None:
        cold, self._cold = self._cold, None
        return cold

    def consume_cold_wall(self) -> tuple[float, float] | None:
        wall, self._cold_wall = self._cold_wall, None
        return wall

    def start(self, payload: Mapping[str, Any]) -> InferenceRun:
        return InferenceRun(self, payload)
