"""User-facing permissions surface.

Exposes a single read-only endpoint the SPA calls on auth state change
to decide which gated routes (currently /experiments) to render. The
server enforces the same whitelist on every gated endpoint
independently — this is a UX hint, not a security boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.common.auth.models import User
from services.core.app.dependencies import get_current_user, is_experimenter


router = APIRouter()


class Permissions(BaseModel):
    can_run_experiments: bool


@router.get("/permissions", response_model=Permissions)
async def get_permissions(user: User = Depends(get_current_user)) -> Permissions:
    return Permissions(can_run_experiments=is_experimenter(user))
