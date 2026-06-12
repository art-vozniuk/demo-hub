"""Sentry trace propagation across process boundaries.

One pipeline = one Sentry trace. The FastAPI integration starts the
trace on POST /pipelines/queue; these helpers carry it over the two
non-HTTP hops where nothing propagates automatically:

  core --(RabbitMQ message)--> dispatch --(Modal payload)--> container

`trace_headers()` snapshots the ambient trace into a plain dict that
rides inside the message/payload; `continue_trace_from()` resumes it on
the other side as a new transaction. Everything degrades to a no-op
when Sentry has no DSN (tests, local runs without Sentry).
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
    """Resume the trace embedded in `carrier` inside a new transaction.

    Starts a fresh trace when the carrier has no sentry keys, so a
    directly-published message still produces a complete transaction.
    """

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
def span(op: str, description: str | None = None) -> Iterator[None]:
    """A child span on whatever transaction is ambient (no-op without one)."""

    with sentry_sdk.start_span(op=op, name=description or op):
        yield
