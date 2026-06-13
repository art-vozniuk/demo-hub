import logging
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from .config import config
from services.common.observability import register_db_pool_collector

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    def dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


engine = create_async_engine(
    config.DATABASE_URL,
    echo=config.DATABASE_ECHO,
    pool_size=config.DATABASE_POOL_SIZE,
    max_overflow=config.DATABASE_MAX_OVERFLOW,
    pool_timeout=config.DATABASE_POOL_TIMEOUT,
    pool_recycle=config.DATABASE_POOL_RECYCLE,
    pool_pre_ping=True,
)


def _statement_operation(statement: str) -> str:
    op = statement.lstrip().split(" ", 1)[0].lower() if statement else ""
    return (
        op
        if op in {"select", "insert", "update", "delete", "begin", "commit"}
        else "other"
    )


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _db_timer_start(conn, cursor, statement, parameters, context, executemany):
    context._demo_hub_t0 = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _db_timer_stop(conn, cursor, statement, parameters, context, executemany):
    from services.common.observability.metrics import db_query_duration_seconds

    t0 = getattr(context, "_demo_hub_t0", None)
    if t0 is not None:
        db_query_duration_seconds.labels(
            operation=_statement_operation(statement)
        ).observe(time.perf_counter() - t0)


@event.listens_for(engine.sync_engine, "handle_error")
def _db_error(exception_context):
    from services.common.observability.metrics import db_errors_total

    statement = exception_context.statement or ""
    db_errors_total.labels(operation=_statement_operation(statement)).inc()


async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def _pool_stats() -> dict[str, float] | None:
    """Live connection-pool counters for the saturation collector. Workers
    contending for connections shows up as checked_out nearing capacity."""

    try:
        pool = engine.sync_engine.pool
        return {
            "checked_out": pool.checkedout(),
            "idle": pool.checkedin(),
            "capacity": config.DATABASE_POOL_SIZE + config.DATABASE_MAX_OVERFLOW,
        }
    except Exception:
        return None


register_db_pool_collector(_pool_stats)
