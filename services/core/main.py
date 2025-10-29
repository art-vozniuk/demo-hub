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
from services.core.app.pipelines.router import router as pipelines_router
from services.core.app.auth.router import router as auth_router
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
    asyncio.create_task(start_pipeline_update_consumer(consumer))

    yield

    log.info("Shutting down core service")
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
app.include_router(pipelines_router, prefix="/api/v1/pipelines", tags=["pipelines"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
