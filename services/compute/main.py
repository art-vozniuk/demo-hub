# ruff: noqa: E402
import logging
import asyncio
import signal

import services.common.logging.config as logging_config

logging_config.configure()

import services.compute.app.pipelines.consumer as pipeline_router

from services.compute.app.config import config

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

    # Expose Prometheus metrics on :9091. The worker has no other HTTP
    # surface, so this stands alone — Prometheus scrapes compute:9091
    # over the docker network. Port 9091 (not 9090) avoids the cognitive
    # collision with Prometheus's own UI port.
    from prometheus_client import start_http_server

    start_http_server(9091)
    log.info("Prometheus metrics endpoint listening on :9091")

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
