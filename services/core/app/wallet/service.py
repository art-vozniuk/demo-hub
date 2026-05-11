"""Wallet service. Balance = SUM(token_transactions.delta) for an
owner; per-owner pg_advisory_xact_lock serializes charges. Grants and
charges/refunds are idempotent via partial UNIQUE indexes."""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PipelineType, TokenTransaction

log = logging.getLogger(__name__)


SIGNUP_GRANT = 200
ANON_GRANT = 15

# Namespaces keep user-id and anon-id locks from colliding on hash.
_USER_LOCK_NS = "wallet:user:"
_ANON_LOCK_NS = "wallet:anon:"


class InsufficientFunds(Exception):
    """Raised when charge() would push balance below zero."""


async def _acquire_user_lock(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))").bindparams(
            k=f"{_USER_LOCK_NS}{user_id}"
        )
    )


async def _acquire_anon_lock(db: AsyncSession, anon_id: UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))").bindparams(
            k=f"{_ANON_LOCK_NS}{anon_id}"
        )
    )


async def get_user_balance(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(TokenTransaction.delta), 0)).where(
            TokenTransaction.user_id == user_id
        )
    )
    return int(result.scalar_one())


async def get_anon_balance(db: AsyncSession, anon_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(TokenTransaction.delta), 0)).where(
            TokenTransaction.anon_id == anon_id
        )
    )
    return int(result.scalar_one())


async def get_pipeline_type(db: AsyncSession, name: str) -> Optional[PipelineType]:
    result = await db.execute(select(PipelineType).where(PipelineType.name == name))
    return result.scalar_one_or_none()


async def grant_signup_if_needed(db: AsyncSession, user_id: UUID) -> None:
    stmt = (
        pg_insert(TokenTransaction)
        .values(
            user_id=user_id,
            delta=SIGNUP_GRANT,
            reason="signup_grant",
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=["user_id"],
            index_where=text("reason = 'signup_grant' AND user_id IS NOT NULL"),
        )
    )
    result = await db.execute(stmt)
    if result.rowcount > 0:
        log.info(f"granted signup +{SIGNUP_GRANT} to user {user_id}")


async def grant_anon_if_needed(db: AsyncSession, anon_id: UUID) -> None:
    stmt = (
        pg_insert(TokenTransaction)
        .values(
            anon_id=anon_id,
            delta=ANON_GRANT,
            reason="anon_grant",
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=["anon_id"],
            index_where=text("reason = 'anon_grant' AND anon_id IS NOT NULL"),
        )
    )
    result = await db.execute(stmt)
    if result.rowcount > 0:
        log.info(f"granted anon +{ANON_GRANT} to anon {anon_id}")


async def migrate_anon_to_user(
    db: AsyncSession,
    user_id: UUID,
    anon_id: UUID,
) -> int:
    """Move remaining anon balance into user. Idempotent per anon_id."""
    existing = await db.execute(
        select(TokenTransaction.id)
        .where(TokenTransaction.anon_id == anon_id)
        .where(TokenTransaction.reason == "anon_migration")
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return 0

    await _acquire_anon_lock(db, anon_id)
    balance = await get_anon_balance(db, anon_id)
    if balance <= 0:
        return 0

    now = datetime.now(timezone.utc)
    await db.execute(
        TokenTransaction.__table__.insert().values(
            anon_id=anon_id,
            delta=-balance,
            reason="anon_migration",
            created_at=now,
        )
    )
    await db.execute(
        TokenTransaction.__table__.insert().values(
            user_id=user_id,
            anon_id=anon_id,
            delta=balance,
            reason="anon_migration",
            created_at=now,
        )
    )
    log.info(f"migrated +{balance} from anon {anon_id} to user {user_id}")
    return balance


async def charge(
    db: AsyncSession,
    *,
    pipeline_id: UUID,
    pipeline_type_id: int,
    cost: int,
    user_id: Optional[UUID],
    anon_id: Optional[UUID],
) -> None:
    """Charge under per-owner lock. Raises InsufficientFunds if balance
    would go negative; duplicate pipeline_id calls no-op."""
    if cost <= 0:
        return

    if user_id is not None:
        await _acquire_user_lock(db, user_id)
        balance = await get_user_balance(db, user_id)
    else:
        assert anon_id is not None, "charge needs user_id or anon_id"
        await _acquire_anon_lock(db, anon_id)
        balance = await get_anon_balance(db, anon_id)

    if balance < cost:
        raise InsufficientFunds()

    stmt = (
        pg_insert(TokenTransaction)
        .values(
            user_id=user_id,
            anon_id=anon_id,
            pipeline_id=pipeline_id,
            pipeline_type_id=pipeline_type_id,
            delta=-cost,
            reason="charge",
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=["pipeline_id", "reason"],
            index_where=text("pipeline_id IS NOT NULL"),
        )
    )
    await db.execute(stmt)


async def refund(db: AsyncSession, pipeline_id: UUID) -> None:
    """Refund the prior charge. Idempotent per pipeline_id."""
    charge_row = await db.execute(
        select(TokenTransaction)
        .where(TokenTransaction.pipeline_id == pipeline_id)
        .where(TokenTransaction.reason == "charge")
        .limit(1)
    )
    charge_obj = charge_row.scalar_one_or_none()
    if charge_obj is None:
        log.info(f"no charge for pipeline {pipeline_id}, nothing to refund")
        return

    stmt = (
        pg_insert(TokenTransaction)
        .values(
            user_id=charge_obj.user_id,
            anon_id=charge_obj.anon_id,
            pipeline_id=pipeline_id,
            pipeline_type_id=charge_obj.pipeline_type_id,
            delta=-charge_obj.delta,  # flip sign of the charge
            reason="refund",
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=["pipeline_id", "reason"],
            index_where=text("pipeline_id IS NOT NULL"),
        )
    )
    result = await db.execute(stmt)
    if result.rowcount > 0:
        log.info(f"refunded {-charge_obj.delta} for pipeline {pipeline_id}")
