import logging
from fastapi import APIRouter

from services.common.database import DbSession

from .schemas import SplatSceneRead
from . import service

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/scenes", response_model=list[SplatSceneRead])
async def get_scenes(db: DbSession):
    return await service.get_all_scenes(db)
