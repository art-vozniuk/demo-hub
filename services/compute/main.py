import logging
import asyncio
import signal

import services.common.logging.config as logging_config

import services.compute.app.pipelines.router as pipeline_router

from services.compute.app.config import config

logging_config.configure()
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
    )
    sentry_sdk.set_tag("service", "compute")

shutdown_event = asyncio.Event()


def signal_handler(sig, frame):
    log.info(f"Received signal {sig}, initiating shutdown")
    shutdown_event.set()


async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log.info("Starting compute worker")

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
