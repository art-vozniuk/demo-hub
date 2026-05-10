import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from services.common.auth.models import User
from services.common.database import DbSession

from . import service
from .cookies import issue_anon_id, read_anon_id
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
    request: Request,
    response: Response,
    db: DbSession,
    user: Optional[User] = Depends(_get_optional_user_dep()),
) -> BalanceResponse:
    """Read wallet balance, lazily issuing the one-time grant
    (+200 user / +15 anon) and migrating anon→user after sign-in."""

    # Bundle the cost catalog so the frontend never hardcodes prices.
    types_result = await db.execute(
        select(PipelineType.name, PipelineType.base_cost)
    )
    pipeline_costs = {name: cost for name, cost in types_result.all()}

    if user is not None:
        user_uuid = UUID(user.id)
        await service.grant_signup_if_needed(db, user_uuid)
        anon_id = read_anon_id(request)
        if anon_id is not None:
            await service.migrate_anon_to_user(db, user_uuid, anon_id)
        balance = await service.get_user_balance(db, user_uuid)
        return BalanceResponse(
            tokens=balance,
            is_anonymous=False,
            pipeline_costs=pipeline_costs,
        )

    anon_id = read_anon_id(request)
    if anon_id is None:
        anon_id = issue_anon_id(response)
    await service.grant_anon_if_needed(db, anon_id)
    balance = await service.get_anon_balance(db, anon_id)
    return BalanceResponse(
        tokens=balance,
        is_anonymous=True,
        pipeline_costs=pipeline_costs,
    )
