# ruff: noqa: E402
import logging
import asyncio
import os
import signal

import services.common.logging.config as logging_config

logging_config.configure()

import services.dispatch.app.pipelines.consumer as pipeline_router
import services.common.observability.metrics  # noqa: F401  (registers metrics)

from services.dispatch.app.config import config
from services.dispatch.app.pipelines.modal_client import close_client
from services.common.observability import start_metrics_server

log = logging.getLogger(__name__)

if config.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.ENV,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=1.0,
    )
    sentry_sdk.set_tag("service", "dispatch")
    log.info("Sentry initialized for dispatch service")

shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    log.info(f"Received signal {sig}, initiating shutdown")
    shutdown_event.set()


async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log.info("Starting dispatch worker")

    # /metrics on a separate port — dispatch has no HTTP surface of its
    # own, so prometheus_client's built-in WSGI server is the simplest
    # way to expose them. Off by default (port=0) for tests.
    metrics_port = int(os.environ.get("DISPATCH_METRICS_PORT", "0"))
    if metrics_port > 0:
        start_metrics_server(metrics_port)

    await pipeline_router.init()

    log.info("Dispatch worker is running, waiting for messages...")

    await shutdown_event.wait()

    try:
        await pipeline_router.shutdown()
    except Exception as e:
        log.error(f"Failed to shutdown pipeline router: {e}")

    try:
        await close_client()
    except Exception as e:
        log.error(f"Failed to close shared Modal httpx client: {e}")

    log.info("Dispatch worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
