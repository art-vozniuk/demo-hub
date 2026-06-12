"""Sentry for Modal containers — same DSN as the VDS services, tagged by
environment + service so issues land in the right Sentry env. DSN +
SENTRY_ENVIRONMENT come from the `sentry` Modal secret (dev -> development,
main -> production), mirroring how VDS services derive environment from ENV.

Init once per container AFTER snapshot restore (snap=False enter) — sentry's
background transport thread must not be frozen into a memory snapshot.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("modal.sentry")

_inited = False


def _traces_sampler(ctx):
    # Web submit/poll transactions are routing noise (dispatch polls every
    # few seconds); the real trace resumes from the payload in generate().
    if ctx.get("asgi_scope") is not None:
        return 0.0
    parent = ctx.get("parent_sampled")
    if parent is not None:
        return parent
    return 1.0


def init_sentry(service: str) -> None:
    """Idempotent per-container init; no-op without SENTRY_DSN (e.g. at
    local deploy time, where the secret isn't injected)."""

    global _inited
    if _inited:
        return
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    import sentry_sdk

    environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        send_default_pii=True,
        enable_logs=True,
        traces_sampler=_traces_sampler,
    )
    sentry_sdk.set_tag("service", service)
    sentry_sdk.set_tag("platform", "modal")
    _inited = True
    log.info("Sentry initialized: service=%s environment=%s", service, environment)
