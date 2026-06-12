# ruff: noqa: E402
import logging
import asyncio
import os
import signal

import services.common.logging.config as logging_config

logging_config.configure()

import services.compute.app.pipelines.consumer as pipeline_router
import services.common.observability.metrics  # noqa: F401  (registers metrics)

from services.compute.app.config import config
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
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
        _experiments={
            "attach_logger_name": True,
        },
    )
    sentry_sdk.set_tag("service", "compute")
    log.info("Sentry initialized for compute service")

shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    log.info(f"Received signal {sig}, initiating shutdown")
    shutdown_event.set()


async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log.info("Starting compute worker")

    # /metrics on its own port (compute has no HTTP surface otherwise),
    # mirroring dispatch. Scraped by Prometheus as the `compute` job.
    metrics_port = int(os.environ.get("COMPUTE_METRICS_PORT", "0"))
    if metrics_port > 0:
        start_metrics_server(metrics_port)

    await pipeline_router.init()

    log.info("Compute worker is running, waiting for messages...")

    await shutdown_event.wait()

    try:
        await pipeline_router.shutdown()
    except Exception as e:
        log.error(f"Failed to shutdown pipeline router: {e}")

    log.info("Compute worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
