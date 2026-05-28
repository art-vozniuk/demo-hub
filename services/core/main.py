# ruff: noqa: E402
import logging
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import services.common.logging.config as logging_config

logging_config.configure()

from services.core.app.recast.router import router as recast_router
from services.core.app.splats.router import router as splats_router
from services.core.app.pipelines.router import router as pipelines_router
from services.core.app.generative.router import router as generative_router
from services.core.app.wallet.router import router as wallet_router
from services.core.app.editor_scenes.router import router as editor_scenes_router
from services.core.app.permissions.router import router as permissions_router
from services.core.app.bench.router import router as bench_router
from services.common.middleware.exception import ExceptionMiddleware
from services.common.database.middleware import DatabaseMiddleware
from services.core.app.dependencies import (
    init_rabbitmq,
    shutdown_rabbitmq,
    get_rabbitmq_consumer,
    init_redis,
    shutdown_redis,
)
from services.core.app.pipelines.consumer import start_pipeline_update_consumer

from services.core.app.config import config

log = logging.getLogger(__name__)

build_tag = os.getenv("BUILD_TAG", "unknown")
log.info(f"starting core service, build tag: {build_tag}")

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
    sentry_sdk.set_tag("service", "core")
    log.info("Sentry initialized for core service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up core service")
    await init_redis()
    await init_rabbitmq()

    consumer = await get_rabbitmq_consumer()
    # Hold a strong reference so the task can't be garbage-collected
    # mid-flight — bare `asyncio.create_task(...)` returns an object that
    # the loop only weakrefs, and CPython has historically dropped tasks
    # whose only owner was the loop itself.
    app.state.background_tasks = {
        asyncio.create_task(start_pipeline_update_consumer(consumer)),
    }

    yield

    log.info("Shutting down core service")
    for task in app.state.background_tasks:
        task.cancel()
    await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
    await shutdown_rabbitmq()
    await shutdown_redis()


app = FastAPI(
    title="core",
    description="Core service",
    docs_url=None,
    openapi_url="/docs/openapi.json",
    redoc_url="/docs",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    """Prometheus scrape target. Same shape as any other Prometheus
    text-exposition endpoint — registered against the default registry
    so any service code that imports services.common.observability.metrics
    contributes."""

    from fastapi import Response
    from services.common.observability import collect_text, CONTENT_TYPE_LATEST
    # Import for side effects: registers the canonical metric set on
    # the default registry, even if no code has touched them yet.
    import services.common.observability.metrics  # noqa: F401

    return Response(content=collect_text(), media_type=CONTENT_TYPE_LATEST)


app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.add_middleware(ExceptionMiddleware)
app.add_middleware(DatabaseMiddleware)


app.include_router(recast_router, prefix="/api/v1/recast", tags=["recast"])
app.include_router(splats_router, prefix="/api/v1/splats", tags=["splats"])
app.include_router(pipelines_router, prefix="/api/v1/pipelines", tags=["pipelines"])
app.include_router(generative_router, prefix="/api/v1/generative", tags=["generative"])
app.include_router(wallet_router, prefix="/api/v1/me", tags=["wallet"])
app.include_router(
    editor_scenes_router, prefix="/api/v1/editor", tags=["editor_scenes"]
)
app.include_router(permissions_router, prefix="/api/v1/me", tags=["permissions"])
app.include_router(bench_router, prefix="/api/v1/bench", tags=["bench"])
