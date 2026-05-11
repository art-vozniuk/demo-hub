import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from services.common.auth.models import User
from services.common.database import DbSession

from . import service
from .models import PipelineType
from .schemas import BalanceResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _get_optional_user_dep():
    # Lazy import to avoid circular-import friction with tests.
    from ..dependencies import get_current_user_optional

    return get_current_user_optional


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    db: DbSession,
    user: Optional[User] = Depends(_get_optional_user_dep()),
) -> BalanceResponse:
    """Public read of the pricing catalog + signup grant; returns the
    caller's balance when authenticated (and lazily issues the one-time
    signup grant), or 0 for anonymous callers."""

    types_result = await db.execute(select(PipelineType.name, PipelineType.base_cost))
    pipeline_costs = {name: cost for name, cost in types_result.all()}

    if user is None:
        return BalanceResponse(
            tokens=0,
            pipeline_costs=pipeline_costs,
            signup_grant=service.SIGNUP_GRANT,
        )

    user_uuid = UUID(user.id)
    await service.grant_signup_if_needed(db, user_uuid)
    balance = await service.get_user_balance(db, user_uuid)
    return BalanceResponse(
        tokens=balance,
        pipeline_costs=pipeline_costs,
        signup_grant=service.SIGNUP_GRANT,
    )
