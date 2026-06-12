"""Sentry trace propagation over the non-HTTP hops (core → RabbitMQ →
dispatch → Modal payload), so one pipeline = one trace. All helpers are
no-ops when Sentry has no DSN.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping

import sentry_sdk

SENTRY_TRACE_KEY = "sentry_trace"
SENTRY_BAGGAGE_KEY = "baggage"


def trace_headers() -> dict[str, str]:
    """Snapshot the current trace context for embedding in a message."""

    headers: dict[str, str] = {}
    traceparent = sentry_sdk.get_traceparent()
    if traceparent:
        headers[SENTRY_TRACE_KEY] = traceparent
    baggage = sentry_sdk.get_baggage()
    if baggage:
        headers[SENTRY_BAGGAGE_KEY] = baggage
    return headers


@contextmanager
def continue_trace_from(
    carrier: Mapping[str, Any],
    *,
    op: str,
    name: str,
    tags: Mapping[str, str] | None = None,
) -> Iterator[None]:
    """Resume the trace embedded in `carrier` (or start a fresh one)."""

    transaction = sentry_sdk.continue_trace(
        {
            "sentry-trace": carrier.get(SENTRY_TRACE_KEY) or "",
            "baggage": carrier.get(SENTRY_BAGGAGE_KEY) or "",
        },
        op=op,
        name=name,
    )
    with sentry_sdk.start_transaction(transaction):
        for key, value in (tags or {}).items():
            sentry_sdk.set_tag(key, value)
        yield


@contextmanager
def span(op: str, description: str | None = None) -> Iterator[Any]:
    """A child span on whatever transaction is ambient (no-op without one)."""

    with sentry_sdk.start_span(op=op, name=description or op) as s:
        yield s


def retro_span(op: str, name: str, start_ts: float, end_ts: float) -> None:
    """Backdated child span from wall-clock POSIX timestamps — for work
    that finished before we could open a live span (e.g. queue wait)."""

    if end_ts <= start_ts:
        return
    try:
        parent = sentry_sdk.get_current_span()
        if parent is None:
            return
        child = parent.start_child(op=op, name=name, start_timestamp=start_ts)
        child.finish(end_timestamp=end_ts)
    except Exception:
        pass
